"""Volume and order flow features (RVOL, volume persistence, CVD, CVD price divergence)."""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional


def compute_volume_features(
    df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    lookback_short: int = 20,
    lookback_long: int = 60,
) -> Dict[str, float]:
    """Computes volume and CVD features strictly using historical data <= current bar.
    df columns expected: ['open', 'high', 'low', 'close', 'volume', 'quote_volume']
    """
    features: Dict[str, float] = {
        "rvol_20": 1.0,
        "rvol_60": 1.0,
        "volume_persistence": 0.0,
        "cvd_rolling": 0.0,
        "cvd_price_divergence": 0.0,
    }

    if df.empty or len(df) < 5:
        return features

    vol = df["volume"].values
    close = df["close"].values
    n = len(vol)

    current_vol = vol[-1]

    # 1. RVOL_n: current bar volume / rolling average volume (excluding current bar)
    if n > lookback_short:
        base_short = np.mean(vol[-lookback_short - 1 : -1])
        features["rvol_20"] = float(current_vol / base_short) if base_short > 0 else 1.0
    else:
        base_short = np.mean(vol[:-1]) if n > 1 else current_vol
        features["rvol_20"] = float(current_vol / base_short) if base_short > 0 else 1.0

    if n > lookback_long:
        base_long = np.mean(vol[-lookback_long - 1 : -1])
        features["rvol_60"] = float(current_vol / base_long) if base_long > 0 else 1.0
    else:
        features["rvol_60"] = features["rvol_20"]

    # 2. Volume persistence: number of consecutive bars where volume >= 1.5x baseline
    baseline = base_short if base_short > 0 else 1.0
    persistence_count = 0
    # Walk backward from current bar
    for v in reversed(vol):
        if v >= 1.5 * baseline:
            persistence_count += 1
        else:
            break
    features["volume_persistence"] = float(persistence_count)

    # 3. CVD (Cumulative Volume Delta) from aggTrades
    # If trades_df is available, calculate exact delta
    if trades_df is not None and not trades_df.empty and "is_buyer_maker" in trades_df.columns:
        # is_buyer_maker == 0 (False) means buyer was taker -> taker buy (+qty)
        # is_buyer_maker == 1 (True) means seller was taker -> taker sell (-qty)
        qty = trades_df["quantity"].values
        is_bm = trades_df["is_buyer_maker"].values
        delta = np.where(is_bm == 0, qty, -qty)
        features["cvd_rolling"] = float(np.sum(delta))

        # CVD-Price divergence check
        # Compare CVD direction with price change over recent trades
        if len(trades_df) >= 10:
            price_start = trades_df["price"].iloc[0]
            price_end = trades_df["price"].iloc[-1]
            price_change = price_end - price_start

            # If price rose but CVD was negative or flat -> Bearish divergence (+1.0 divergence flag)
            # If price rose and CVD rose -> Strong agreement (0.0 divergence)
            if price_change > 0 and features["cvd_rolling"] < 0:
                features["cvd_price_divergence"] = 1.0  # Fragile move
            elif price_change < 0 and features["cvd_rolling"] > 0:
                features["cvd_price_divergence"] = -1.0  # Bullish divergence
            else:
                features["cvd_price_divergence"] = 0.0
    else:
        # Synthetic CVD proxy from bar metrics when high-frequency aggTrades are cached at candle level
        # Uses standard candle delta estimation: Volume * (2 * (Close - Low) / (High - Low) - 1)
        ranges = df["high"].values[-lookback_short:] - df["low"].values[-lookback_short:]
        valid_mask = ranges > 0
        closes = df["close"].values[-lookback_short:]
        lows = df["low"].values[-lookback_short:]
        vols = vol[-lookback_short:]

        synth_deltas = np.zeros_like(vols)
        synth_deltas[valid_mask] = vols[valid_mask] * (
            2.0 * (closes[valid_mask] - lows[valid_mask]) / ranges[valid_mask] - 1.0
        )
        features["cvd_rolling"] = float(np.sum(synth_deltas))

        # Slope alignment
        price_slope = close[-1] - close[max(0, n - lookback_short)]
        if price_slope > 0 and features["cvd_rolling"] < 0:
            features["cvd_price_divergence"] = 1.0
        elif price_slope < 0 and features["cvd_rolling"] > 0:
            features["cvd_price_divergence"] = -1.0
        else:
            features["cvd_price_divergence"] = 0.0

    return features
