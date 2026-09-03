import asyncio
from datetime import datetime, timezone
from typing import Optional, Tuple
import aiohttp
from src.config import TelegramConfig
from src.db.repository import ScannerRepository
from src.logger import get_logger
from src.models.signal import SignalResult
from src.models.universe import PumpingCoin
from src.telegram.formatter import format_telegram_alert

logger = get_logger("telegram_dispatcher")


class TelegramDispatcher:
    """Asynchronous worker that queues and rate-limits alert messages to the Telegram Bot API."""

    def __init__(self, config: TelegramConfig, repository: ScannerRepository):
        self.config = config
        self.repository = repository
        self.queue: asyncio.Queue[Tuple[SignalResult, PumpingCoin]] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._delay_between_msgs = 1.0 / max(1.0, self.config.rate_limit_msgs_per_second)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def start(self) -> None:
        """Start the background dispatcher queue worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info(
            "TelegramDispatcher started (dry_run=%s, rate_limit=%.1f msg/s)",
            self.config.dry_run,
            self.config.rate_limit_msgs_per_second,
        )

    async def stop(self) -> None:
        """Stop the background worker cleanly."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("TelegramDispatcher stopped.")

    async def dispatch(self, signal: SignalResult, coin: PumpingCoin) -> None:
        """Enqueue a signal alert for asynchronous dispatch."""
        await self.queue.put((signal, coin))

    async def _process_queue(self) -> None:
        while self._running:
            try:
                signal, coin = await self.queue.get()
                await self._send_alert(signal, coin)
                self.queue.task_done()
                await asyncio.sleep(self._delay_between_msgs)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Unexpected error in Telegram dispatch loop: %s", str(e), exc_info=True)
                await asyncio.sleep(1.0)

    async def _send_alert(self, signal: SignalResult, coin: PumpingCoin) -> None:
        text = format_telegram_alert(signal, coin)

        # Check if dry run or missing credentials
        if self.config.dry_run or not self.config.bot_token or not self.config.chat_id:
            logger.info("📢 [TELEGRAM DRY RUN / ALERT DISPATCH]\n%s", text)
            self.repository.mark_telegram_sent(
                signal.signal_id,
                sent_at=datetime.now(timezone.utc).isoformat(),
                error=None,
            )
            return

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        session = await self._get_session()
        attempts = 0

        while attempts < self.config.max_retries:
            attempts += 1
            try:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        logger.info("Alert dispatched successfully for %s (%s)", signal.symbol, signal.signal_type.value)
                        self.repository.mark_telegram_sent(
                            signal.signal_id,
                            sent_at=datetime.now(timezone.utc).isoformat(),
                            error=None,
                        )
                        return
                    elif resp.status == 429:
                        # Rate limited by Telegram API
                        data = await resp.json()
                        retry_after = data.get("parameters", {}).get("retry_after", 3)
                        logger.warning("Telegram rate limit hit (429). Backing off for %d seconds...", retry_after)
                        await asyncio.sleep(retry_after)
                    else:
                        resp_text = await resp.text()
                        logger.error(
                            "Telegram API error HTTP %d (attempt %d/%d): %s",
                            resp.status,
                            attempts,
                            self.config.max_retries,
                            resp_text,
                        )
                        await asyncio.sleep(self.config.retry_backoff_seconds * attempts)
            except Exception as e:
                logger.error("Failed sending Telegram message (attempt %d/%d): %s", attempts, self.config.max_retries, str(e))
                await asyncio.sleep(self.config.retry_backoff_seconds * attempts)

        # If all retries failed
        self.repository.mark_telegram_sent(
            signal.signal_id,
            sent_at=None,
            error=f"Failed after {self.config.max_retries} attempts",
        )
