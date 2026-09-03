from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_ema, calculate_vwap
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalEVwapReclaim(BaseSignalDetector):
    """Signal E: VWAP reclaim.
    Price dipped below VWAP on 5m/15m and current candle closed back above it during 1h uptrend."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.E, config)
        self.timeframe = config.get("timeframe", "5m")
        self.max_dip_below_vwap_pct = config.get("max_dip_below_vwap_pct", 4.0)

    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        if not self.enabled:
            return None

        # 1h Trend Filter
        if klines_1h is None or len(klines_1h) < 50:
            return None
        ema50_1h = calculate_ema(klines_1h["close"], 50)
        curr_1h_close = float(klines_1h["close"].iloc[-1])
        curr_1h_ema50 = float(ema50_1h.iloc[-1])
        if curr_1h_close < curr_1h_ema50:
            return None

        df_target = klines_5m if self.timeframe == "5m" else klines_15m
        if df_target is None or len(df_target) < 20:
            return None

        vwap_series = calculate_vwap(df_target)
        curr_close = float(df_target["close"].iloc[-1])
        curr_low = float(df_target["low"].iloc[-1])
        prev_close = float(df_target["close"].iloc[-2])
        prev_low = float(df_target["low"].iloc[-2])

        c_vwap = float(vwap_series.iloc[-1])
        p_vwap = float(vwap_series.iloc[-2])

        # Dip and Reclaim conditions:
        # Case 1: Prior candle closed below VWAP and current candle closed above VWAP
        cross_reclaim = prev_close < p_vwap and curr_close > c_vwap
        # Case 2: Current candle dipped below VWAP (wick) and closed back above
        wick_reclaim = curr_low < c_vwap and curr_close > c_vwap and prev_close >= p_vwap

        if not (cross_reclaim or wick_reclaim):
            return None

        dip_price = min(curr_low, prev_low)
        dip_pct = ((c_vwap - dip_price) / c_vwap) * 100.0
        if dip_pct > self.max_dip_below_vwap_pct or dip_pct < 0:
            return None

        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "vwap_value": round(c_vwap, 6),
            "dip_price": round(dip_price, 6),
            "reclaim_close": round(curr_close, 6),
            "dip_below_vwap_pct": round(dip_pct, 2),
            "timeframe_used": self.timeframe,
            "1h_ema50": round(curr_1h_ema50, 6),
        }

        reasoning = (
            f"{self.timeframe} dipped to ${dip_price:.4f} (-{dip_pct:.2f}% below VWAP ${c_vwap:.4f}) "
            f"and closed back above VWAP at ${curr_close:.4f} while 1h uptrend holds."
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
