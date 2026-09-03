from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_supertrend
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalKSupertrendFlip(BaseSignalDetector):
    """Signal K: Supertrend Bullish Flip (Bonus Signal).
    Supertrend(10, 3.0) flips from Bearish (-1) to Bullish (+1) on 15m/5m."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.K, config)
        self.period = config.get("period", 10)
        self.multiplier = config.get("multiplier", 3.0)
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

        df_target = klines_15m if self.timeframe == "15m" else klines_5m
        if df_target is None or len(df_target) < self.period + 10:
            return None

        st_series, dir_series = calculate_supertrend(
            df_target, period=self.period, multiplier=self.multiplier
        )

        curr_dir = int(dir_series.iloc[-1])
        prev_dir = int(dir_series.iloc[-2])

        # Bullish flip: direction changes from -1 to 1
        if not (prev_dir == -1 and curr_dir == 1):
            return None

        curr_close = float(df_target["close"].iloc[-1])
        curr_st = float(st_series.iloc[-1])
        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "supertrend_value": round(curr_st, 6),
            "period": self.period,
            "multiplier": self.multiplier,
            "direction_prev": prev_dir,
            "direction_curr": curr_dir,
            "timeframe_used": self.timeframe,
            "close_price": curr_close,
        }

        reasoning = (
            f"{self.timeframe} Supertrend({self.period},{self.multiplier}) flipped BULLISH "
            f"with stop support at ${curr_st:.4f} (Close: ${curr_close:.4f})."
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
