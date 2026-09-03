import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
from src.config import ScreeningConfig
from src.db.repository import ScannerRepository
from src.exchange.mexc_client import MexcClient
from src.logger import get_logger
from src.models.universe import PumpingCoin, PumpingUniverseEvent, UniverseEventType

logger = get_logger("universe_manager")


class UniverseManager:
    """Manages the rolling pumping universe of coins, filtering, and lifecycle events."""

    def __init__(
        self,
        config: ScreeningConfig,
        mexc_client: MexcClient,
        repository: ScannerRepository,
    ):
        self.config = config
        self.mexc_client = mexc_client
        self.repository = repository
        self._current_universe: Dict[str, PumpingCoin] = {}

    @property
    def current_universe(self) -> Dict[str, PumpingCoin]:
        return self._current_universe

    def is_valid_symbol(self, symbol: str) -> bool:
        """Filter out non-target quote currencies, leveraged tokens, and stablecoin pairs."""
        if not symbol.endswith(self.config.quote_currency):
            return False

        base = symbol[: -len(self.config.quote_currency)]

        # Check stablecoins
        if base in self.config.stablecoins:
            return False

        # Check leveraged token patterns
        for pattern in self.config.exclude_patterns:
            if pattern in base:
                return False

        return True

    async def scan_market(self) -> Dict[str, PumpingCoin]:
        """Poll 24h tickers and evaluate coins against pumping criteria."""
        tickers = await self.mexc_client.get_24hr_tickers()
        if not tickers:
            logger.warning("No tickers retrieved from MEXC.")
            return self._current_universe

        candidate_tickers = []
        for t in tickers:
            symbol = t.get("symbol", "")
            if not self.is_valid_symbol(symbol):
                continue

            try:
                quote_vol = float(t.get("quoteVolume", 0.0))
                last_price = float(t.get("lastPrice", 0.0))
            except (ValueError, TypeError):
                continue

            if quote_vol < self.config.min_quote_volume_24h_usd or last_price <= 0:
                continue

            candidate_tickers.append((symbol, last_price, quote_vol, t))

        logger.info(
            "Screened %d valid candidate pairs with >=$%sk 24h volume",
            len(candidate_tickers),
            int(self.config.min_quote_volume_24h_usd / 1000),
        )

        # For candidates, fetch 1h klines to calculate precise 1h and 4h price change & volume surge
        new_universe: Dict[str, PumpingCoin] = {}
        now = datetime.now(timezone.utc)

        # Batch pull 1h klines for candidate tokens
        async def evaluate_candidate(cand: Tuple[str, float, float, Dict]) -> Optional[PumpingCoin]:
            sym, price, quote_vol, raw_t = cand
            # Pull last 5 1h candles
            df_1h = await self.mexc_client.get_klines(sym, interval="1h", limit=6)
            if df_1h is None or len(df_1h) < 2:
                return None

            close_series = df_1h["close"]
            current_close = float(close_series.iloc[-1])
            prev_1h_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_close
            prev_4h_close = float(close_series.iloc[-5]) if len(close_series) >= 5 else float(close_series.iloc[0])

            change_1h_pct = ((current_close - prev_1h_close) / prev_1h_close) * 100.0 if prev_1h_close > 0 else 0.0
            change_4h_pct = ((current_close - prev_4h_close) / prev_4h_close) * 100.0 if prev_4h_close > 0 else 0.0

            # Calculate volume surge ratio: current 1h volume vs (24h quote volume / 24)
            current_1h_quote_vol = float(df_1h["quote_volume"].iloc[-1])
            avg_hourly_vol = quote_vol / 24.0 if quote_vol > 0 else 1.0
            volume_surge_ratio = current_1h_quote_vol / avg_hourly_vol if avg_hourly_vol > 0 else 0.0

            # Evaluation criteria:
            # 1h change >= min_1h OR 4h change >= min_4h
            meets_1h = change_1h_pct >= self.config.min_price_change_1h_pct
            meets_4h = change_4h_pct >= self.config.min_price_change_4h_pct

            if meets_1h or meets_4h:
                reasons = []
                if meets_1h:
                    reasons.append(f"1h +{change_1h_pct:.2f}% (>= {self.config.min_price_change_1h_pct}%)")
                if meets_4h:
                    reasons.append(f"4h +{change_4h_pct:.2f}% (>= {self.config.min_price_change_4h_pct}%)")
                if volume_surge_ratio >= self.config.volume_surge_multiplier:
                    reasons.append(f"Vol surge {volume_surge_ratio:.1f}x")

                return PumpingCoin(
                    symbol=sym,
                    price=current_close,
                    price_change_1h_pct=round(change_1h_pct, 2),
                    price_change_4h_pct=round(change_4h_pct, 2),
                    volume_surge_ratio=round(volume_surge_ratio, 2),
                    quote_volume_24h=round(quote_vol, 2),
                    entered_at=now,
                    last_updated_at=now,
                    trigger_reason=", ".join(reasons),
                )
            return None

        # Execute candidate evaluations concurrently in chunks
        chunk_size = 30
        for i in range(0, len(candidate_tickers), chunk_size):
            chunk = candidate_tickers[i : i + chunk_size]
            results = await asyncio.gather(*(evaluate_candidate(c) for c in chunk), return_exceptions=True)
            for res in results:
                if isinstance(res, PumpingCoin):
                    new_universe[res.symbol] = res

        # Update and log transitions
        await self._process_universe_transitions(new_universe, now)
        self._current_universe = new_universe

        logger.info(
            "Pumping universe updated: %d active pumping coins (%s)",
            len(self._current_universe),
            ", ".join(list(self._current_universe.keys())[:10]) + ("..." if len(self._current_universe) > 10 else ""),
        )
        return self._current_universe

    async def _process_universe_transitions(
        self, new_universe: Dict[str, PumpingCoin], now: datetime
    ) -> None:
        """Detect and persist ENTER and EXIT events for the pumping universe."""
        old_symbols: Set[str] = set(self._current_universe.keys())
        new_symbols: Set[str] = set(new_universe.keys())

        entered = new_symbols - old_symbols
        exited = old_symbols - new_symbols

        for sym in entered:
            coin = new_universe[sym]
            event = PumpingUniverseEvent(
                symbol=sym,
                event_type=UniverseEventType.ENTER,
                timestamp_utc=now.isoformat(),
                price=coin.price,
                price_change_1h_pct=coin.price_change_1h_pct,
                price_change_4h_pct=coin.price_change_4h_pct,
                volume_surge_ratio=coin.volume_surge_ratio,
                quote_volume_24h=coin.quote_volume_24h,
                reason=coin.trigger_reason,
                metrics_json=json.dumps(coin.to_context_dict()),
            )
            self.repository.log_universe_event(event)
            logger.info("🟢 [UNIVERSE ENTER] %s | %s | Price: $%s", sym, coin.trigger_reason, coin.price)

        for sym in exited:
            coin = self._current_universe[sym]
            event = PumpingUniverseEvent(
                symbol=sym,
                event_type=UniverseEventType.EXIT,
                timestamp_utc=now.isoformat(),
                price=coin.price,
                price_change_1h_pct=coin.price_change_1h_pct,
                price_change_4h_pct=coin.price_change_4h_pct,
                volume_surge_ratio=coin.volume_surge_ratio,
                quote_volume_24h=coin.quote_volume_24h,
                reason="Fell below 1h/4h momentum thresholds",
                metrics_json=json.dumps(coin.to_context_dict()),
            )
            self.repository.log_universe_event(event)
            logger.info("🔴 [UNIVERSE EXIT] %s | Price: $%s", sym, coin.price)
