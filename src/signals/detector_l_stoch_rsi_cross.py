from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_stoch_rsi
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalLStochRsiCross(BaseSignalDetector):
    """Signal L: Stochastic RSI Oversold Bullish Cross (Bonus Signal).
    Stochastic RSI (%K crosses above %D) while in or rising out of oversold territory (< 25)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.L, config)
        self.rsi_period = config.get("rsi_period", 14)
        self.stoch_period = config.get("stoch_period", 14)
        self.k_period = config.get("k_period", 3)
        self.d_period = config.get("d_period", 3)
        self.oversold_threshold = config.get("oversold_threshold", 25.0)
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
        if df_target is None or len(df_target) < self.rsi_period + self.stoch_period + 5:
            return None

        k, d = calculate_stoch_rsi(
            df_target["close"],
            rsi_period=self.rsi_period,
            stoch_period=self.stoch_period,
            k_period=self.k_period,
            d_period=self.d_period,
        )

        curr_k = float(k.iloc[-1])
        curr_d = float(d.iloc[-1])
        prev_k = float(k.iloc[-2])
        prev_d = float(d.iloc[-2])

        # Bullish cross condition: %K crosses above %D
        cross_up = prev_k <= prev_d and curr_k > curr_d
        # Oversold condition: recent %K or %D was below threshold
        was_oversold = min(prev_k, prev_d, curr_k, curr_d) <= self.oversold_threshold

        if not (cross_up and was_oversold):
            return None

        curr_close = float(df_target["close"].iloc[-1])
        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "stoch_k_curr": round(curr_k, 2),
            "stoch_d_curr": round(curr_d, 2),
            "stoch_k_prev": round(prev_k, 2),
            "stoch_d_prev": round(prev_d, 2),
            "oversold_threshold": self.oversold_threshold,
            "timeframe_used": self.timeframe,
            "close_price": curr_close,
        }

        reasoning = (
            f"{self.timeframe} Stoch RSI({self.rsi_period},{self.stoch_period},{self.k_period},{self.d_period}) "
            f"bullish cross in oversold zone (%K {curr_k:.1f} > %D {curr_d:.1f}) at ${curr_close:.4f}."
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
