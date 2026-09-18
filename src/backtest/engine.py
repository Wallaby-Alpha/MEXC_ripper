"""Walk-forward backtest engine with cheap pre-filter and full feature logging."""
import logging
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from tqdm import tqdm

from config import (
    DEFAULT_INTERVAL,
    DEFAULT_START_TIME,
    DEFAULT_END_TIME,
    PREFILTER_MIN_RVOL_20,
    PREFILTER_MIN_1H_RETURN_PCT,
    PROCESSED_DATA_DIR,
)
from src.data_ingestion.mexc_client import MexcClient
from src.data_ingestion.cache import MarketDataCache
from src.data_ingestion.universe import UniverseManager
from src.features.feature_pipeline import extract_features_point_in_time
from src.backtest.labeler import label_forward_outcomes

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Walks forward through the historical window bar-by-bar, filters candidates,
    extracts zero-lookahead feature vectors, and labels forward outcomes.
    """

    def __init__(
        self,
        client: Optional[MexcClient] = None,
        cache: Optional[MarketDataCache] = None,
        interval: str = DEFAULT_INTERVAL,
    ):
        self.client = client or MexcClient()
        self.cache = cache or MarketDataCache()
        self.universe_mgr = UniverseManager(client=self.client, cache=self.cache)
        self.interval = interval

    def run(
        self,
        start_time_iso: str = DEFAULT_START_TIME,
        end_time_iso: str = DEFAULT_END_TIME,
        symbols: Optional[List[str]] = None,
        max_symbols: Optional[int] = 30,
        min_24h_turnover: float = 50_000.0,
    ) -> pd.DataFrame:
        """Runs the walk-forward backtest across the point-in-time universe."""
        t_start = int(datetime.fromisoformat(start_time_iso.replace("Z", "+00:00")).timestamp() * 1000)
        t_end = int(datetime.fromisoformat(end_time_iso.replace("Z", "+00:00")).timestamp() * 1000)

        # 1. Reconstruct Point-in-time universe
        if not symbols:
            symbols = self.universe_mgr.build_point_in_time_universe(
                start_time_ms=t_start,
                end_time_ms=t_end,
                min_24h_turnover=min_24h_turnover,
                max_symbols=max_symbols,
            )

        logger.info("Starting walk-forward backtest for %d symbols across [%s, %s]", len(symbols), start_time_iso, end_time_iso)

        # Ensure benchmarks are loaded first for relative strength
        benchmark_symbols = ["BTCUSDT", "ETHUSDT"]
        bench_data: Dict[str, pd.DataFrame] = {}
        for b_sym in benchmark_symbols:
            bench_df = self._ensure_klines_cached(b_sym, t_start, t_end)
            bench_data[b_sym] = bench_df

        btc_df = bench_data.get("BTCUSDT")
        eth_df = bench_data.get("ETHUSDT")

        candidate_records: List[Dict[str, Any]] = []

        # Iterate over universe
        for sym in tqdm(symbols, desc="Evaluating Symbols"):
            if sym in benchmark_symbols:
                continue  # BTC/ETH are relative strength benchmarks, not altcoin candidates

            # Load historical data including lookback padding (e.g. 5 days prior for 288-bar features)
            padding_ms = 5 * 24 * 3600 * 1000  # 5 days
            kline_df = self._ensure_klines_cached(sym, t_start - padding_ms, t_end + 2 * 24 * 3600 * 1000)

            if kline_df.empty or len(kline_df) < 65:
                continue

            # Walk forward through evaluation window
            eval_mask = (kline_df["open_time"] >= t_start) & (kline_df["open_time"] <= t_end)
            eval_indices = np.where(eval_mask)[0]

            for idx in eval_indices:
                bar_open_time = int(kline_df["open_time"].iloc[idx])
                bar_close = float(kline_df["close"].iloc[idx])
                bar_vol = float(kline_df["volume"].iloc[idx])

                # Cheap pre-filter to control compute cost:
                # Must have: rvol_20 > 2.0 OR 1h_return > 3.0%
                if idx < 20:
                    continue

                prev_vols = kline_df["volume"].iloc[idx - 20 : idx].values
                base_vol = np.mean(prev_vols) if len(prev_vols) > 0 else 1.0
                rvol_20 = (bar_vol / base_vol) if base_vol > 0 else 1.0

                prev_close_1h = float(kline_df["close"].iloc[max(0, idx - 12)])
                ret_1h_pct = ((bar_close - prev_close_1h) / prev_close_1h * 100.0) if prev_close_1h > 0 else 0.0

                passes_prefilter = (rvol_20 >= PREFILTER_MIN_RVOL_20) or (ret_1h_pct >= PREFILTER_MIN_1H_RETURN_PCT)

                if not passes_prefilter:
                    continue

                # Candidate identified! Compute FULL feature set strictly using data <= bar_open_time
                history_df = kline_df.iloc[: idx + 1]

                try:
                    feat_dict = extract_features_point_in_time(
                        symbol=sym,
                        timestamp_ms=bar_open_time,
                        klines_df=history_df,
                        btc_klines_df=btc_df,
                        eth_klines_df=eth_df,
                    )
                except Exception as exc:
                    logger.warning("Feature extraction failed for %s at %s: %s", sym, bar_open_time, exc)
                    continue

                # Forward outcome labeling using forward bars (strictly > idx)
                forward_bars = kline_df.iloc[idx + 1 : idx + 1 + 576]  # up to 48h forward
                label_dict = label_forward_outcomes(
                    entry_close=bar_close,
                    entry_time_ms=bar_open_time,
                    forward_klines_df=forward_bars,
                )

                # Combine features and forward labels
                record = {**feat_dict, **label_dict}
                candidate_records.append(record)

        results_df = pd.DataFrame(candidate_records)
        logger.info("Backtest complete. Identified %d pump candidate events.", len(results_df))

        # Save processed dataset
        if not results_df.empty:
            csv_path = PROCESSED_DATA_DIR / "candidates_labeled.csv"
            parquet_path = PROCESSED_DATA_DIR / "candidates_labeled.parquet"
            results_df.to_csv(csv_path, index=False)
            results_df.to_parquet(parquet_path, index=False)
            logger.info("Datasets saved to %s and %s", csv_path, parquet_path)

        return results_df

    def _ensure_klines_cached(self, symbol: str, start_time: int, end_time: int) -> pd.DataFrame:
        """Retrieves klines from cache, or fetches from MEXC and updates cache."""
        cached_min, cached_max = self.cache.get_kline_range(symbol, self.interval)

        # If cache is missing or doesn't cover range, fetch
        if cached_min is None or cached_min > start_time or cached_max < end_time:
            try:
                fetch_start = start_time if cached_min is None else min(start_time, cached_min)
                fetch_end = end_time if cached_max is None else max(end_time, cached_max)
                bars = self.client.paginate_klines(symbol, self.interval, fetch_start, fetch_end)
                if bars:
                    self.cache.save_klines(symbol, self.interval, bars)
            except Exception as exc:
                logger.warning("Failed fetching klines for %s: %s", symbol, exc)

        return self.cache.get_klines(symbol, self.interval, start_time, end_time)
