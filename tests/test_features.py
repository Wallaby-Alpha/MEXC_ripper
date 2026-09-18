"""Unit tests for individual feature calculation modules."""
import numpy as np
import pandas as pd
import pytest

from src.features.volume import compute_volume_features
from src.features.price_structure import compute_price_structure_features
from src.features.momentum import compute_momentum_features, compute_rsi
from src.features.relative_strength import compute_relative_strength_features
from tests.test_lookahead_bias import generate_synthetic_candles


def test_volume_and_cvd_features():
    df = generate_synthetic_candles(40)
    # Inject a 3x volume spike on the last candle
    df.loc[df.index[-1], "volume"] = df["volume"].iloc[-21:-1].mean() * 3.5

    feats = compute_volume_features(df)
    assert feats["rvol_20"] > 3.0
    assert feats["volume_persistence"] >= 1.0

    # Test with trade-level CVD
    trades = pd.DataFrame([
        {"trade_time": 1000, "price": 10.0, "quantity": 500.0, "is_buyer_maker": 0},  # Taker buy +500
        {"trade_time": 1001, "price": 10.1, "quantity": 200.0, "is_buyer_maker": 1},  # Taker sell -200
    ])
    feats_cvd = compute_volume_features(df, trades_df=trades)
    assert np.isclose(feats_cvd["cvd_rolling"], 300.0)


def test_price_structure_breakout():
    df = generate_synthetic_candles(50)
    prior_high = df["high"].iloc[-21:-1].max()

    # Make last candle breakout well above prior high
    df.loc[df.index[-1], "close"] = prior_high * 1.05
    df.loc[df.index[-1], "high"] = prior_high * 1.06

    feats = compute_price_structure_features(df)
    assert feats["breakout_flag"] == 1.0
    assert feats["extension_atr"] > 0.0


def test_momentum_rsi_and_macd():
    # Accelerating momentum price sequence
    prices = 10.0 * (1.02 ** np.arange(50))
    rsi = compute_rsi(prices, period=14)
    assert rsi[-1] > 70.0  # Strong uptrend leads to high RSI

    df = generate_synthetic_candles(50)
    df["close"] = prices
    df["high"] = prices * 1.01
    df["low"] = prices * 0.99
    mom_feats = compute_momentum_features(df)
    assert mom_feats["rsi_14"] > 70.0
    assert mom_feats["macd_histogram"] > 0.0
    assert mom_feats["macd_histogram_slope"] >= 0.0


def test_relative_strength_vs_benchmarks():
    coin_df = generate_synthetic_candles(50)
    btc_df = generate_synthetic_candles(50)

    # Coin pumps 10% in last 12 bars, BTC is flat
    coin_df.loc[coin_df.index[-1], "close"] = coin_df["close"].iloc[-13] * 1.10
    btc_df.loc[btc_df.index[-1], "close"] = btc_df["close"].iloc[-13] * 1.00

    rs_feats = compute_relative_strength_features(coin_df, btc_df=btc_df)
    assert np.isclose(rs_feats["rs_vs_btc_1h"], 0.10, atol=0.01)
