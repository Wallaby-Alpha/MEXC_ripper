from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_bollinger_bands
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalHBbSqueeze(BaseSignalDetector):
    """Signal H: Bollinger Band squeeze + breakout.
    Bollinger Bands (20, 2) bandwidth is at a multi-period low (squeeze) followed by close above upper band."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.H, config)
        self.bb_period = config.get("bb_period", 20)
        self.bb_std_dev = config.get("bb_std_dev", 2.0)
        self.squeeze_lookback = config.get("squeeze_lookback", 30)
        self.squeeze_percentile_threshold = config.get("squeeze_percentile_threshold", 20.0)
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
        if df_target is None or len(df_target) < self.bb_period + self.squeeze_lookback:
            return None

        mid, upper, lower, bandwidth = calculate_bollinger_bands(
            df_target["close"], period=self.bb_period, std_dev=self.bb_std_dev
        )

        curr_close = float(df_target["close"].iloc[-1])
        curr_upper = float(upper.iloc[-1])
        prev_close = float(df_target["close"].iloc[-2])
        prev_upper = float(upper.iloc[-2])

        # Breakout: current candle closes outside/above upper band
        broke_upper = curr_close >= curr_upper and (prev_close <= prev_upper or curr_close > prev_close)
        if not broke_upper:
            return None

        # Check squeeze within the prior lookback window (excluding current breakout candle)
        prior_bw = bandwidth.iloc[-self.squeeze_lookback - 1 : -1].dropna()
        if len(prior_bw) < 10:
            return None

        min_bw = float(prior_bw.min())
        curr_bw = float(bandwidth.iloc[-1])
        prev_bw = float(bandwidth.iloc[-2])

        # Calculate percentile of the bandwidth at squeeze
        bw_rank = (prior_bw < prev_bw).sum() / len(prior_bw) * 100.0

        if bw_rank > self.squeeze_percentile_threshold and min_bw > 10.0:
            # Not a tight enough squeeze
            return None

        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "bandwidth_curr": round(curr_bw, 2),
            "bandwidth_min_prior": round(min_bw, 2),
            "bandwidth_percentile": round(bw_rank, 1),
            "bb_upper": round(curr_upper, 6),
            "bb_mid": round(float(mid.iloc[-1]), 6),
            "bb_lower": round(float(lower.iloc[-1]), 6),
            "current_close": round(curr_close, 6),
            "timeframe_used": self.timeframe,
        }

        reasoning = (
            f"{self.timeframe} BB({self.bb_period},{self.bb_std_dev}) broke above upper band (${curr_upper:.4f}) "
            f"after bandwidth squeeze to {min_bw:.2f}% ({bw_rank:.0f}th percentile)."
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
