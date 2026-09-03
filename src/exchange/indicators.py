from typing import List, Optional, Tuple
import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average (EMA)."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculate Volume Weighted Average Price (VWAP) over the dataframe period."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vp = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_vp / cum_vol.replace(0, np.nan)


def calculate_bollinger_bands(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands (middle, upper, lower, bandwidth_pct)."""
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + (std * std_dev)
    lower = mid - (std * std_dev)
    bandwidth = (upper - lower) / mid.replace(0, np.nan) * 100.0
    return mid, upper, lower, bandwidth


def calculate_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD line, Signal line, and Histogram."""
    ema_fast = calculate_ema(close, fast)
    ema_slow = calculate_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range (ATR)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


def find_swing_lows(df: pd.DataFrame, window: int = 4) -> List[Tuple[int, float]]:
    """Find swing low pivots (index, low_price) where low is the lowest in +/- window candles."""
    lows = df["low"].values
    swing_lows = []
    n = len(lows)

    for i in range(window, n - window):
        current_low = lows[i]
        left_min = np.min(lows[i - window : i])
        right_min = np.min(lows[i + 1 : i + window + 1])
        if current_low <= left_min and current_low <= right_min:
            swing_lows.append((i, float(current_low)))
    return swing_lows


def find_swing_highs(df: pd.DataFrame, window: int = 4) -> List[Tuple[int, float]]:
    """Find swing high pivots (index, high_price) where high is the highest in +/- window candles."""
    highs = df["high"].values
    swing_highs = []
    n = len(highs)

    for i in range(window, n - window):
        current_high = highs[i]
        left_max = np.max(highs[i - window : i])
        right_max = np.max(highs[i + 1 : i + window + 1])
        if current_high >= left_max and current_high >= right_max:
            swing_highs.append((i, float(current_high)))
    return swing_highs


def calculate_supertrend(
    df: pd.DataFrame, period: int = 10, multiplier: float = 3.0
) -> Tuple[pd.Series, pd.Series]:
    """Calculate Supertrend indicator (supertrend_line, direction: 1 for Bullish, -1 for Bearish)."""
    hl2 = (df["high"] + df["low"]) / 2.0
    atr = calculate_atr(df, period)

    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    n = len(df)
    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    supertrend = np.zeros(n)
    direction = np.zeros(n)  # 1 = bullish (green), -1 = bearish (red)

    close = df["close"].values
    b_upper = basic_upper.values
    b_lower = basic_lower.values

    for i in range(1, n):
        # Final Upper Band
        if b_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = b_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Final Lower Band
        if b_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = b_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # Supertrend direction
        if direction[i - 1] == 1:
            if close[i] < final_lower[i]:
                direction[i] = -1
                supertrend[i] = final_upper[i]
            else:
                direction[i] = 1
                supertrend[i] = final_lower[i]
        else:
            if close[i] > final_upper[i]:
                direction[i] = 1
                supertrend[i] = final_lower[i]
            else:
                direction[i] = -1
                supertrend[i] = final_upper[i]

    st_series = pd.Series(supertrend, index=df.index)
    dir_series = pd.Series(direction, index=df.index)
    return st_series, dir_series


def calculate_stoch_rsi(
    close: pd.Series,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> Tuple[pd.Series, pd.Series]:
    """Calculate Stochastic RSI (%K, %D)."""
    rsi = calculate_rsi(close, rsi_period)
    rsi_low = rsi.rolling(window=stoch_period).min()
    rsi_high = rsi.rolling(window=stoch_period).max()

    stoch_rsi = ((rsi - rsi_low) / (rsi_high - rsi_low).replace(0, np.nan)) * 100.0
    stoch_rsi = stoch_rsi.fillna(50.0)

    k = stoch_rsi.rolling(window=k_period).mean().fillna(50.0)
    d = k.rolling(window=d_period).mean().fillna(50.0)
    return k, d
