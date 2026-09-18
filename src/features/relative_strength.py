"""Relative strength features vs BTC and ETH over multiple lookbacks."""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional


def compute_relative_strength_features(
    df: pd.DataFrame,
    btc_df: Optional[pd.DataFrame] = None,
    eth_df: Optional[pd.DataFrame] = None,
) -> Dict[str, float]:
    """Computes relative strength against BTC and ETH:
    coin return minus benchmark return over 1h (12 bars), 4h (48 bars), and 24h (288 bars).
    Strictly using aligned timestamps <= current bar.
    """
    features: Dict[str, float] = {
        "return_1h": 0.0,
        "return_4h": 0.0,
        "return_24h": 0.0,
        "rs_vs_btc_1h": 0.0,
        "rs_vs_btc_4h": 0.0,
        "rs_vs_btc_24h": 0.0,
        "rs_vs_eth_1h": 0.0,
        "rs_vs_eth_4h": 0.0,
        "rs_vs_eth_24h": 0.0,
    }

    if df.empty or len(df) < 5:
        return features

    close = df["close"].values
    n = len(close)
    current_close = close[-1]

    # Calculate returns for candidate
    def calc_ret(bars: int) -> float:
        if n > bars and close[-bars - 1] > 0:
            return float((current_close - close[-bars - 1]) / close[-bars - 1])
        elif n > 1 and close[0] > 0:
            return float((current_close - close[0]) / close[0])
        return 0.0

    ret_1h = calc_ret(12)
    ret_4h = calc_ret(48)
    ret_24h = calc_ret(288)

    features["return_1h"] = ret_1h
    features["return_4h"] = ret_4h
    features["return_24h"] = ret_24h

    # Helper for benchmark relative return
    def calc_rs(bench_df: Optional[pd.DataFrame], bars: int, coin_ret: float) -> float:
        if bench_df is None or bench_df.empty or len(bench_df) < 2:
            return coin_ret
        b_close = bench_df["close"].values
        b_n = len(b_close)
        b_curr = b_close[-1]
        if b_n > bars and b_close[-bars - 1] > 0:
            bench_ret = float((b_curr - b_close[-bars - 1]) / b_close[-bars - 1])
        elif b_n > 1 and b_close[0] > 0:
            bench_ret = float((b_curr - b_close[0]) / b_close[0])
        else:
            bench_ret = 0.0
        return float(coin_ret - bench_ret)

    features["rs_vs_btc_1h"] = calc_rs(btc_df, 12, ret_1h)
    features["rs_vs_btc_4h"] = calc_rs(btc_df, 48, ret_4h)
    features["rs_vs_btc_24h"] = calc_rs(btc_df, 288, ret_24h)

    features["rs_vs_eth_1h"] = calc_rs(eth_df, 12, ret_1h)
    features["rs_vs_eth_4h"] = calc_rs(eth_df, 48, ret_4h)
    features["rs_vs_eth_24h"] = calc_rs(eth_df, 288, ret_24h)

    return features
