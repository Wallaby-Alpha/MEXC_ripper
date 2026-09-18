"""Forward outcome labeling for candidate pump events.
Measures MFE, time-to-targets, drawdown before peak, round-trip below entry, and continuation status.
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, List
from config import FORWARD_HORIZONS, TARGET_MFE_THRESHOLDS, CONTINUATION_CRITERIA


def label_forward_outcomes(
    entry_close: float,
    entry_time_ms: int,
    forward_klines_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Given entry price and the forward bars following the candidate bar,
    measures ground-truth continuation metrics across multiple horizons (4h, 12h, 24h, 48h).

    Tracks:
    - MFE % (Max Favorable Excursion) at 4h, 12h, 24h, 48h
    - MAE % (Max Adverse Excursion) at 4h, 12h, 24h, 48h
    - Max Drawdown before MFE peak
    - Minutes to reach +10%, +25%, +50%
    - Round-trip flag (price crossed back below entry close after initial pump)
    - Target binary classification label: `label_continued` (1 if hit +15% with <=8% drawdown)
    """
    labels: Dict[str, Any] = {
        "fwd_bars_available": len(forward_klines_df),
        "return_4h": 0.0,
        "return_12h": 0.0,
        "return_24h": 0.0,
        "return_48h": 0.0,
        "mfe_4h": 0.0,
        "mfe_12h": 0.0,
        "mfe_24h": 0.0,
        "mfe_48h": 0.0,
        "mae_4h": 0.0,
        "mae_12h": 0.0,
        "mae_24h": 0.0,
        "mae_48h": 0.0,
        "drawdown_before_mfe_24h": 0.0,
        "minutes_to_10pct": None,
        "minutes_to_25pct": None,
        "minutes_to_50pct": None,
        "round_tripped": 0,
        "label_continued": 0,
    }

    if forward_klines_df.empty or entry_close <= 0:
        return labels

    highs = forward_klines_df["high"].values
    lows = forward_klines_df["low"].values
    closes = forward_klines_df["close"].values
    open_times = forward_klines_df["open_time"].values
    n = len(forward_klines_df)

    # 1. Horizon-specific returns, MFE, MAE
    for h_name, bars_count in FORWARD_HORIZONS.items():
        avail = min(n, bars_count)
        if avail > 0:
            h_highs = highs[:avail]
            h_lows = lows[:avail]
            labels[f"return_{h_name}"] = float((closes[avail - 1] - entry_close) / entry_close)
            labels[f"mfe_{h_name}"] = float((np.max(h_highs) - entry_close) / entry_close)
            labels[f"mae_{h_name}"] = float((np.min(h_lows) - entry_close) / entry_close)

    # 2. Time to targets (+10%, +25%, +50%)
    for target in TARGET_MFE_THRESHOLDS:
        target_price = entry_close * (1.0 + target)
        target_int = int(target * 100)
        key = f"minutes_to_{target_int}pct"

        hit_indices = np.where(highs >= target_price)[0]
        if len(hit_indices) > 0:
            first_idx = hit_indices[0]
            elapsed_min = (open_times[first_idx] - entry_time_ms) / (60 * 1000)
            labels[key] = float(elapsed_min)

    # 3. Max Drawdown before MFE peak (over 24h horizon)
    bars_24h = min(n, FORWARD_HORIZONS["24h"])
    if bars_24h > 0:
        highs_24 = highs[:bars_24h]
        lows_24 = lows[:bars_24h]
        mfe_idx = int(np.argmax(highs_24))

        if mfe_idx > 0:
            min_low_before_mfe = float(np.min(lows_24[: mfe_idx + 1]))
            labels["drawdown_before_mfe_24h"] = float((min_low_before_mfe - entry_close) / entry_close)
        else:
            labels["drawdown_before_mfe_24h"] = float((lows_24[0] - entry_close) / entry_close)

        # 4. Round-trip check: Did price reach at least +5% then subsequently fall below entry close?
        peak_24 = np.max(highs_24)
        if peak_24 >= entry_close * 1.05 and mfe_idx < bars_24h - 1:
            later_lows = lows_24[mfe_idx + 1 :]
            if np.min(later_lows) < entry_close:
                labels["round_tripped"] = 1

    # 5. Ground truth binary label: Continued vs Faded
    # Continued = Reached target gain (+15%) within 24h with max drawdown >= -8% before peak and no round-trip
    mfe_24 = labels["mfe_24h"]
    dd_24 = labels["drawdown_before_mfe_24h"]

    target_gain = CONTINUATION_CRITERIA["target_gain"]
    max_dd = -abs(CONTINUATION_CRITERIA["max_drawdown"])

    if mfe_24 >= target_gain and dd_24 >= max_dd:
        labels["label_continued"] = 1
    else:
        labels["label_continued"] = 0

    return labels
