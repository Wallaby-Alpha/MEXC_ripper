"""Momentum features (RSI, RSI pullback depth, MACD histogram slope)."""
import numpy as np
import pandas as pd
from typing import Dict, Any


def compute_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Standard Wilder's RSI calculation."""
    if len(prices) < period + 1:
        return np.full(len(prices), 50.0)

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.zeros(len(prices))
    avg_loss = np.zeros(len(prices))

    # Initial SMA
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    # Exponential smoothing
    for i in range(period + 1, len(prices)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

    # If avg_loss is 0, RSI is 100 (no losses occurred)
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
        rsi = np.where(avg_loss == 0, 100.0, 100.0 - (100.0 / (1.0 + rs)))
    rsi[:period] = 50.0
    return rsi


def compute_macd(prices: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """Computes MACD line, signal line, and histogram."""
    if len(prices) < slow + signal:
        zeros = np.zeros(len(prices))
        return zeros, zeros, zeros

    s = pd.Series(prices)
    ema_fast = s.ewm(span=fast, adjust=False).mean().values
    ema_slow = s.ewm(span=slow, adjust=False).mean().values
    macd_line = ema_fast - ema_slow
    signal_line = pd.Series(macd_line).ewm(span=signal, adjust=False).mean().values
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_momentum_features(df: pd.DataFrame) -> Dict[str, float]:
    """Computes momentum features strictly using bars <= current bar."""
    features: Dict[str, float] = {
        "rsi_14": 50.0,
        "rsi_pullback_depth": 50.0,
        "macd_histogram": 0.0,
        "macd_histogram_slope": 0.0,
    }

    if df.empty or len(df) < 15:
        return features

    close = df["close"].values
    n = len(close)

    # 1. RSI 14
    rsi_series = compute_rsi(close, period=14)
    features["rsi_14"] = float(rsi_series[-1])

    # 2. RSI Pullback Depth
    # Find local price lows in the last 20 bars and find the minimum RSI value at those pullback points
    lookback = min(20, n - 2)
    low_prices = df["low"].values
    pullback_rsis = []

    for i in range(n - lookback, n - 1):
        # Local price trough (lower than adjacent bars)
        if low_prices[i] <= low_prices[i - 1] and low_prices[i] <= low_prices[i + 1]:
            pullback_rsis.append(rsi_series[i])

    if pullback_rsis:
        features["rsi_pullback_depth"] = float(np.min(pullback_rsis))
    else:
        # If trend was continuous without troughs, use min RSI over window
        features["rsi_pullback_depth"] = float(np.min(rsi_series[-lookback:]))

    # 3. MACD Histogram and 3-bar slope
    _, _, histogram = compute_macd(close)
    features["macd_histogram"] = float(histogram[-1])

    if len(histogram) >= 3:
        # Slope over last 3 bars: (hist[t] - hist[t-2]) / 2
        features["macd_histogram_slope"] = float((histogram[-1] - histogram[-3]) / 2.0)
    else:
        features["macd_histogram_slope"] = 0.0

    return features
