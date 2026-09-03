import numpy as np
import pandas as pd
import pytest
from src.exchange.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_stoch_rsi,
    calculate_supertrend,
    calculate_vwap,
    find_swing_highs,
    find_swing_lows,
)


@pytest.fixture
def sample_df():
    """Generate 100 periods of synthetic OHLCV data."""
    np.random.seed(42)
    n = 100
    prices = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    highs = prices + np.random.rand(n) * 0.8
    lows = prices - np.random.rand(n) * 0.8
    opens = prices + (np.random.rand(n) - 0.5) * 0.4
    closes = prices + (np.random.rand(n) - 0.5) * 0.4
    volumes = np.random.randint(1000, 50000, size=n)

    times = [1700000000000 + i * 300000 for i in range(n)]

    return pd.DataFrame(
        {
            "open_time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "close_time": [t + 299999 for t in times],
            "quote_volume": volumes * closes,
        }
    )


def test_calculate_ema(sample_df):
    ema_20 = calculate_ema(sample_df["close"], 20)
    assert len(ema_20) == len(sample_df)
    assert not ema_20.isna().any()
    assert isinstance(ema_20.iloc[-1], float)


def test_calculate_rsi(sample_df):
    rsi = calculate_rsi(sample_df["close"], 14)
    assert len(rsi) == len(sample_df)
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_calculate_vwap(sample_df):
    vwap = calculate_vwap(sample_df)
    assert len(vwap) == len(sample_df)
    assert not vwap.isna().any()
    assert vwap.iloc[-1] > 0


def test_calculate_bollinger_bands(sample_df):
    mid, upper, lower, bandwidth = calculate_bollinger_bands(sample_df["close"], 20, 2.0)
    assert len(mid) == len(sample_df)
    assert (upper.dropna() >= mid.dropna()).all()
    assert (mid.dropna() >= lower.dropna()).all()
    assert (bandwidth.dropna() >= 0).all()


def test_calculate_macd(sample_df):
    macd, signal, hist = calculate_macd(sample_df["close"], 12, 26, 9)
    assert len(macd) == len(sample_df)
    assert len(signal) == len(sample_df)
    assert len(hist) == len(sample_df)
    # Check that histogram equals macd - signal
    np.testing.assert_allclose(hist.dropna(), (macd - signal).dropna(), atol=1e-5)


def test_calculate_atr(sample_df):
    atr = calculate_atr(sample_df, 14)
    assert len(atr) == len(sample_df)
    assert (atr >= 0).all()


def test_calculate_supertrend(sample_df):
    st, direction = calculate_supertrend(sample_df, 10, 3.0)
    assert len(st) == len(sample_df)
    assert len(direction) == len(sample_df)
    assert set(direction.unique()).issubset({1.0, -1.0, 0.0})


def test_calculate_stoch_rsi(sample_df):
    k, d = calculate_stoch_rsi(sample_df["close"], 14, 14, 3, 3)
    assert len(k) == len(sample_df)
    assert len(d) == len(sample_df)
    assert (k.dropna() >= 0).all() and (k.dropna() <= 100).all()


def test_swing_pivots():
    df = pd.DataFrame(
        {
            "high": [10, 11, 12, 15, 12, 11, 10, 13, 10],
            "low": [8, 9, 7, 5, 7, 8, 9, 8, 7],
        }
    )
    swing_highs = find_swing_highs(df, window=2)
    swing_lows = find_swing_lows(df, window=2)
    assert len(swing_highs) >= 1
    assert len(swing_lows) >= 1
    assert swing_highs[0][1] == 15.0
    assert swing_lows[0][1] == 5.0
