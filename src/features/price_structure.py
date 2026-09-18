"""Price structure features (breakout, base quality, retest hold, swing structure, extension ATR)."""
import numpy as np
import pandas as pd
from typing import Dict, Any


def compute_price_structure_features(
    df: pd.DataFrame,
    breakout_lookback: int = 20,
    buffer_pct: float = 0.005,  # 0.5% buffer above range high
    atr_period: int = 14,
) -> Dict[str, float]:
    """Computes price structure features strictly using bars <= current bar."""
    features: Dict[str, float] = {
        "pre_breakout_base_quality": 0.0,
        "breakout_flag": 0.0,
        "retest_hold_flag": 0.0,
        "swing_structure_hh_hl": 0.0,
        "extension_atr": 0.0,
        "atr_14": 0.0,
        "atr_pct": 0.0,
    }

    if df.empty or len(df) < breakout_lookback + 5:
        return features

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    vol = df["volume"].values
    n = len(df)

    # 1. Compute True Range and ATR_14
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr = np.insert(tr, 0, high[0] - low[0])

    if len(tr) >= atr_period:
        # Exponential or simple moving average of TR
        atr = np.mean(tr[-atr_period:])
    else:
        atr = np.mean(tr)
    features["atr_14"] = float(atr)
    current_close = close[-1]
    features["atr_pct"] = float(atr / current_close) if current_close > 0 else 0.0

    # 2. Breakout detection: Prior N-bar high (strictly excluding current bar!)
    prior_highs = high[-breakout_lookback - 1 : -1]
    prior_lows = low[-breakout_lookback - 1 : -1]
    prior_max_high = float(np.max(prior_highs))
    prior_min_low = float(np.min(prior_lows))
    breakout_level = prior_max_high

    is_breakout = current_close > prior_max_high * (1.0 + buffer_pct)
    features["breakout_flag"] = 1.0 if is_breakout else 0.0

    # 3. Pre-breakout base quality (Bollinger bandwidth of the prior base bars)
    # Tighter base = narrower bandwidth = higher base quality
    base_closes = close[-breakout_lookback - 1 : -1]
    base_mean = np.mean(base_closes)
    base_std = np.std(base_closes)
    if base_mean > 0:
        bollinger_bandwidth = (4.0 * base_std) / base_mean
        # Quality score 0-100: narrower bandwidth gives higher score
        features["pre_breakout_base_quality"] = float(np.clip(1.0 / (1.0 + bollinger_bandwidth * 20.0), 0.0, 1.0))
    else:
        features["pre_breakout_base_quality"] = 0.5

    # 4. Retest & Hold Flag
    # Check if a breakout happened within last 3-8 bars, price subsequently dipped near breakout level,
    # and current close held above breakout level with pullback volume < breakout candle volume
    retest_hold = 0.0
    if n >= 10:
        # Search for breakout bar in the recent window [t-8 to t-2]
        for offset in range(3, min(9, n - breakout_lookback)):
            b_bar_idx = n - offset
            prev_level = np.max(high[b_bar_idx - breakout_lookback : b_bar_idx])
            b_close = close[b_bar_idx]
            b_vol = vol[b_bar_idx]

            if b_close > prev_level * (1.0 + buffer_pct):
                # Breakout occurred at b_bar_idx
                # Check subsequent bars between breakout and now
                subsequent_lows = low[b_bar_idx + 1 : -1] if offset > 1 else np.array([])
                subsequent_vols = vol[b_bar_idx + 1 : -1] if offset > 1 else np.array([])

                if len(subsequent_lows) > 0:
                    min_pullback_low = np.min(subsequent_lows)
                    # Dipped within 1.5% of breakout level without heavily violating it
                    dipped_to_retest = min_pullback_low <= prev_level * 1.015
                    held_above = current_close >= prev_level
                    pullback_vol_lower = np.mean(subsequent_vols) < b_vol

                    if dipped_to_retest and held_above and pullback_vol_lower:
                        retest_hold = 1.0
                        break
    features["retest_hold_flag"] = retest_hold

    # 5. Swing Structure (Higher Highs & Higher Lows)
    # Check 3-bar local pivots over the last 15 bars
    if n >= 15:
        pivots_high = []
        pivots_low = []
        for i in range(n - 14, n - 1):
            if high[i] > high[i - 1] and high[i] > high[i + 1]:
                pivots_high.append(high[i])
            if low[i] < low[i - 1] and low[i] < low[i + 1]:
                pivots_low.append(low[i])

        # Check if consecutive highs and lows are ascending
        is_hh = len(pivots_high) >= 2 and all(x < y for x, y in zip(pivots_high[:-1], pivots_high[1:]))
        is_hl = len(pivots_low) >= 2 and all(x < y for x, y in zip(pivots_low[:-1], pivots_low[1:]))

        if is_hh and is_hl:
            features["swing_structure_hh_hl"] = 2.0  # Strong uptrend structure
        elif is_hh or is_hl:
            features["swing_structure_hh_hl"] = 1.0  # Moderate structure
        else:
            features["swing_structure_hh_hl"] = 0.0

    # 6. Extension ATR: (current_price - breakout_level) / ATR
    if atr > 0:
        features["extension_atr"] = float((current_close - breakout_level) / atr)
    else:
        features["extension_atr"] = 0.0

    return features
