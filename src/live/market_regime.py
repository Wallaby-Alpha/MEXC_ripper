"""Market Regime Gate for MEXC Altcoin Momentum Scanner.
Protects long-only strategies from correlation dump cascades during adverse BTC market regimes.
Implements a Dynamic Tier Filter:
  - BULLISH: Full green light with default min_score (e.g., 80.0)
  - CAUTION_PULLBACK: BTC is below EMA50 or drifting down; elevates min_score from 80 to 90
  - CIRCUIT_BREAKER: BTC is flushing (>1.0%/1h or >0.6%/15m); completely pauses all new entries
"""
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
import pandas as pd
import numpy as np

from config import (
    ENABLE_MARKET_REGIME_GATE,
    BTC_DUMP_1H_THRESHOLD_PCT,
    BTC_DUMP_15M_THRESHOLD_PCT,
    BTC_CAUTION_SCORE_PENALTY,
    BTC_RSI_FLOOR_PANIC,
)

logger = logging.getLogger(__name__)


@dataclass
class MarketRegimeResult:
    allowed: bool
    regime: str  # "BULLISH", "CAUTION_PULLBACK", "CIRCUIT_BREAKER"
    effective_min_score: float
    btc_price: float
    btc_ema20: float
    btc_ema50: float
    btc_1h_change_pct: float
    btc_15m_change_pct: float
    btc_rsi: float
    reason: str


