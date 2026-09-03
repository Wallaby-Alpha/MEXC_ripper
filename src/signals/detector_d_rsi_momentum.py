from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_rsi
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalDRsiMomentum(BaseSignalDetector):
    """Signal D: RSI momentum extension (The "Chase" signal).
    1h RSI(14) crosses above 70 freshly after coming up from below 50."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.D, config)
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_threshold = config.get("rsi_threshold", 70.0)
        self.candles_since_below_50_max = config.get("candles_since_below_50_max", 20)

    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        if not self.enabled or klines_1h is None or len(klines_1h) < self.rsi_period + self.candles_since_below_50_max:
            return None

        rsi_series = calculate_rsi(klines_1h["close"], self.rsi_period)
        rsi_curr = float(rsi_series.iloc[-1])
        rsi_prev = float(rsi_series.iloc[-2])

        # Must cross above threshold (70) or be fresh > 70 with prior candle <= 70
        is_fresh_cross = rsi_curr >= self.rsi_threshold and rsi_prev < self.rsi_threshold
        if not is_fresh_cross:
            return None

        # Count candles since RSI was below 50
        history_rsi = rsi_series.iloc[-self.candles_since_below_50_max :]
        below_50_indices = history_rsi[history_rsi < 50.0].index

        candles_since_below_50 = 0
        if not below_50_indices.empty:
            last_below_idx = below_50_indices[-1]
            candles_since_below_50 = len(history_rsi) - 1 - history_rsi.index.get_loc(last_below_idx)
        else:
            candles_since_below_50 = self.candles_since_below_50_max

        curr_close = float(klines_1h["close"].iloc[-1])
        candle_ts = int(klines_1h["close_time"].iloc[-1])

        snapshot = {
            "1h_rsi_curr": round(rsi_curr, 2),
            "1h_rsi_prev": round(rsi_prev, 2),
            "rsi_threshold": self.rsi_threshold,
            "candles_since_below_50": candles_since_below_50,
            "1h_close": curr_close,
        }

        reasoning = (
            f"1h RSI({self.rsi_period}) crossed above {self.rsi_threshold} to {rsi_curr:.1f} (from {rsi_prev:.1f}); "
            f"broke out {candles_since_below_50} candles after being below 50.0."
        )

        return SignalResult(
            signal_type=self.signal_type,
            symbol=coin.symbol,
            price_at_signal=curr_close,
            candle_timestamp=candle_ts,
            reasoning=reasoning,
            indicator_snapshot=snapshot,
            timeframe_used="1h",
        )
