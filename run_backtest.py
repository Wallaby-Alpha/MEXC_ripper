"""CLI entry point for Phase 1: Historical Backtester & Feature Discovery."""
import argparse
import logging
import sys
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import (
    DEFAULT_START_TIME,
    DEFAULT_END_TIME,
    DEFAULT_INTERVAL,
    DEFAULT_MIN_24H_TURNOVER_USDT,
    REPORTS_DIR,
)
from src.backtest.engine import BacktestEngine
from src.backtest.analysis import bucket_feature_analysis, fit_feature_importance_model
from src.backtest.report import generate_backtest_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_backtest")
console = Console()


def parse_args():
    parser = argparse.ArgumentParser(description="MEXC Altcoin Momentum Continuation Backtester")
    parser.add_argument("--start", type=str, default=DEFAULT_START_TIME, help="Start ISO timestamp (UTC)")
    parser.add_argument("--end", type=str, default=DEFAULT_END_TIME, help="End ISO timestamp (UTC)")
    parser.add_argument("--interval", type=str, default=DEFAULT_INTERVAL, help="Kline candle interval (e.g. 5m)")
    parser.add_argument("--max-symbols", type=int, default=30, help="Max universe symbols to backtest (for fast runs)")
    parser.add_argument("--min-turnover", type=float, default=DEFAULT_MIN_24H_TURNOVER_USDT, help="Min 24h USDT turnover")
    return parser.parse_args()


def main():
    args = parse_args()
    console.print(
        Panel.fit(
            f"[bold cyan]MEXC Momentum Continuation Backtester (Phase 1)[/bold cyan]\n"
            f"Window: [green]{args.start}[/green] to [green]{args.end}[/green] | Interval: [yellow]{args.interval}[/yellow]\n"
            f"Liquidity Floor: [magenta]${args.min_turnover:,.0f} USDT[/magenta] | Max Universe: [white]{args.max_symbols}[/white]",
            border_style="cyan",
        )
    )

    # 1. Run Walk-Forward Engine
    engine = BacktestEngine(interval=args.interval)
    candidates_df = engine.run(
        start_time_iso=args.start,
        end_time_iso=args.end,
        max_symbols=args.max_symbols,
        min_24h_turnover=args.min_turnover,
    )

    if candidates_df.empty:
        console.print("[bold red]No candidate pump events identified meeting pre-filters in this window.[/bold red]")
        sys.exit(0)

    # 2. Analyze Feature Buckets
    console.print("[bold yellow]Computing feature bucket separations...[/bold yellow]")
    bucket_results = bucket_feature_analysis(candidates_df)

    # 3. Fit Joint Feature Model
    console.print("[bold yellow]Fitting joint feature importance models...[/bold yellow]")
    model_results = fit_feature_importance_model(candidates_df)

    # 4. Generate Reports
    console.print("[bold yellow]Generating Markdown and HTML reports...[/bold yellow]")
    report_path = generate_backtest_report(candidates_df, bucket_results, model_results)

    # 5. Display Console Summary Table
    total = len(candidates_df)
    continued = int(candidates_df["label_continued"].sum())
    hit_rate = (continued / total) * 100.0 if total > 0 else 0.0

    summary_table = Table(title="Backtest Summary (Point-in-Time Verified)", show_header=True, header_style="bold magenta")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="bold green")

    summary_table.add_row("Total Pump Candidates Logged", f"{total:,}")
    summary_table.add_row("Continued Run (+15% gain, <=8% DD)", f"{continued:,} ({hit_rate:.1f}%)")
    summary_table.add_row("Mean 24h Forward Return", f"{candidates_df['return_24h'].mean() * 100:+.2f}%")
    summary_table.add_row("Mean Max Favorable Excursion (24h)", f"+{candidates_df['mfe_24h'].mean() * 100:.2f}%")
    summary_table.add_row("Mean Max Adverse Excursion (24h)", f"{candidates_df['mae_24h'].mean() * 100:.2f}%")
    console.print(summary_table)

    # Display Top 3 Feature Splits
    console.print("\n[bold cyan]Top Predictive Feature Splits:[/bold cyan]")
    for feat_name in ["breakout_flag", "retest_hold_flag", "rvol_20"]:
        if feat_name in bucket_results:
            b_table = Table(title=f"Feature: {feat_name}", header_style="bold blue")
            b_table.add_column("Bucket", style="white")
            b_table.add_column("Count", justify="right")
            b_table.add_column("Hit Rate (%)", justify="right", style="bold yellow")
            b_table.add_column("Avg Return 24h", justify="right")
            b_table.add_column("Avg MFE 24h", justify="right", style="green")

            for _, r in bucket_results[feat_name].iterrows():
                b_table.add_row(
                    str(r["bucket"]),
                    str(int(r["count"])),
                    f"{float(r['hit_rate']) * 100:.1f}%",
                    f"{float(r['avg_return_24h']) * 100:+.2f}%",
                    f"+{float(r['avg_mfe_24h']) * 100:.2f}%",
                )
            console.print(b_table)

    console.print(f"\n[bold green][OK] Research report generated at: {report_path}[/bold green]")
    console.print(
        Panel(
            "[bold yellow]METHODOLOGY NOTE:[/bold yellow] All calculations are strictly point-in-time.\n"
            "Because this discovery run evaluates a 10-day window, results are directional.\n"
            "Next step: Execute an expanded 3-6 month ingestion with a 70/30 temporal train/test split.",
            border_style="yellow",
        )
    )


if __name__ == "__main__":
    main()
