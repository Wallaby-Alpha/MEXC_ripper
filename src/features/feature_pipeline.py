"""Unified feature pipeline that merges volume, price structure, momentum, relative strength,
and liquidity features into a single pure function with guaranteed zero lookahead bias.
"""
from typing import Dict, Any, Optional
import pandas as pd

from src.features.volume import compute_volume_features
from src.features.price_structure import compute_price_structure_features
from src.features.momentum import compute_momentum_features
from src.features.relative_strength import compute_relative_strength_features
from src.features.liquidity import compute_liquidity_features
from src.features.derivatives import compute_derivatives_features


def extract_features_point_in_time(
    symbol: str,
    timestamp_ms: int,
    klines_df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    btc_klines_df: Optional[pd.DataFrame] = None,
    eth_klines_df: Optional[pd.DataFrame] = None,
    funding_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Pure function: Computes all features for (symbol, timestamp_ms) strictly using data <= timestamp_ms.
    Guarantees no future data is ever visible.

    Returns a flat dictionary containing all computed features.
    """
    # 1. Strict point-in-time slicing
    sub_klines = (
        klines_df[klines_df["open_time"] <= timestamp_ms].copy()
        if "open_time" in klines_df.columns
        else klines_df.copy()
    )

    if sub_klines.empty:
        raise ValueError(f"No kline data available for {symbol} at or before timestamp {timestamp_ms}")

    sub_trades = None
    if trades_df is not None and not trades_df.empty and "trade_time" in trades_df.columns:
        sub_trades = trades_df[trades_df["trade_time"] <= timestamp_ms].copy()

    sub_btc = None
    if btc_klines_df is not None and not btc_klines_df.empty and "open_time" in btc_klines_df.columns:
        sub_btc = btc_klines_df[btc_klines_df["open_time"] <= timestamp_ms].copy()

    sub_eth = None
    if eth_klines_df is not None and not eth_klines_df.empty and "open_time" in eth_klines_df.columns:
        sub_eth = eth_klines_df[eth_klines_df["open_time"] <= timestamp_ms].copy()

    # Base identifier info
    current_close = float(sub_klines["close"].iloc[-1])
    current_vol = float(sub_klines["volume"].iloc[-1])
    current_quote_vol = (
        float(sub_klines["quote_volume"].iloc[-1])
        if "quote_volume" in sub_klines.columns
        else current_close * current_vol
    )

    features: Dict[str, Any] = {
        "symbol": symbol,
        "timestamp_ms": timestamp_ms,
        "close": current_close,
        "volume": current_vol,
        "quote_volume": current_quote_vol,
    }

    # 2. Extract feature sets
    vol_feats = compute_volume_features(sub_klines, trades_df=sub_trades)
    features.update(vol_feats)

    price_feats = compute_price_structure_features(sub_klines)
    features.update(price_feats)

    mom_feats = compute_momentum_features(sub_klines)
    features.update(mom_feats)

    rs_feats = compute_relative_strength_features(sub_klines, btc_df=sub_btc, eth_df=sub_eth)
    features.update(rs_feats)

    liq_feats = compute_liquidity_features(sub_klines)
    features.update(liq_feats)

    deriv_feats = compute_derivatives_features(funding_df, current_time_ms=timestamp_ms)
    features.update(deriv_feats)

    return features
