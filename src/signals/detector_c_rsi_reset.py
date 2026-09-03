from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_ema, calculate_rsi
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalCRsiReset(BaseSignalDetector):
    """Signal C: RSI reset in confirmed uptrend.
    1h: In uptrend (price > EMA50 or making higher highs).
    5m/15m: RSI(14) dipped into 38-52 zone and turned upwards (RSI[0] > RSI[-2] and RSI[0] > 40)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.C, config)
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_pullback_min = config.get("rsi_pullback_min", 38.0)
        self.rsi_pullback_max = config.get("rsi_pullback_max", 52.0)
        self.timeframe = config.get("timeframe", "5m")

    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        if not self.enabled or klines_1h is None:
            return None

        # 1h Trend Filter
        if len(klines_1h) < 50:
            return None
        ema50_1h = calculate_ema(klines_1h["close"], 50)
        curr_1h_close = float(klines_1h["close"].iloc[-1])
        curr_1h_ema50 = float(ema50_1h.iloc[-1])
        uptrend = curr_1h_close >= curr_1h_ema50

        if not uptrend:
            return None

        # Target timeframe klines
        df_target = klines_5m if self.timeframe == "5m" else klines_15m
        if df_target is None or len(df_target) < self.rsi_period + 5:
            return None

        rsi_series = calculate_rsi(df_target["close"], self.rsi_period)
        rsi_curr = float(rsi_series.iloc[-1])
        rsi_prev1 = float(rsi_series.iloc[-2])
        rsi_prev2 = float(rsi_series.iloc[-3])

        # Check if recent RSI dipped into reset zone (38 - 52)
        min_recent_rsi = min(rsi_curr, rsi_prev1, rsi_prev2)
        if not (self.rsi_pullback_min <= min_recent_rsi <= self.rsi_pullback_max):
            return None

        # Check if RSI is turning back up
        turning_up = rsi_curr > rsi_prev1 and rsi_curr > rsi_prev2 and rsi_curr >= 40.0
        if not turning_up:
            return None

        curr_close = float(df_target["close"].iloc[-1])
        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "1h_close": curr_1h_close,
            "1h_ema50": round(curr_1h_ema50, 6),
            "1h_trend_state": "BULLISH_ABOVE_EMA50",
            "timeframe_used": self.timeframe,
            "rsi_curr": round(rsi_curr, 2),
            "rsi_prev1": round(rsi_prev1, 2),
            "rsi_prev2": round(rsi_prev2, 2),
            "rsi_trough": round(min_recent_rsi, 2),
        }

        reasoning = (
            f"1h uptrend confirmed (Close > EMA50), {self.timeframe} RSI({self.rsi_period}) reset to {min_recent_rsi:.1f} "
            f"and turned up to {rsi_curr:.1f} (prior: {rsi_prev1:.1f}, {rsi_prev2:.1f})."
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
