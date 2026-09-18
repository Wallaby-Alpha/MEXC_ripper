"""Test proving 100% zero-lookahead bias across the entire feature pipeline."""
import numpy as np
import pandas as pd
import pytest
from src.features.feature_pipeline import extract_features_point_in_time


def generate_synthetic_candles(n_bars: int = 100, base_time: int = 1788220800000) -> pd.DataFrame:
    """Generates synthetic 5m candles."""
    records = []
    curr_p = 10.0
    for i in range(n_bars):
        open_t = base_time + i * 300_000
        close_t = open_t + 299_999
        ret = np.sin(i / 5.0) * 0.02
        high = curr_p * (1.0 + abs(ret) + 0.01)
        low = curr_p * (1.0 - abs(ret) - 0.01)
        close = curr_p * (1.0 + ret)
        vol = 1000.0 + (i % 7) * 200.0
        q_vol = vol * close
        records.append({
            "open_time": open_t,
            "open": curr_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "close_time": close_t,
            "quote_volume": q_vol,
        })
        curr_p = close
    return pd.DataFrame(records)


def test_strict_zero_lookahead_bias():
    """Mutating future data must NOT alter any feature calculated at bar T."""
    full_df = generate_synthetic_candles(100)
    eval_idx = 45
    eval_time = int(full_df["open_time"].iloc[eval_idx])

    # 1. Compute features with slice strictly ending at eval_time
    history_only_df = full_df.iloc[: eval_idx + 1].copy()
    feats_baseline = extract_features_point_in_time(
        symbol="TESTUSDT",
        timestamp_ms=eval_time,
        klines_df=history_only_df,
    )

    # 2. Compute features passing the entire 100-bar dataframe (pipeline must slice internally)
    feats_with_future = extract_features_point_in_time(
        symbol="TESTUSDT",
        timestamp_ms=eval_time,
        klines_df=full_df.copy(),
    )

    # 3. Aggressively corrupt future bars (indices 46 to 99): 100x price spike and volume explosion
    corrupted_df = full_df.copy()
    corrupted_df.loc[eval_idx + 1 :, "close"] *= 100.0
    corrupted_df.loc[eval_idx + 1 :, "high"] *= 150.0
    corrupted_df.loc[eval_idx + 1 :, "low"] *= 50.0
    corrupted_df.loc[eval_idx + 1 :, "volume"] *= 500.0
    corrupted_df.loc[eval_idx + 1 :, "quote_volume"] *= 50000.0

    feats_with_corrupted_future = extract_features_point_in_time(
        symbol="TESTUSDT",
        timestamp_ms=eval_time,
        klines_df=corrupted_df,
    )

    # Assert baseline == with_future == with_corrupted_future
    for k in feats_baseline.keys():
        val_base = feats_baseline[k]
        val_fut = feats_with_future[k]
        val_corrupt = feats_with_corrupted_future[k]

        if isinstance(val_base, (int, float)):
            assert np.isclose(val_base, val_fut, equal_nan=True), f"Lookahead detected on '{k}': baseline={val_base}, with_future={val_fut}"
            assert np.isclose(val_base, val_corrupt, equal_nan=True), f"Lookahead corruption detected on '{k}': baseline={val_base}, corrupt={val_corrupt}"
        else:
            assert val_base == val_fut == val_corrupt, f"String/identity mismatch on '{k}'"
