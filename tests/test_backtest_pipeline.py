"""Integration tests for the backtest labeling, bucketing, and ML analysis pipeline."""
import numpy as np
import pandas as pd
import pytest

from src.backtest.labeler import label_forward_outcomes
from src.backtest.analysis import bucket_feature_analysis, fit_feature_importance_model
from tests.test_lookahead_bias import generate_synthetic_candles


def test_forward_outcome_labeling():
    # Generate 100 forward bars
    forward_df = generate_synthetic_candles(100)
    entry_close = 10.0
    entry_time = int(forward_df["open_time"].iloc[0])

    # Case 1: Massive pump to +30% with small drawdown
    forward_df["high"] = np.linspace(10.0, 13.0, 100)
    forward_df["low"] = np.linspace(9.6, 12.5, 100)
    forward_df["close"] = np.linspace(9.8, 12.9, 100)

    labels = label_forward_outcomes(entry_close, entry_time, forward_df)
    assert labels["mfe_24h"] >= 0.25
    assert labels["label_continued"] == 1
    assert labels["minutes_to_10pct"] is not None
    assert labels["minutes_to_25pct"] is not None

    # Case 2: Fade / Round-trip
    fade_df = generate_synthetic_candles(100)
    # Pump to 10.6 (+6%) then crash to 8.0 (-20%)
    highs = np.concatenate([np.linspace(10.0, 10.6, 10), np.linspace(10.5, 8.2, 90)])
    lows = np.concatenate([np.linspace(9.9, 10.2, 10), np.linspace(10.1, 8.0, 90)])
    closes = np.concatenate([np.linspace(10.0, 10.5, 10), np.linspace(10.3, 8.1, 90)])
    fade_df["high"] = highs
    fade_df["low"] = lows
    fade_df["close"] = closes

    labels_fade = label_forward_outcomes(entry_close, entry_time, fade_df)
    assert labels_fade["label_continued"] == 0
    assert labels_fade["round_tripped"] == 1


def test_bucketing_and_ml_analysis():
    # Create synthetic candidates dataset
    n = 50
    data = []
    for i in range(n):
        rvol = np.random.uniform(1.5, 6.0)
        breakout = 1.0 if rvol > 3.5 else 0.0
        # Positive continuation correlation
        label = 1 if (breakout == 1.0 and np.random.rand() > 0.3) else 0
        ret_24h = 0.20 if label == 1 else -0.05
        data.append({
            "rvol_20": rvol,
            "rvol_60": rvol * 0.9,
            "breakout_flag": breakout,
            "retest_hold_flag": 1.0 if (breakout == 1.0 and np.random.rand() > 0.5) else 0.0,
            "return_24h": ret_24h,
            "mfe_24h": max(ret_24h + 0.05, 0.02),
            "mae_24h": -0.04 if label == 1 else -0.15,
            "label_continued": label,
        })
    df = pd.DataFrame(data)

    # Test bucketing
    buckets = bucket_feature_analysis(df)
    assert "breakout_flag" in buckets
    assert "rvol_20" in buckets

    # Test ML fit
    model_res = fit_feature_importance_model(df)
    assert model_res["status"] in ("success", "insufficient_data")
    if model_res["status"] == "success":
        assert "logistic_regression_coefficients" in model_res
        assert "decision_tree_importances" in model_res
