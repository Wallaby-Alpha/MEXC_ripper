from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_ema
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalAPullbackReclaim(BaseSignalDetector):
    """Signal A: HTF trend + LTF pullback reclaim.
    1h: Price above rising EMA(50) and HH/HL structure.
    5m: Price dipped below/touched EMA(20) or EMA(50) and current candle closed back above it."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.A, config)
        self.htf_ema_period = config.get("htf_ema_period", 50)
        self.ltf_ema_fast = config.get("ltf_ema_fast", 20)
        self.ltf_ema_slow = config.get("ltf_ema_slow", 50)
        self.htf_structure_lookback = config.get("htf_structure_lookback", 12)
        self.max_pullback_depth_pct = config.get("max_pullback_depth_pct", 7.0)

    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        if not self.enabled or klines_1h is None or klines_5m is None:
            return None

        if len(klines_1h) < self.htf_ema_period + 2 or len(klines_5m) < self.ltf_ema_slow + 2:
            return None

        # 1h Trend Filter: Close > EMA50 and EMA50 is rising
        ema50_1h = calculate_ema(klines_1h["close"], self.htf_ema_period)
        curr_1h_close = float(klines_1h["close"].iloc[-1])
        curr_1h_ema50 = float(ema50_1h.iloc[-1])
        prev_1h_ema50 = float(ema50_1h.iloc[-2])
        ema50_slope = ((curr_1h_ema50 - prev_1h_ema50) / prev_1h_ema50) * 100.0

        if curr_1h_close <= curr_1h_ema50 or ema50_slope <= 0:
            return None

        # 1h Structure: Higher highs / Higher lows over lookback
        lookback_1h = klines_1h.iloc[-self.htf_structure_lookback :]
        min_1h_low = float(lookback_1h["low"].min())
        max_1h_high = float(lookback_1h["high"].max())
        if curr_1h_close < (min_1h_low + max_1h_high) / 2.0:
            return None

        # 5m Pullback Reclaim check:
        # Check either EMA20 or EMA50 on 5m
        ema20_5m = calculate_ema(klines_5m["close"], self.ltf_ema_fast)
        ema50_5m = calculate_ema(klines_5m["close"], self.ltf_ema_slow)

        curr_close = float(klines_5m["close"].iloc[-1])
        curr_low = float(klines_5m["low"].iloc[-1])
        prev_low = float(klines_5m["low"].iloc[-2])
        prev_close = float(klines_5m["close"].iloc[-2])

        c_ema20 = float(ema20_5m.iloc[-1])
        c_ema50 = float(ema50_5m.iloc[-1])
        p_ema20 = float(ema20_5m.iloc[-2])
        p_ema50 = float(ema50_5m.iloc[-2])

        reclaim_ema20 = (prev_low <= p_ema20 or curr_low <= c_ema20) and curr_close > c_ema20 and prev_close <= p_ema20
        reclaim_ema50 = (prev_low <= p_ema50 or curr_low <= c_ema50) and curr_close > c_ema50 and prev_close <= p_ema50

        # Also support intraday wick dip & close back above EMA on same candle
        wick_reclaim_20 = curr_low < c_ema20 and curr_close > c_ema20 and prev_close > p_ema20
        wick_reclaim_50 = curr_low < c_ema50 and curr_close > c_ema50 and prev_close > p_ema50

        reclaimed = reclaim_ema20 or reclaim_ema50 or wick_reclaim_20 or wick_reclaim_50
        if not reclaimed:
            return None

        ref_ema = c_ema20 if (reclaim_ema20 or wick_reclaim_20) else c_ema50
        pullback_depth = ((curr_close - min(curr_low, prev_low)) / curr_close) * 100.0

        if pullback_depth > self.max_pullback_depth_pct:
            return None

        candle_ts = int(klines_5m["close_time"].iloc[-1])
        ema_name = "EMA20" if (reclaim_ema20 or wick_reclaim_20) else "EMA50"

        snapshot = {
            "1h_close": curr_1h_close,
            "1h_ema50": round(curr_1h_ema50, 6),
            "1h_ema50_slope_pct": round(ema50_slope, 4),
            "5m_close": curr_close,
            "5m_ema20": round(c_ema20, 6),
            "5m_ema50": round(c_ema50, 6),
            "pullback_depth_pct": round(pullback_depth, 2),
            "reclaimed_level": ema_name,
        }

        reasoning = (
            f"1h EMA50 rising (+{ema50_slope:.3f}%), 5m pulled back ({pullback_depth:.1f}% dip) "
            f"and closed back above {ema_name} (${ref_ema:.4f}) at ${curr_close:.4f}."
        )

        return SignalResult(
            signal_type=self.signal_type,
            symbol=coin.symbol,
            price_at_signal=curr_close,
            candle_timestamp=candle_ts,
            reasoning=reasoning,
            indicator_snapshot=snapshot,
            timeframe_used="5m",
        )
