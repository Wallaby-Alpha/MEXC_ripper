import argparse
import asyncio
import sys
from src.analytics.reporter import AnalyticsReporter
from src.config import load_config
from src.db.database import Database
from src.db.repository import ScannerRepository
from src.exchange.mexc_client import MexcClient
from src.main import MomentumScannerApp
from src.tracker.forward_return_tracker import ForwardReturnTracker


async def run_scan_once(verbose: bool = False) -> None:
    app = MomentumScannerApp()
    await app.dispatcher.start()
    try:
        count = await app.run_single_scan_cycle()
        print(f"\n[OK] Scan cycle complete. Fired {count} signals.")
    finally:
        await app.dispatcher.stop()
        await app.mexc_client.close()


async def run_backfill() -> None:
    config = load_config()
    db = Database(config.app.db_path)
    repo = ScannerRepository(db)
    client = MexcClient(config.mexc)
    tracker = ForwardReturnTracker(config.forward_returns, repo, client)
    try:
        print("\nChecking pending forward returns...")
        updated = await tracker.evaluate_pending_signals()
        print(f"[OK] Evaluated & updated {updated} signal records.")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="MEXC Altcoin Momentum Scanner CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan-once
    scan_parser = subparsers.add_parser("scan-once", help="Run a single scan cycle against MEXC and exit")
    scan_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    # stats
    subparsers.add_parser("stats", help="Display system and database statistics")

    # signals
    subparsers.add_parser("signals", help="Display signal firing counts by type")

    # performance
    subparsers.add_parser("performance", help="Display forward-return win rates & performance matrix")

    # export
    export_parser = subparsers.add_parser("export", help="Export signals and forward returns dataset to CSV")
    export_parser.add_argument("--dir", default="exports", help="Output directory for CSV export")

    # backfill
    subparsers.add_parser("backfill", help="Run an immediate forward-return evaluation/backfill pass")

    args = parser.parse_args()

    config = load_config()
    db = Database(config.app.db_path)
    repo = ScannerRepository(db)
    reporter = AnalyticsReporter(repo)

    if args.command == "scan-once":
        asyncio.run(run_scan_once(verbose=args.verbose))
    elif args.command == "stats":
        reporter.print_system_stats()
    elif args.command == "signals":
        reporter.print_signal_counts_table()
    elif args.command == "performance":
        reporter.print_performance_summary()
    elif args.command == "export":
        out = reporter.export_dataset_csv(args.dir)
        print(f"Exported to: {out}")
    elif args.command == "backfill":
        asyncio.run(run_backfill())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
