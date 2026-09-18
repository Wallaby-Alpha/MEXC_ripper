"""Liquidity and turnover features."""
import numpy as np
import pandas as pd
from typing import Dict, Any


def compute_liquidity_features(df: pd.DataFrame, bars_in_24h: int = 288) -> Dict[str, float]:
    """Computes liquidity and quote turnover features strictly using bars <= current bar."""
    features: Dict[str, float] = {
        "turnover_24h": 0.0,
        "quote_vol_spike_ratio": 1.0,
    }

    if df.empty:
        return features

    # Check if quote_volume is present, else approximate with volume * close
    if "quote_volume" in df.columns:
        qv = df["quote_volume"].values
    else:
        qv = df["volume"].values * df["close"].values

    n = len(qv)
    current_qv = qv[-1]

    # Rolling 24h turnover
    window_24h = min(n, bars_in_24h)
    turnover_24h = float(np.sum(qv[-window_24h:]))
    features["turnover_24h"] = turnover_24h

    # Spike ratio vs average quote volume per bar
    if window_24h > 1:
        avg_qv = np.mean(qv[-window_24h - 1 : -1]) if n > window_24h else np.mean(qv[:-1])
        features["quote_vol_spike_ratio"] = float(current_qv / avg_qv) if avg_qv > 0 else 1.0
    else:
        features["quote_vol_spike_ratio"] = 1.0

    return features
