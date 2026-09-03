import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
from src.config import ForwardReturnsConfig
from src.db.repository import ScannerRepository
from src.exchange.mexc_client import MexcClient
from src.logger import get_logger
from src.models.returns import ForwardReturnRecord, ForwardReturnStatus

logger = get_logger("forward_tracker")


class ForwardReturnTracker:
    """Background worker that revisits logged signals at +5m, +15m, +1h, +4h, +24h to record price outcomes."""

    def __init__(
        self,
        config: ForwardReturnsConfig,
        repository: ScannerRepository,
        mexc_client: MexcClient,
    ):
        self.config = config
        self.repository = repository
        self.mexc_client = mexc_client
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the periodic background evaluation loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._tracker_loop())
        logger.info("ForwardReturnTracker started (check_interval=%ds)", self.config.check_interval_seconds)

    async def stop(self) -> None:
        """Stop the background tracker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ForwardReturnTracker stopped.")

    async def _tracker_loop(self) -> None:
        while self._running:
            try:
                await self.evaluate_pending_signals()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in ForwardReturnTracker loop: %s", str(e), exc_info=True)

            await asyncio.sleep(self.config.check_interval_seconds)

    async def evaluate_pending_signals(self) -> int:
        """Evaluate all pending forward return records whose time horizons have elapsed."""
        pending = self.repository.get_pending_forward_returns(limit=self.config.batch_size)
        if not pending:
            return 0

        now_utc = datetime.now(timezone.utc)
        updated_count = 0

        for item in pending:
            try:
                signal_time = datetime.fromisoformat(item["signal_timestamp_utc"])
                if signal_time.tzinfo is None:
                    signal_time = signal_time.replace(tzinfo=timezone.utc)

                elapsed_seconds = (now_utc - signal_time).total_seconds()
                # If less than 5 minutes have elapsed, nothing to evaluate yet
                if elapsed_seconds < 300:
                    continue

                updated = await self._evaluate_single_record(item, elapsed_seconds)
                if updated:
                    updated_count += 1
            except Exception as e:
                logger.warning("Failed evaluating forward returns for signal %s: %s", item.get("signal_id"), str(e))

        if updated_count > 0:
            logger.info("Updated forward returns for %d signal(s)", updated_count)
        return updated_count

    async def _evaluate_single_record(self, item: Dict[str, Any], elapsed_seconds: float) -> bool:
        symbol = item["symbol"]
        price_at_signal = float(item["price_at_signal"])
        candle_ts = int(item["candle_timestamp"])  # epoch ms

        # Fetch 5m or 15m klines around the signal timestamp
        df_klines = await self.mexc_client.get_klines(
            symbol=symbol,
            interval="5m",
            limit=300,
            start_time=candle_ts,
        )
        if df_klines is None or df_klines.empty:
            return False

        # Sort and ensure numeric
        df_klines = df_klines.sort_values("open_time").reset_index(drop=True)

        record = ForwardReturnRecord(
            signal_id=item["signal_id"],
            symbol=symbol,
            price_at_signal=price_at_signal,
            signal_timestamp_utc=item["signal_timestamp_utc"],
            price_5m=item.get("price_5m"),
            price_15m=item.get("price_15m"),
            price_1h=item.get("price_1h"),
            price_4h=item.get("price_4h"),
            price_24h=item.get("price_24h"),
            return_5m_pct=item.get("return_5m_pct"),
            return_15m_pct=item.get("return_15m_pct"),
            return_1h_pct=item.get("return_1h_pct"),
            return_4h_pct=item.get("return_4h_pct"),
            return_24h_pct=item.get("return_24h_pct"),
            max_runup_24h_pct=item.get("max_runup_24h_pct"),
            max_drawdown_24h_pct=item.get("max_drawdown_24h_pct"),
            status=ForwardReturnStatus(item.get("status", "PENDING")),
        )

        has_changes = False

        # Helper to find close price closest to target ms
        def get_price_at_offset_minutes(minutes: int) -> Optional[float]:
            target_ms = candle_ts + (minutes * 60 * 1000)
            matching = df_klines[df_klines["open_time"] >= target_ms]
            if not matching.empty:
                return float(matching.iloc[0]["close"])
            return None

        # 1. +5m
        if record.price_5m is None and elapsed_seconds >= 300:
            p_5m = get_price_at_offset_minutes(5)
            if p_5m is not None:
                record.price_5m = p_5m
                record.return_5m_pct = round(((p_5m - price_at_signal) / price_at_signal) * 100.0, 3)
                record.status = ForwardReturnStatus.PARTIALLY_FILLED
                has_changes = True

        # 2. +15m
        if record.price_15m is None and elapsed_seconds >= 900:
            p_15m = get_price_at_offset_minutes(15)
            if p_15m is not None:
                record.price_15m = p_15m
                record.return_15m_pct = round(((p_15m - price_at_signal) / price_at_signal) * 100.0, 3)
                record.status = ForwardReturnStatus.PARTIALLY_FILLED
                has_changes = True

        # 3. +1h (60m)
        if record.price_1h is None and elapsed_seconds >= 3600:
            p_1h = get_price_at_offset_minutes(60)
            if p_1h is not None:
                record.price_1h = p_1h
                record.return_1h_pct = round(((p_1h - price_at_signal) / price_at_signal) * 100.0, 3)
                record.status = ForwardReturnStatus.PARTIALLY_FILLED
                has_changes = True

        # 4. +4h (240m)
        if record.price_4h is None and elapsed_seconds >= 14400:
            p_4h = get_price_at_offset_minutes(240)
            if p_4h is not None:
                record.price_4h = p_4h
                record.return_4h_pct = round(((p_4h - price_at_signal) / price_at_signal) * 100.0, 3)
                record.status = ForwardReturnStatus.PARTIALLY_FILLED
                has_changes = True

        # 5. +24h (1440m) + Max Runup / Max Drawdown
        if record.price_24h is None and elapsed_seconds >= 86400:
            # Need 1h klines for 24h window
            df_24h = await self.mexc_client.get_klines(
                symbol=symbol,
                interval="1h",
                limit=30,
                start_time=candle_ts,
            )
            if df_24h is not None and len(df_24h) >= 24:
                p_24h = float(df_24h.iloc[24]["close"]) if len(df_24h) > 24 else float(df_24h.iloc[-1]["close"])
                record.price_24h = p_24h
                record.return_24h_pct = round(((p_24h - price_at_signal) / price_at_signal) * 100.0, 3)

                # Compute Max Runup (MFE) and Max Drawdown (MAE) over the 24h candles
                window_24h = df_24h.iloc[:25]
                max_high = float(window_24h["high"].max())
                min_low = float(window_24h["low"].min())

                record.max_runup_24h_pct = round(((max_high - price_at_signal) / price_at_signal) * 100.0, 3)
                record.max_drawdown_24h_pct = round(((min_low - price_at_signal) / price_at_signal) * 100.0, 3)
                record.status = ForwardReturnStatus.COMPLETED
                has_changes = True

        if has_changes:
            record.last_evaluated_at = datetime.now(timezone.utc).isoformat()
            self.repository.update_forward_return(record)
            return True

        return False
