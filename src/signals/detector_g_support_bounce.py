from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import find_swing_lows
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalGSupportBounce(BaseSignalDetector):
    """Signal G: Support / prior-swing-low bounce.
    Detects approach near a prior swing low support level and a bullish reversal candle."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.G, config)
        self.pivot_window = config.get("pivot_window", 4)
        self.support_proximity_pct = config.get("support_proximity_pct", 1.5)
        self.timeframe = config.get("timeframe", "15m")

    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        if not self.enabled:
            return None

        df_target = klines_15m if self.timeframe == "15m" else klines_1h
        if df_target is None or len(df_target) < 25:
            return None

        # Exclude the last 3 candles when looking for historical support pivots
        eval_df = df_target.iloc[:-3].copy().reset_index(drop=True)
        swing_lows = find_swing_lows(eval_df, window=self.pivot_window)
        if not swing_lows:
            return None

        # Get recent swing low closest to current price
        curr_close = float(df_target["close"].iloc[-1])
        curr_open = float(df_target["open"].iloc[-1])
        curr_low = float(df_target["low"].iloc[-1])
        curr_high = float(df_target["high"].iloc[-1])

        prev_close = float(df_target["close"].iloc[-2])
        prev_open = float(df_target["open"].iloc[-2])
        prev_low = float(df_target["low"].iloc[-2])

        # Filter swing lows that are below or around current price
        valid_supports = [sl for sl in swing_lows if sl[1] <= curr_close * 1.02]
        if not valid_supports:
            return None

        # Find the nearest support level
        nearest_idx, support_level = min(valid_supports, key=lambda x: abs(curr_low - x[1]))

        # Check proximity to support
        dist_to_support_pct = ((curr_low - support_level) / support_level) * 100.0
        if abs(dist_to_support_pct) > self.support_proximity_pct and curr_low > support_level * (
            1 + self.support_proximity_pct / 100.0
        ):
            return None

        # Reversal Candle Patterns:
        # 1. Green close after red close
        green_after_red = curr_close > curr_open and prev_close < prev_open
        # 2. Bullish engulfing
        engulfing = curr_close > prev_open and curr_open < prev_close and curr_close > curr_open and prev_close < prev_open
        # 3. Hammer (lower wick >= 2x body)
        body = abs(curr_close - curr_open)
        lower_wick = min(curr_open, curr_close) - curr_low
        hammer = lower_wick >= 2.0 * max(body, 0.0000001) and curr_close >= curr_open

        pattern = None
        if engulfing:
            pattern = "Bullish Engulfing"
        elif hammer:
            pattern = "Hammer Reversal"
        elif green_after_red:
            pattern = "Green Rebound"
        elif curr_close > curr_open:
            pattern = "Bullish Close"
        else:
            return None

        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "support_level": round(support_level, 6),
            "distance_from_support_pct": round(dist_to_support_pct, 2),
            "candle_pattern": pattern,
            "current_close": round(curr_close, 6),
            "current_low": round(curr_low, 6),
            "timeframe_used": self.timeframe,
        }

        reasoning = (
            f"{self.timeframe} tested prior swing-low support at ${support_level:.4f} (distance: {dist_to_support_pct:.2f}%) "
            f"and formed a {pattern} closing at ${curr_close:.4f}."
        )

        return SignalResult(
            signal_type=self.signal_type,
            symbol=coin.symbol,
            price_at_signal=curr_close,
            candle_timestamp=candle_ts,
            reasoning=reasoning,
            indicator_snapshot=snapshot,
            timeframe_used=self.timeframe,
        )
