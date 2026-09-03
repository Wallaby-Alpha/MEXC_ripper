import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from src.db.database import Database
from src.logger import get_logger
from src.models.returns import ForwardReturnRecord, ForwardReturnStatus
from src.models.signal import SignalLogRecord, SignalResult
from src.models.universe import PumpingUniverseEvent, UniverseEventType

logger = get_logger("repository")


class ScannerRepository:
    """Repository handling all database operations for signals, universe, and returns."""

    def __init__(self, db: Database):
        self.db = db

    # --------------------------------------------------------------------------
    # Pumping Universe Events
    # --------------------------------------------------------------------------
    def log_universe_event(self, event: PumpingUniverseEvent) -> int:
        """Log a coin entering or exiting the pumping universe."""
        query = """
        INSERT INTO pumping_universe_events (
            symbol, event_type, timestamp_utc, price, price_change_1h_pct,
            price_change_4h_pct, volume_surge_ratio, quote_volume_24h, reason, metrics_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                (
                    event.symbol,
                    event.event_type.value if hasattr(event.event_type, "value") else event.event_type,
                    event.timestamp_utc,
                    event.price,
                    event.price_change_1h_pct,
                    event.price_change_4h_pct,
                    event.volume_surge_ratio,
                    event.quote_volume_24h,
                    event.reason,
                    event.metrics_json,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    # --------------------------------------------------------------------------
    # Signals
    # --------------------------------------------------------------------------
    def is_duplicate_candle_signal(self, symbol: str, signal_type: str, candle_timestamp: int) -> bool:
        """Check if this exact candle for this signal type & symbol has already been logged."""
        query = "SELECT 1 FROM signals WHERE symbol = ? AND signal_type = ? AND candle_timestamp = ? LIMIT 1;"
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (symbol, signal_type, candle_timestamp))
            return cursor.fetchone() is not None

    def insert_signal(
        self,
        signal: SignalResult,
        change_1h: float,
        change_4h: float,
        volume_surge_ratio: float,
        quote_volume_24h: float,
        telegram_sent: bool = False,
        telegram_sent_at: Optional[str] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Insert a newly fired signal and create an associated pending forward_returns row.
        Returns True if inserted, False if duplicate candle already exists."""
        signal_query = """
        INSERT OR IGNORE INTO signals (
            signal_id, signal_type, symbol, timestamp_utc, candle_timestamp,
            price_at_signal, price_change_1h_pct, price_change_4h_pct,
            volume_surge_ratio, quote_volume_24h, indicator_snapshot_json,
            reasoning, timeframe_used, telegram_sent, telegram_sent_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        returns_query = """
        INSERT OR IGNORE INTO forward_returns (
            signal_id, symbol, price_at_signal, signal_timestamp_utc, status
        ) VALUES (?, ?, ?, ?, ?);
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                signal_query,
                (
                    signal.signal_id,
                    signal.signal_type.value if hasattr(signal.signal_type, "value") else signal.signal_type,
                    signal.symbol,
                    signal.timestamp_utc.isoformat(),
                    signal.candle_timestamp,
                    signal.price_at_signal,
                    change_1h,
                    change_4h,
                    volume_surge_ratio,
                    quote_volume_24h,
                    json.dumps(signal.indicator_snapshot),
                    signal.reasoning,
                    signal.timeframe_used,
                    1 if telegram_sent else 0,
                    telegram_sent_at,
                    error,
                ),
            )
            if cursor.rowcount == 0:
                # Duplicate candle close already exists
                return False

            cursor.execute(
                returns_query,
                (
                    signal.signal_id,
                    signal.symbol,
                    signal.price_at_signal,
                    signal.timestamp_utc.isoformat(),
                    ForwardReturnStatus.PENDING.value,
                ),
            )
            conn.commit()
            return True

    def mark_telegram_sent(self, signal_id: str, sent_at: Optional[str] = None, error: Optional[str] = None) -> None:
        """Update the telegram dispatch status for a signal."""
        query = """
        UPDATE signals
        SET telegram_sent = ?, telegram_sent_at = ?, error = ?
        WHERE signal_id = ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                (
                    1 if error is None else 0,
                    sent_at or datetime.now(timezone.utc).isoformat(),
                    error,
                    signal_id,
                ),
            )
            conn.commit()

    # --------------------------------------------------------------------------
    # Forward Returns
    # --------------------------------------------------------------------------
    def get_pending_forward_returns(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get signals whose forward returns are still pending or partially filled."""
        query = """
        SELECT r.*, s.candle_timestamp
        FROM forward_returns r
        JOIN signals s ON r.signal_id = s.signal_id
        WHERE r.status IN ('PENDING', 'PARTIALLY_FILLED')
        ORDER BY r.signal_timestamp_utc ASC
        LIMIT ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def update_forward_return(self, record: ForwardReturnRecord) -> None:
        """Update forward return metrics for a signal."""
        query = """
        UPDATE forward_returns
        SET price_5m = ?, price_15m = ?, price_1h = ?, price_4h = ?, price_24h = ?,
            return_5m_pct = ?, return_15m_pct = ?, return_1h_pct = ?, return_4h_pct = ?, return_24h_pct = ?,
            max_runup_24h_pct = ?, max_drawdown_24h_pct = ?, status = ?, last_evaluated_at = ?
        WHERE signal_id = ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                (
                    record.price_5m,
                    record.price_15m,
                    record.price_1h,
                    record.price_4h,
                    record.price_24h,
                    record.return_5m_pct,
                    record.return_15m_pct,
                    record.return_1h_pct,
                    record.return_4h_pct,
                    record.return_24h_pct,
                    record.max_runup_24h_pct,
                    record.max_drawdown_24h_pct,
                    record.status.value if hasattr(record.status, "value") else record.status,
                    record.last_evaluated_at or datetime.now(timezone.utc).isoformat(),
                    record.signal_id,
                ),
            )
            conn.commit()

    # --------------------------------------------------------------------------
    # Analytics & Summary Queries
    # --------------------------------------------------------------------------
    def get_signal_counts_by_type(self) -> List[Dict[str, Any]]:
        """Get total signal counts grouped by signal type."""
        query = """
        SELECT signal_type, COUNT(*) as count, MIN(timestamp_utc) as first_seen, MAX(timestamp_utc) as last_seen
        FROM signals
        GROUP BY signal_type
        ORDER BY signal_type ASC;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def get_forward_return_summary(self) -> List[Dict[str, Any]]:
        """Compute average returns and win rates (+return > 0) per signal type across time horizons."""
        query = """
        SELECT
            s.signal_type,
            COUNT(r.signal_id) as total_evaluated,
            AVG(r.return_5m_pct) as avg_ret_5m,
            AVG(r.return_15m_pct) as avg_ret_15m,
            AVG(r.return_1h_pct) as avg_ret_1h,
            AVG(r.return_4h_pct) as avg_ret_4h,
            AVG(r.return_24h_pct) as avg_ret_24h,
            AVG(r.max_runup_24h_pct) as avg_max_runup_24h,
            AVG(r.max_drawdown_24h_pct) as avg_max_dd_24h,
            100.0 * SUM(CASE WHEN r.return_15m_pct > 0 THEN 1 ELSE 0 END) / COUNT(CASE WHEN r.return_15m_pct IS NOT NULL THEN 1 END) as win_rate_15m,
            100.0 * SUM(CASE WHEN r.return_1h_pct > 0 THEN 1 ELSE 0 END) / COUNT(CASE WHEN r.return_1h_pct IS NOT NULL THEN 1 END) as win_rate_1h,
            100.0 * SUM(CASE WHEN r.return_4h_pct > 0 THEN 1 ELSE 0 END) / COUNT(CASE WHEN r.return_4h_pct IS NOT NULL THEN 1 END) as win_rate_4h,
            100.0 * SUM(CASE WHEN r.return_24h_pct > 0 THEN 1 ELSE 0 END) / COUNT(CASE WHEN r.return_24h_pct IS NOT NULL THEN 1 END) as win_rate_24h
        FROM signals s
        JOIN forward_returns r ON s.signal_id = r.signal_id
        WHERE r.status != 'PENDING'
        GROUP BY s.signal_type
        ORDER BY s.signal_type ASC;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_signals(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve the most recent logged signals."""
        query = """
        SELECT s.*, r.return_5m_pct, r.return_15m_pct, r.return_1h_pct, r.return_4h_pct, r.return_24h_pct, r.status as return_status
        FROM signals s
        LEFT JOIN forward_returns r ON s.signal_id = r.signal_id
        ORDER BY s.timestamp_utc DESC
        LIMIT ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_total_counts(self) -> Dict[str, int]:
        """Get high-level database stats."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM signals;")
            total_signals = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM pumping_universe_events;")
            total_events = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM forward_returns WHERE status = 'COMPLETED';")
            completed_returns = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM forward_returns WHERE status IN ('PENDING', 'PARTIALLY_FILLED');")
            pending_returns = cursor.fetchone()[0]
            return {
                "total_signals": total_signals,
                "total_universe_events": total_events,
                "completed_returns": completed_returns,
                "pending_returns": pending_returns,
            }