class MarketRegimeGate:
    """Evaluates real-time BTC benchmark bars to determine market regime and entry permissions."""

    def __init__(
        self,
        enabled: bool = ENABLE_MARKET_REGIME_GATE,
        dump_1h_threshold: float = BTC_DUMP_1H_THRESHOLD_PCT,
        dump_15m_threshold: float = BTC_DUMP_15M_THRESHOLD_PCT,
        caution_penalty: float = BTC_CAUTION_SCORE_PENALTY,
        rsi_panic_floor: float = BTC_RSI_FLOOR_PANIC,
    ):
        self.enabled = enabled
        self.dump_1h_threshold = dump_1h_threshold
        self.dump_15m_threshold = dump_15m_threshold
        self.caution_penalty = caution_penalty
        self.rsi_panic_floor = rsi_panic_floor
        self.last_result: Optional[MarketRegimeResult] = None

    def _calc_rsi(self, series: pd.Series, period: int = 14) -> float:
        """Calculates standard Wilders RSI."""
        if len(series) < period + 1:
            return 50.0
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
        if avg_loss == 0 or np.isnan(avg_loss):
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    def evaluate(self, btc_df: Optional[pd.DataFrame], base_min_score: float = 80.0) -> MarketRegimeResult:
        """Evaluates BTC price action and returns a MarketRegimeResult."""
        if not self.enabled or btc_df is None or len(btc_df) < 20:
            # Fallback when disabled or insufficient data
            res = MarketRegimeResult(
                allowed=True,
                regime="BULLISH" if self.enabled else "DISABLED",
                effective_min_score=base_min_score,
                btc_price=float(btc_df["close"].iloc[-1]) if btc_df is not None and not btc_df.empty else 0.0,
                btc_ema20=0.0,
                btc_ema50=0.0,
                btc_1h_change_pct=0.0,
                btc_15m_change_pct=0.0,
                btc_rsi=50.0,
                reason="Regime gate disabled or warm-up in progress",
            )
            self.last_result = res
            return res

        close = btc_df["close"].astype(float)
        curr_price = float(close.iloc[-1])

        # Moving averages
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=min(50, len(close)), adjust=False).mean().iloc[-1])

        # Price changes: detect 1h (approx 12 bars on 5m, 4 bars on 15m) and 15m (3 bars on 5m, 1 bar on 15m)
        bars_1h = min(12, len(close) - 1)
        bars_15m = min(3, len(close) - 1)

        ref_1h = float(close.iloc[-(bars_1h + 1)])
        ret_1h = ((curr_price - ref_1h) / ref_1h) * 100.0 if ref_1h > 0 else 0.0

        ref_15m = float(close.iloc[-(bars_15m + 1)])
        ret_15m = ((curr_price - ref_15m) / ref_15m) * 100.0 if ref_15m > 0 else 0.0

        rsi = self._calc_rsi(close, period=14)

        # -------------------------------------------------------------------------
        # TIER 3: HARD CIRCUIT BREAKER (Sharp Dump / Liquidation Cascade)
        # -------------------------------------------------------------------------
        if ret_1h <= self.dump_1h_threshold:
            reason = f"BTC 1h flash drop {ret_1h:+.2f}% exceeds circuit breaker threshold ({self.dump_1h_threshold:.1f}%)"
            res = MarketRegimeResult(
                allowed=False,
                regime="CIRCUIT_BREAKER",
                effective_min_score=999.0,
                btc_price=curr_price,
                btc_ema20=ema20,
                btc_ema50=ema50,
                btc_1h_change_pct=ret_1h,
                btc_15m_change_pct=ret_15m,
                btc_rsi=rsi,
                reason=reason,
            )
            self.last_result = res
            return res

        if ret_15m <= self.dump_15m_threshold:
            reason = f"BTC 15m dump {ret_15m:+.2f}% exceeds circuit breaker threshold ({self.dump_15m_threshold:.1f}%)"
            res = MarketRegimeResult(
                allowed=False,
                regime="CIRCUIT_BREAKER",
                effective_min_score=999.0,
                btc_price=curr_price,
                btc_ema20=ema20,
                btc_ema50=ema50,
                btc_1h_change_pct=ret_1h,
                btc_15m_change_pct=ret_15m,
                btc_rsi=rsi,
                reason=reason,
            )
            self.last_result = res
            return res

        if rsi < self.rsi_panic_floor and ret_1h < -0.80 and curr_price < ema20:
            reason = f"BTC panic RSI ({rsi:.1f} < {self.rsi_panic_floor:.1f}) with active drop ({ret_1h:+.2f}%) below EMA20"
            res = MarketRegimeResult(
                allowed=False,
                regime="CIRCUIT_BREAKER",
                effective_min_score=999.0,
                btc_price=curr_price,
                btc_ema20=ema20,
                btc_ema50=ema50,
                btc_1h_change_pct=ret_1h,
                btc_15m_change_pct=ret_15m,
                btc_rsi=rsi,
                reason=reason,
            )
            self.last_result = res
            return res

        # -------------------------------------------------------------------------
        # TIER 2: CAUTION / MILD PULLBACK (Elevate Score Threshold)
        # -------------------------------------------------------------------------
        is_below_ema50 = curr_price < ema50
        is_bearish_cross = ema20 < ema50
        is_soft_rsi = rsi < 48.0
        is_negative_1h = ret_1h < -0.30

        if is_below_ema50 or (is_bearish_cross and is_soft_rsi) or is_negative_1h:
            elevated_score = min(90.0, base_min_score + self.caution_penalty)
            sub_reasons = []
            if is_below_ema50:
                sub_reasons.append(f"Price (${curr_price:,.0f}) < EMA50 (${ema50:,.0f})")
            if is_negative_1h:
                sub_reasons.append(f"1h change {ret_1h:+.2f}%")
            if is_soft_rsi:
                sub_reasons.append(f"RSI {rsi:.1f}")

            res = MarketRegimeResult(
                allowed=True,
                regime="CAUTION_PULLBACK",
                effective_min_score=elevated_score,
                btc_price=curr_price,
                btc_ema20=ema20,
                btc_ema50=ema50,
                btc_1h_change_pct=ret_1h,
                btc_15m_change_pct=ret_15m,
                btc_rsi=rsi,
                reason=f"BTC mild pullback ({', '.join(sub_reasons)}) -> Min Score raised to {elevated_score:.0f}",
            )
            self.last_result = res
            return res

        # -------------------------------------------------------------------------
        # TIER 1: BULLISH / HEALTHY CONSOLIDATION (Full Green Light)
        # -------------------------------------------------------------------------
        res = MarketRegimeResult(
            allowed=True,
            regime="BULLISH",
            effective_min_score=base_min_score,
            btc_price=curr_price,
            btc_ema20=ema20,
            btc_ema50=ema50,
            btc_1h_change_pct=ret_1h,
            btc_15m_change_pct=ret_15m,
            btc_rsi=rsi,
            reason="BTC trending above key EMAs with positive/neutral momentum",
        )
        self.last_result = res
        return res
