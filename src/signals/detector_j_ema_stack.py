from typing import Any, Dict, Optional
import pandas as pd
from src.exchange.indicators import calculate_ema
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.signals.base import BaseSignalDetector


class SignalJEmaStack(BaseSignalDetector):
    """Signal J: Simple moving average stack alignment.
    EMA(9) > EMA(21) > EMA(50) on 15m, freshly aligned within the last 1-2 candles."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(SignalType.J, config)
        self.ema_fast = config.get("ema_fast", 9)
        self.ema_mid = config.get("ema_mid", 21)
        self.ema_slow = config.get("ema_slow", 50)
        self.max_candles_since_aligned = config.get("max_candles_since_aligned", 2)
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
        if df_target is None or len(df_target) < self.ema_slow + 10:
            return None

        e_fast = calculate_ema(df_target["close"], self.ema_fast)
        e_mid = calculate_ema(df_target["close"], self.ema_mid)
        e_slow = calculate_ema(df_target["close"], self.ema_slow)

        # Check current alignment: Fast > Mid > Slow
        c_f, c_m, c_s = float(e_fast.iloc[-1]), float(e_mid.iloc[-1]), float(e_slow.iloc[-1])
        is_aligned_now = (c_f > c_m) and (c_m > c_s)

        if not is_aligned_now:
            return None

        # Check how many candles back this alignment started
        # It must be fresh (i.e., not aligned 2-3 candles ago)
        aligned_history = (e_fast > e_mid) & (e_mid > e_slow)
        
        # Check alignment count in recent candles
        recent_aligned_count = 0
        for val in reversed(aligned_history.iloc[-10:].values):
            if val:
                recent_aligned_count += 1
            else:
                break

        if recent_aligned_count > self.max_candles_since_aligned:
            # Already aligned for too long; not a fresh signal
            return None

        curr_close = float(df_target["close"].iloc[-1])
        candle_ts = int(df_target["close_time"].iloc[-1])

        snapshot = {
            "ema_fast": round(c_f, 6),
            "ema_mid": round(c_m, 6),
            "ema_slow": round(c_s, 6),
            "candles_since_aligned": recent_aligned_count,
            "timeframe_used": self.timeframe,
            "close_price": curr_close,
        }

        reasoning = (
            f"{self.timeframe} EMA stack freshly aligned: EMA({self.ema_fast}) ${c_f:.4f} > "
            f"EMA({self.ema_mid}) ${c_m:.4f} > EMA({self.ema_slow}) ${c_s:.4f} ({recent_aligned_count} candle(s) ago)."
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
