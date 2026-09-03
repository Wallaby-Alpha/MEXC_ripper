import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from tabulate import tabulate
from src.db.repository import ScannerRepository
from src.models.signal import SIGNAL_METADATA, SignalType


class AnalyticsReporter:
    """Generates analytics tables, performance reports, and exports dataset to CSV/JSON."""

    def __init__(self, repository: ScannerRepository):
        self.repository = repository

    def print_system_stats(self) -> None:
        """Print overall database health and logged counts."""
        counts = self.repository.get_total_counts()
        print("\n" + "=" * 60)
        print("           MEXC MOMENTUM SCANNER - SYSTEM STATUS")
        print("=" * 60)
        print(f"  Total Signals Logged:          {counts['total_signals']}")
        print(f"  Pumping Universe Events:       {counts['total_universe_events']}")
        print(f"  Pending Forward Returns:       {counts['pending_returns']}")
        print(f"  Completed 24h Forward Returns: {counts['completed_returns']}")
        print("=" * 60 + "\n")

    def print_signal_counts_table(self) -> None:
        """Display table of signal firings grouped by detector type."""
        data = self.repository.get_signal_counts_by_type()
        if not data:
            print("No signals recorded in database yet.")
            return

        table_rows = []
        for row in data:
            st_raw = row["signal_type"]
            st_enum = SignalType(st_raw) if st_raw in SignalType._value2member_map_ else None
            meta = SIGNAL_METADATA.get(st_enum, {}) if st_enum else {}
            name = meta.get("name", "Unknown")
            emoji = meta.get("emoji", "")

            table_rows.append([
                f"{emoji} [{st_raw}]",
                name,
                row["count"],
                row.get("first_seen", "N/A"),
                row.get("last_seen", "N/A"),
            ])

        headers = ["Type", "Signal Description", "Total Fires", "First Seen (UTC)", "Last Seen (UTC)"]
        print("\n" + tabulate(table_rows, headers=headers, tablefmt="github") + "\n")

    def print_performance_summary(self) -> None:
        """Display forward return performance and win rates per signal type."""
        summary = self.repository.get_forward_return_summary()
        if not summary:
            print("No forward return data available yet (signals are pending time horizon backfill).")
            return

        table_rows = []
        for s in summary:
            st_raw = s["signal_type"]
            st_enum = SignalType(st_raw) if st_raw in SignalType._value2member_map_ else None
            meta = SIGNAL_METADATA.get(st_enum, {}) if st_enum else {}
            tag = meta.get("tag", f"[{st_raw}]")

            ret_5m = f"{s['avg_ret_5m']:+.2f}%" if s["avg_ret_5m"] is not None else "-"
            ret_15m = f"{s['avg_ret_15m']:+.2f}%" if s["avg_ret_15m"] is not None else "-"
            ret_1h = f"{s['avg_ret_1h']:+.2f}%" if s["avg_ret_1h"] is not None else "-"
            ret_4h = f"{s['avg_ret_4h']:+.2f}%" if s["avg_ret_4h"] is not None else "-"
            ret_24h = f"{s['avg_ret_24h']:+.2f}%" if s["avg_ret_24h"] is not None else "-"
            wr_15m = f"{s['win_rate_15m']:.1f}%" if s["win_rate_15m"] is not None else "-"
            wr_1h = f"{s['win_rate_1h']:.1f}%" if s["win_rate_1h"] is not None else "-"
            wr_24h = f"{s['win_rate_24h']:.1f}%" if s["win_rate_24h"] is not None else "-"

            table_rows.append([
                tag,
                s["total_evaluated"],
                ret_5m,
                ret_15m,
                ret_1h,
                ret_4h,
                ret_24h,
                wr_15m,
                wr_1h,
                wr_24h,
            ])

        headers = [
            "Signal Type",
            "Evaluated",
            "Avg +5m",
            "Avg +15m",
            "Avg +1h",
            "Avg +4h",
            "Avg +24h",
            "WR 15m",
            "WR 1h",
            "WR 24h",
        ]
        print("\n" + tabulate(table_rows, headers=headers, tablefmt="github") + "\n")

    def export_dataset_csv(self, output_dir: str = "exports") -> str:
        """Export all signals and forward returns to CSV for offline research/backtesting."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        query = """
        SELECT
            s.signal_id, s.signal_type, s.symbol, s.timestamp_utc, s.candle_timestamp,
            s.price_at_signal, s.price_change_1h_pct, s.price_change_4h_pct,
            s.volume_surge_ratio, s.quote_volume_24h, s.indicator_snapshot_json,
            s.reasoning, s.timeframe_used, s.telegram_sent,
            r.price_5m, r.price_15m, r.price_1h, r.price_4h, r.price_24h,
            r.return_5m_pct, r.return_15m_pct, r.return_1h_pct, r.return_4h_pct, r.return_24h_pct,
            r.max_runup_24h_pct, r.max_drawdown_24h_pct, r.status as return_status
        FROM signals s
        LEFT JOIN forward_returns r ON s.signal_id = r.signal_id
        ORDER BY s.timestamp_utc ASC;
        """
        with self.repository.db.get_connection() as conn:
            df = pd.read_sql_query(query, conn)

        out_path = Path(output_dir) / f"signals_dataset_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(out_path, index=False)
        print(f"Exported {len(df)} signal rows to {out_path}")
        return str(out_path)
