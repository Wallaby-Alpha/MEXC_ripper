from typing import Any, Dict, Optional
import numpy as np
import pandas as pd
from src.exchange.indicators import find_swing_highs
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalBBreakoutRetest(BaseSignalDetector):
    """Signal B: Breakout + retest of prior resistance.
    Detects a broken resistance swing high that has been pulled back to and is holding."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.B, config)
        self.lookback_candles_15m = config.get("lookback_candles_15m", 32)
        self.resistance_retest_tolerance_pct = config.get("resistance_retest_tolerance_pct", 1.2)
        self.volume_breakout_multiplier = config.get("volume_breakout_multiplier", 1.5)

    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        if not self.enabled or klines_15m is None or len(klines_15m) < self.lookback_candles_15m:
            return None

        df = klines_15m.iloc[-self.lookback_candles_15m :].copy().reset_index(drop=True)
        n = len(df)
        if n < 10:
            return None

        # Find swing highs in the middle section (excluding the most recent 3 candles)
        eval_df = df.iloc[:-3].copy().reset_index(drop=True)
        swing_highs = find_swing_highs(eval_df, window=3)
        if not swing_highs:
            return None

        # Take the most prominent resistance level
        best_swing = max(swing_highs, key=lambda x: x[1])
        res_idx, resistance_level = best_swing

        # Check if price broke above this resistance with volume
        post_res_df = df.iloc[res_idx + 1 :]
        if len(post_res_df) < 3:
            return None

        # Find breakout candle
        breakout_candidates = post_res_df[post_res_df["close"] > resistance_level]
        if breakout_candidates.empty:
            return None

        breakout_candle = breakout_candidates.iloc[0]
        avg_vol = df["volume"].mean()
        if breakout_candle["volume"] < avg_vol * self.volume_breakout_multiplier:
            return None

        # Check retest & hold on the current/recent candles (last 2 candles)
        recent_candles = df.iloc[-2:]
        min_retest_low = float(recent_candles["low"].min())
        curr_close = float(df["close"].iloc[-1])

        # Retest condition: low reached near resistance level (within tolerance) and close is above resistance
        dist_to_res_pct = ((min_retest_low - resistance_level) / resistance_level) * 100.0
        if abs(dist_to_res_pct) > self.resistance_retest_tolerance_pct and min_retest_low > resistance_level * (
            1 + self.resistance_retest_tolerance_pct / 100.0
        ):
            return None

        if curr_close < resistance_level:
            return None

        candle_ts = int(df["close_time"].iloc[-1])
        curr_vs_level_pct = ((curr_close - resistance_level) / resistance_level) * 100.0

        snapshot = {
            "resistance_level": round(resistance_level, 6),
            "breakout_volume": round(float(breakout_candle["volume"]), 2),
            "avg_volume": round(float(avg_vol), 2),
            "retest_low": round(min_retest_low, 6),
            "current_close": round(curr_close, 6),
            "current_vs_level_pct": round(curr_vs_level_pct, 2),
            "tolerance_pct": self.resistance_retest_tolerance_pct,
        }

        reasoning = (
            f"Broke prior 15m resistance at ${resistance_level:.4f} with {breakout_candle['volume']/avg_vol:.1f}x volume, "
            f"tested low ${min_retest_low:.4f} and is holding above at ${curr_close:.4f} (+{curr_vs_level_pct:.2f}%)."
        )

        return SignalResult(
            signal_type=self.signal_type,
            symbol=coin.symbol,
            price_at_signal=curr_close,
            candle_timestamp=candle_ts,
            reasoning=reasoning,
            indicator_snapshot=snapshot,
            timeframe_used="15m",
        )
