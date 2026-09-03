from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_atr
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalFVolumeSpike(BaseSignalDetector):
    """Signal F: Volume spike / relative volume surge entry.
    Triggered when current candle volume is >= N times the 20-candle average."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.F, config)
        self.volume_ratio_threshold = config.get("volume_ratio_threshold", 3.0)
        self.lookback_candles = config.get("lookback_candles", 20)
        self.timeframe = config.get("timeframe", "5m")

    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        if not self.enabled:
            return None

        df_target = klines_5m if self.timeframe == "5m" else klines_15m
        if df_target is None or len(df_target) < self.lookback_candles + 2:
            return None

        # Prior lookback volume average
        prior_vol = df_target["volume"].iloc[-self.lookback_candles - 1 : -1]
        avg_vol = float(prior_vol.mean()) if not prior_vol.empty else 1.0
        if avg_vol <= 0:
            avg_vol = 1.0

        curr_vol = float(df_target["volume"].iloc[-1])
        vol_ratio = curr_vol / avg_vol

        if vol_ratio < self.volume_ratio_threshold:
            return None

        curr_open = float(df_target["open"].iloc[-1])
        curr_close = float(df_target["close"].iloc[-1])
        curr_high = float(df_target["high"].iloc[-1])
        curr_low = float(df_target["low"].iloc[-1])
        candle_direction = "GREEN" if curr_close >= curr_open else "RED"

        # Range vs ATR
        atr_series = calculate_atr(df_target, period=14)
        curr_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 1.0
        candle_range = curr_high - curr_low
        range_vs_atr_ratio = candle_range / curr_atr if curr_atr > 0 else 1.0

        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "timeframe_used": self.timeframe,
            "volume_ratio": round(vol_ratio, 2),
            "current_volume": round(curr_vol, 2),
            "avg_prior_volume": round(avg_vol, 2),
            "candle_direction": candle_direction,
            "candle_range": round(candle_range, 6),
            "atr_14": round(curr_atr, 6),
            "range_vs_atr_ratio": round(range_vs_atr_ratio, 2),
            "close_price": curr_close,
        }

        reasoning = (
            f"{self.timeframe} volume spiked to {vol_ratio:.1f}x prior 20-candle average "
            f"({candle_direction} candle, range {range_vs_atr_ratio:.1f}x ATR) at ${curr_close:.4f}."
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
