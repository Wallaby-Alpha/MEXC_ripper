"""Feature bucket analysis and machine learning evaluation for pump continuation."""
import logging
from typing import Dict, Any, List, Tuple
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# List of key predictive candidate features to analyze
CORE_FEATURES = [
    "rvol_20",
    "rvol_60",
    "volume_persistence",
    "cvd_rolling",
    "cvd_price_divergence",
    "pre_breakout_base_quality",
    "breakout_flag",
    "retest_hold_flag",
    "swing_structure_hh_hl",
    "extension_atr",
    "atr_pct",
    "rsi_14",
    "rsi_pullback_depth",
    "macd_histogram_slope",
    "rs_vs_btc_1h",
    "rs_vs_btc_4h",
    "turnover_24h",
]


def bucket_feature_analysis(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Splits each feature into discrete quartiles or binary categories,
    and computes the continuation hit rate, average 4h/12h/24h return, and average MFE.
    """
    results: Dict[str, pd.DataFrame] = {}

    if df.empty or len(df) < 5:
        return results

    target_col = "label_continued"
    ret_col = "return_24h"
    mfe_col = "mfe_24h"
    mae_col = "mae_24h"

    for feat in CORE_FEATURES:
        if feat not in df.columns:
            continue

        series = pd.to_numeric(df[feat], errors="coerce").fillna(0.0)
        unique_vals = series.nunique()

        if unique_vals <= 3:
            # Binary or discrete categorical feature
            buckets = series.astype(str)
        else:
            # Continuous feature: 4 quartiles
            try:
                buckets = pd.qcut(series, q=4, duplicates="drop").astype(str)
            except Exception:
                buckets = pd.cut(series, bins=3).astype(str)

        grouped = df.groupby(buckets).agg(
            count=(target_col, "count"),
            hit_rate=(target_col, "mean"),
            avg_return_24h=(ret_col, "mean"),
            avg_mfe_24h=(mfe_col, "mean"),
            avg_mae_24h=(mae_col, "mean"),
        ).reset_index()

        grouped.rename(columns={"index": "bucket", feat: "bucket"}, inplace=True)
        # Sort by hit_rate descending
        grouped = grouped.sort_values(by="hit_rate", ascending=False)
        results[feat] = grouped

    return results


def fit_feature_importance_model(df: pd.DataFrame) -> Dict[str, Any]:
    """Fits Logistic Regression and shallow Decision Tree on candidate features.
    Provides feature coefficients / importances with strict small-sample caveats.
    """
    model_output: Dict[str, Any] = {
        "status": "insufficient_data",
        "sample_size": len(df),
        "positive_rate": 0.0,
        "feature_importances": {},
        "caveat": (
            "CAUTION: Sample derived from a short 10-day window. Results are directional only. "
            "A full 3-6 month window with a 70/30 temporal train/test split is required before live deployment."
        ),
    }

    if df.empty or len(df) < 10 or "label_continued" not in df.columns:
        return model_output

    # Prepare features and target
    valid_feats = [f for f in CORE_FEATURES if f in df.columns]
    X = df[valid_feats].apply(pd.to_numeric, errors="coerce").fillna(0.0).values
    y = df["label_continued"].astype(int).values

    pos_count = np.sum(y)
    pos_rate = pos_count / len(y)
    model_output["positive_rate"] = float(pos_rate)
    model_output["sample_size"] = len(y)

    if pos_count < 2 or pos_count == len(y):
        model_output["status"] = "class_imbalance_single_class"
        return model_output

    # Fit Logistic Regression with standardization
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    lr = LogisticRegression(max_iter=1000, C=1.0)
    lr.fit(X_scaled, y)
    lr_coefs = dict(zip(valid_feats, [float(c) for c in lr.coef_[0]]))

    # Fit shallow Decision Tree (max_depth=3 to prevent overfitting)
    dt = DecisionTreeClassifier(max_depth=3, random_state=42)
    dt.fit(X, y)
    dt_importances = dict(zip(valid_feats, [float(imp) for imp in dt.feature_importances_]))

    # Rank features by absolute magnitude
    ranked_lr = sorted(lr_coefs.items(), key=lambda x: abs(x[1]), reverse=True)
    ranked_dt = sorted(dt_importances.items(), key=lambda x: x[1], reverse=True)

    model_output["status"] = "success"
    model_output["logistic_regression_coefficients"] = dict(ranked_lr)
    model_output["decision_tree_importances"] = dict(ranked_dt)

    return model_output
