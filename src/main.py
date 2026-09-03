import asyncio
import signal
import sys
import time
from typing import Dict, List, Optional
from src.config import Config, load_config
from src.db.database import Database
from src.db.repository import ScannerRepository
from src.exchange.mexc_client import MexcClient
from src.logger import get_logger, setup_logger
from src.models.signal import SignalResult
from src.models.universe import PumpingCoin
from src.scanner.universe_manager import UniverseManager
from src.signals.registry import SignalRegistry
from src.telegram.dispatcher import TelegramDispatcher
from src.tracker.forward_return_tracker import ForwardReturnTracker

logger = get_logger("main")


class MomentumScannerApp:
    """Main orchestrator for MEXC Momentum Scanner, Signal Engine, and Alert Dispatcher."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        setup_logger(
            name="mexc_scanner",
            log_dir=self.config.app.log_dir,
            log_file="scanner.log",
            level="INFO",
        )
        self.db = Database(self.config.app.db_path)
        self.repository = ScannerRepository(self.db)
        self.mexc_client = MexcClient(self.config.mexc)
        self.universe_manager = UniverseManager(
            self.config.screening, self.mexc_client, self.repository
        )
        self.signal_registry = SignalRegistry(self.config.signals)
        self.dispatcher = TelegramDispatcher(self.config.telegram, self.repository)
        self.tracker = ForwardReturnTracker(
            self.config.forward_returns, self.repository, self.mexc_client
        )
        self._running = False

    async def run_single_scan_cycle(self) -> int:
        """Run one complete screening and signal evaluation cycle across the pumping universe."""
        start_time = time.time()
        logger.info("=== Starting Scan Cycle ===")

        # 1. Screen pumping universe
        pumping_coins = await self.universe_manager.scan_market()
        if not pumping_coins:
            logger.info("Pumping universe is empty. Cycle finished in %.2fs", time.time() - start_time)
            return 0

        signals_fired_count = 0
        detectors = self.signal_registry.get_active_detectors()

        # 2. Evaluate signals for each coin
        for symbol, coin in pumping_coins.items():
            try:
                # Fetch multi-timeframe klines (1h, 15m, 5m)
                klines_map = await self.mexc_client.get_multi_timeframe_klines(symbol)
                k_1h = klines_map.get("1h")
                k_15m = klines_map.get("15m")
                k_5m = klines_map.get("5m")

                # Evaluate all independent signal modules
                for detector in detectors:
                    try:
                        res: Optional[SignalResult] = detector.evaluate(coin, k_1h, k_15m, k_5m)
                        if res:
                            # Check duplicate candle close timestamp
                            if self.repository.is_duplicate_candle_signal(
                                res.symbol, res.signal_type.value, res.candle_timestamp
                            ):
                                logger.debug(
                                    "Duplicate candle signal suppressed: %s [%s] @ candle %d",
                                    res.symbol,
                                    res.signal_type.value,
                                    res.candle_timestamp,
                                )
                                continue

                            # Persist signal and create pending forward-return record
                            inserted = self.repository.insert_signal(
                                signal=res,
                                change_1h=coin.price_change_1h_pct,
                                change_4h=coin.price_change_4h_pct,
                                volume_surge_ratio=coin.volume_surge_ratio,
                                quote_volume_24h=coin.quote_volume_24h,
                            )

                            if inserted:
                                signals_fired_count += 1
                                logger.info(
                                    "🔥 [SIGNAL FIRED] %s [%s] | Price: $%s | %s",
                                    res.symbol,
                                    res.signal_type.value,
                                    res.price_at_signal,
                                    res.reasoning,
                                )
                                # Dispatch Telegram Alert
                                await self.dispatcher.dispatch(res, coin)
                    except Exception as sig_err:
                        logger.error(
                            "Error evaluating %s for %s: %s",
                            detector.signal_type.value,
                            symbol,
                            str(sig_err),
                            exc_info=True,
                        )

            except Exception as coin_err:
                logger.error("Error processing coin %s: %s", symbol, str(coin_err), exc_info=True)

        cycle_duration = time.time() - start_time
        logger.info(
            "=== Scan Cycle Complete: %d pumping coins evaluated, %d signals fired in %.2fs ===",
            len(pumping_coins),
            signals_fired_count,
            cycle_duration,
        )
        return signals_fired_count

    async def start(self) -> None:
        """Start the daemon scanner loop and background tasks."""
        self._running = True
        logger.info("Initializing MEXC Altcoin Momentum Scanner Daemon...")

        # Start background workers
        await self.dispatcher.start()
        if self.config.forward_returns.enabled:
            await self.tracker.start()

        # Handle graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            except (NotImplementedError, AttributeError):
                # Windows doesn't support add_signal_handler for all signals
                pass

        try:
            while self._running:
                try:
                    await self.run_single_scan_cycle()
                except Exception as e:
                    logger.error("Fatal error during scan cycle: %s", str(e), exc_info=True)

                # Sleep until next cycle
                await asyncio.sleep(self.config.screening.poll_interval_seconds)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def stop(self) -> None:
        logger.info("Shutdown signal received. Stopping scanner...")
        self._running = False

    async def shutdown(self) -> None:
        logger.info("Cleaning up resources...")
        await self.dispatcher.stop()
        if self.config.forward_returns.enabled:
            await self.tracker.stop()
        await self.mexc_client.close()
        logger.info("MEXC Scanner shut down cleanly.")


def main() -> None:
    app = MomentumScannerApp()
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")


if __name__ == "__main__":
    main()
