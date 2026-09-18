"""Generates clean Markdown and interactive HTML research reports for backtest findings."""
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd
from datetime import datetime

from config import REPORTS_DIR


def generate_backtest_report(
    candidates_df: pd.DataFrame,
    bucket_results: Dict[str, pd.DataFrame],
    model_results: Dict[str, Any],
    output_dir: Path = REPORTS_DIR,
) -> Path:
    """Generates a comprehensive Markdown report and companion HTML file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_file = output_dir / "backtest_report.md"
    html_file = output_dir / "backtest_report.html"

    total_candidates = len(candidates_df)
    if total_candidates == 0:
        md_file.write_text("# MEXC Momentum Scanner Backtest Report\n\nNo candidates passed pre-filters in this window.")
        return md_file

    continued_count = int(candidates_df["label_continued"].sum())
    hit_rate = (continued_count / total_candidates) * 100.0
    avg_24h_return = candidates_df["return_24h"].mean() * 100.0
    avg_24h_mfe = candidates_df["mfe_24h"].mean() * 100.0
    avg_24h_mae = candidates_df["mae_24h"].mean() * 100.0

    lines = []
    lines.append("# MEXC Altcoin Momentum Continuation: Backtest Findings")
    lines.append(f"\n*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*")
    lines.append("\n---\n")

    # Executive Summary Table
    lines.append("## 1. Executive Summary")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| **Total Candidates Evaluated** | `{total_candidates:,}` |")
    lines.append(f"| **Successful Continuations (+15% with <=8% DD)** | `{continued_count:,}` (`{hit_rate:.1f}%`) |")
    lines.append(f"| **Average 24h Forward Return** | `{avg_24h_return:+.2f}%` |")
    lines.append(f"| **Average Max Favorable Excursion (24h Peak)** | `+{avg_24h_mfe:.2f}%` |")
    lines.append(f"| **Average Max Drawdown (24h Trough)** | `{avg_24h_mae:.2f}%` |")
    lines.append("")

    # Critical Methodological Note
    lines.append("> [!WARNING]")
    lines.append("> **Lookahead-Bias Free & Temporal Split Recommendation**")
    lines.append("> All features in this study were computed strictly point-in-time using only candles prior to or at bar close.")
    lines.append("> However, because this initial discovery phase spans a 10-day historical window, the sample size is directional.")
    lines.append("> **Recommended Next Step**: Before hardcoding rules or allocating live capital, expand the backtest ingestion to a **3 to 6 month window** and execute a **strict chronological train/test split** (first 70% in time for feature calibration, last 30% held out to test persistence).\n")

    # Feature Bucket Breakdown
    lines.append("## 2. Feature Bucket Performance Breakdown")
    lines.append("This section isolates which preconditions separated pumps that continued from those that faded:\n")

    for feat_name, b_df in bucket_results.items():
        lines.append(f"### Feature: `{feat_name}`")
        lines.append("| Value Bucket | Candidates | Hit Rate (%) | Avg Return (24h) | Avg MFE (24h) | Avg MAE (24h) |")
        lines.append("|---|---|---|---|---|---|")
        for _, row in b_df.iterrows():
            bucket_label = str(row["bucket"]).replace("|", "-")
            count = int(row["count"])
            hr = float(row["hit_rate"]) * 100.0
            ret = float(row["avg_return_24h"]) * 100.0
            mfe = float(row["avg_mfe_24h"]) * 100.0
            mae = float(row["avg_mae_24h"]) * 100.0
            lines.append(f"| `{bucket_label}` | {count} | **{hr:.1f}%** | {ret:+.2f}% | +{mfe:.2f}% | {mae:.2f}% |")
        lines.append("")

    # Machine Learning / Joint Feature Weights
    lines.append("## 3. Joint Feature Importance (Logistic Regression & Decision Tree)")
    if model_results.get("status") == "success":
        lines.append("Logistic Regression standardized coefficients (positive = favors continuation, negative = favors fade):\n")
        lines.append("| Feature | Standardized Weight (LR) | Importance (Tree) |")
        lines.append("|---|---|---|")
        lr_map = model_results.get("logistic_regression_coefficients", {})
        dt_map = model_results.get("decision_tree_importances", {})
        for feat, weight in list(lr_map.items())[:10]:
            tree_imp = dt_map.get(feat, 0.0)
            lines.append(f"| `{feat}` | `{weight:+.4f}` | `{tree_imp:.4f}` |")
        lines.append("")
    else:
        lines.append(f"*Model note: {model_results.get('caveat', 'Insufficient samples to fit model.')}*\n")

    # Top & Bottom Examples
    lines.append("## 4. Notable Candidate Cases")
    top_winners = candidates_df.sort_values(by="mfe_24h", ascending=False).head(3)
    worst_fades = candidates_df.sort_values(by="return_24h", ascending=True).head(3)

    lines.append("### Top Continued Movers")
    lines.append("| Symbol | Timestamp (UTC) | Entry Price | MFE (24h) | Return (24h) | RVOL 20 | Breakout Flag |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, row in top_winners.iterrows():
        dt_str = datetime.utcfromtimestamp(row["timestamp_ms"] / 1000).strftime("%Y-%m-%d %H:%M")
        lines.append(f"| `{row['symbol']}` | {dt_str} | `${row['close']:.4f}` | **+{row['mfe_24h']*100:.1f}%** | {row['return_24h']*100:+.1f}% | {row.get('rvol_20', 1.0):.1f}x | {int(row.get('breakout_flag', 0))} |")

    lines.append("\n### Deepest Fades / Traps")
    lines.append("| Symbol | Timestamp (UTC) | Entry Price | Max Drawdown | Return (24h) | RVOL 20 | Round-Tripped |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, row in worst_fades.iterrows():
        dt_str = datetime.utcfromtimestamp(row["timestamp_ms"] / 1000).strftime("%Y-%m-%d %H:%M")
        lines.append(f"| `{row['symbol']}` | {dt_str} | `${row['close']:.4f}` | **{row['mae_24h']*100:.1f}%** | {row['return_24h']*100:+.1f}% | {row.get('rvol_20', 1.0):.1f}x | {int(row.get('round_tripped', 0))} |")

    # Write Markdown
    md_content = "\n".join(lines)
    md_file.write_text(md_content, encoding="utf-8")

    # Also generate a clean HTML version
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>MEXC Momentum Scanner - Research Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 40px; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: #1e293b; padding: 32px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }}
        h1, h2, h3 {{ color: #38bdf8; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0 32px 0; }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 12px; }}
        tr:hover {{ background: #283548; }}
        code {{ background: #0f172a; color: #f43f5e; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 6px; font-weight: 600; font-size: 13px; }}
        .badge-green {{ background: rgba(34, 197, 94, 0.2); color: #4ade80; }}
        .badge-red {{ background: rgba(239, 68, 68, 0.2); color: #f87171; }}
        .alert {{ background: rgba(245, 158, 11, 0.15); border-left: 4px solid #f59e0b; padding: 16px; margin: 20px 0; border-radius: 6px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>MEXC Altcoin Momentum Continuation Scanner: Backtest Report</h1>
        <div class="alert">
            <strong>Methodology & Lookahead Safety:</strong> All features are computed strictly point-in-time. Expand to 3-6 months with a 70/30 train/test temporal split before deploying capital.
        </div>
        <div style="white-space: pre-wrap; font-family: inherit;">{md_content}</div>
    </div>
</body>
</html>"""
    html_file.write_text(html_content, encoding="utf-8")

    return md_file
