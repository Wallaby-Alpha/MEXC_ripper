"""Point-in-time universe reconstruction with listing date inference and liquidity filtering."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import pandas as pd

from config import DEFAULT_MIN_24H_TURNOVER_USDT
from src.data_ingestion.mexc_client import MexcClient
from src.data_ingestion.cache import MarketDataCache

logger = logging.getLogger(__name__)


class UniverseManager:
    """Reconstructs the point-in-time tradeable universe for a given historical window."""

    def __init__(self, client: Optional[MexcClient] = None, cache: Optional[MarketDataCache] = None):
        self.client = client or MexcClient()
        self.cache = cache or MarketDataCache()

    def build_point_in_time_universe(
        self,
        start_time_ms: int,
        end_time_ms: int,
        min_24h_turnover: float = DEFAULT_MIN_24H_TURNOVER_USDT,
        quote_asset: str = "USDT",
        max_symbols: Optional[int] = None,
    ) -> List[str]:
        """Reconstruct point-in-time universe:
        1. Fetch symbol metadata from exchangeInfo and ticker24hr.
        2. Filter for active spot USDT pairs.
        3. Exclude symbols with negligible 24h quote volume (< min_24h_turnover).
        4. Infer listing date via first available kline timestamp. Exclude if first trade > start_time_ms.
        5. Guarantee benchmark coins (BTCUSDT, ETHUSDT) are present.
        """
        logger.info("Reconstructing Point-in-Time universe for window [%s, %s]", start_time_ms, end_time_ms)

        # 1. Fetch exchange info (cached if recently saved)
        cached_meta = self.cache.get_symbol_metadata()
        if cached_meta.empty:
            logger.info("Fetching exchangeInfo and ticker/24hr from MEXC API...")
            ex_info = self.client.get_exchange_info()
            tickers_24h = self.client.get_ticker_24hr()
            ticker_vol_map = {t["symbol"]: float(t.get("quoteVolume", 0.0)) for t in tickers_24h if "symbol" in t}

            metadata_rows = []
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

            for sym_info in ex_info.get("symbols", []):
                sym = sym_info["symbol"]
                qa = sym_info.get("quoteAsset", "")
                ba = sym_info.get("baseAsset", "")
                status = str(sym_info.get("status", "1"))
                is_spot = sym_info.get("isSpotTradingAllowed", True)

                if qa == quote_asset and is_spot:
                    metadata_rows.append({
                        "symbol": sym,
                        "baseAsset": ba,
                        "quoteAsset": qa,
                        "status": status,
                        "first_kline_time": None,
                        "quoteVolume": ticker_vol_map.get(sym, 0.0),
                        "updated_at": now_ms,
                    })

            self.cache.save_symbol_metadata(metadata_rows)
            meta_df = self.cache.get_symbol_metadata()
        else:
            meta_df = cached_meta

        # Filter by liquidity floor (and ensure benchmark coins are kept)
        benchmark_symbols = {"BTCUSDT", "ETHUSDT"}
        tradeable_candidates = meta_df[
            (meta_df["quote_volume_24h"] >= min_24h_turnover) | (meta_df["symbol"].isin(benchmark_symbols))
        ].copy()

        logger.info(
            "Found %d candidate symbols clearing liquidity floor ($%.0f USDT)",
            len(tradeable_candidates),
            min_24h_turnover,
        )

        # Infer listing / trading status during window: Check if at least 1 bar exists in [start_time_ms, end_time_ms]
        valid_symbols: List[str] = []
        for _, row in tradeable_candidates.iterrows():
            sym = row["symbol"]
            first_kline_time = row["first_kline_time"]

            # If not yet known, probe if symbol traded during window
            if pd.isna(first_kline_time) or first_kline_time is None:
                window_bars = self.client.get_klines(
                    sym,
                    interval="1d",
                    start_time=start_time_ms,
                    end_time=end_time_ms,
                    limit=1,
                )
                if window_bars and len(window_bars) > 0:
                    first_kline_time = int(window_bars[0][0])
                    # Update cache
                    with self.cache._get_connection() as conn:
                        conn.execute(
                            "UPDATE symbol_metadata SET first_kline_time = ? WHERE symbol = ?",
                            (first_kline_time, sym),
                        )
                else:
                    first_kline_time = end_time_ms + 1  # Not tradeable during window

            # Must have traded during our backtest window
            if first_kline_time <= end_time_ms:
                valid_symbols.append(sym)

            if max_symbols and len(valid_symbols) >= max_symbols:
                break

        # Ensure benchmarks are included
        for b in benchmark_symbols:
            if b not in valid_symbols:
                valid_symbols.append(b)

        logger.info("Point-in-Time universe resolved with %d verified symbols.", len(valid_symbols))
        return valid_symbols
