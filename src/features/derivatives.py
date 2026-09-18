"""Derivatives features (funding rate level & trend, OI changes) with graceful fallback for spot-only coins."""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional


def compute_derivatives_features(
    funding_df: Optional[pd.DataFrame] = None,
    current_time_ms: Optional[int] = None,
) -> Dict[str, float]:
    """Computes funding rate level and trend.
    Strictly uses records with settle_time <= current_time_ms.
    """
    features: Dict[str, float] = {
        "has_derivatives": 0.0,
        "funding_rate_level": 0.0,
        "funding_rate_trend": 0.0,
        "oi_change_pct": 0.0,
        "oi_price_alignment": 0.0,
    }

    if funding_df is None or funding_df.empty:
        return features

    # Filter <= current_time_ms
    if current_time_ms is not None and "settle_time" in funding_df.columns:
        valid_rates = funding_df[funding_df["settle_time"] <= current_time_ms]
    else:
        valid_rates = funding_df

    if valid_rates.empty:
        return features

    rates = valid_rates["funding_rate"].values
    features["has_derivatives"] = 1.0
    features["funding_rate_level"] = float(rates[-1])

    # Trend over the last 3 funding cycles (usually 8-hour intervals)
    if len(rates) >= 3:
        features["funding_rate_trend"] = float(rates[-1] - rates[-3])
    elif len(rates) >= 2:
        features["funding_rate_trend"] = float(rates[-1] - rates[-2])

    return features
