from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_macd
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalIMacdCross(BaseSignalDetector):
    """Signal I: MACD bullish cross in uptrend.
    MACD(12,26,9) line crosses above Signal line while histogram turns positive."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.I, config)
        self.fast_period = config.get("fast_period", 12)
        self.slow_period = config.get("slow_period", 26)
        self.signal_period = config.get("signal_period", 9)
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
        if df_target is None or len(df_target) < self.slow_period + self.signal_period + 5:
            return None

        macd, signal, hist = calculate_macd(
            df_target["close"],
            fast=self.fast_period,
            slow=self.slow_period,
            signal=self.signal_period,
        )

        curr_macd = float(macd.iloc[-1])
        curr_signal = float(signal.iloc[-1])
        curr_hist = float(hist.iloc[-1])

        prev_macd = float(macd.iloc[-2])
        prev_signal = float(signal.iloc[-2])
        prev_hist = float(hist.iloc[-2])

        # Cross condition: MACD line crosses above signal line (or hist turns positive from <= 0)
        cross_up = (prev_macd <= prev_signal and curr_macd > curr_signal) or (prev_hist <= 0 and curr_hist > 0)

        if not cross_up:
            return None

        curr_close = float(df_target["close"].iloc[-1])
        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "macd_curr": round(curr_macd, 6),
            "signal_curr": round(curr_signal, 6),
            "hist_curr": round(curr_hist, 6),
            "macd_prev": round(prev_macd, 6),
            "signal_prev": round(prev_signal, 6),
            "hist_prev": round(prev_hist, 6),
            "timeframe_used": self.timeframe,
            "close_price": curr_close,
        }

        reasoning = (
            f"{self.timeframe} MACD({self.fast_period},{self.slow_period},{self.signal_period}) bullish cross: "
            f"MACD {curr_macd:.5f} > Signal {curr_signal:.5f}, Histogram expanded to +{curr_hist:.5f}."
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
