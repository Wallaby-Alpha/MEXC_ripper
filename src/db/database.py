import sqlite3
from pathlib import Path
from typing import Optional
from src.logger import get_logger

logger = get_logger("database")


class Database:
    """Manages SQLite database connection, PRAGMA tuning, and schema migrations."""

    def __init__(self, db_path: str = "data/scanner_data.db"):
        self.db_path = db_path
        self._ensure_directory()
        self.init_schema()

    def _ensure_directory(self) -> None:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # PRAGMA optimizations for speed and high-concurrency read/write
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        return conn

    def init_schema(self) -> None:
        """Initialize required database tables and indexes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Pumping Universe Events (Enter/Exit transitions)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS pumping_universe_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                event_type TEXT NOT NULL, -- 'ENTER' or 'EXIT'
                timestamp_utc TEXT NOT NULL,
                price REAL NOT NULL,
                price_change_1h_pct REAL NOT NULL,
                price_change_4h_pct REAL NOT NULL,
                volume_surge_ratio REAL NOT NULL,
                quote_volume_24h REAL NOT NULL,
                reason TEXT NOT NULL,
                metrics_json TEXT
            );
            """)

            # 2. Signals Log Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                signal_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                candle_timestamp INTEGER NOT NULL,
                price_at_signal REAL NOT NULL,
                price_change_1h_pct REAL NOT NULL,
                price_change_4h_pct REAL NOT NULL,
                volume_surge_ratio REAL NOT NULL,
                quote_volume_24h REAL NOT NULL,
                indicator_snapshot_json TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                timeframe_used TEXT DEFAULT '5m',
                telegram_sent INTEGER DEFAULT 0,
                telegram_sent_at TEXT,
                error TEXT,
                UNIQUE(symbol, signal_type, candle_timestamp)
            );
            """)

            # 3. Forward Returns Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS forward_returns (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                price_at_signal REAL NOT NULL,
                signal_timestamp_utc TEXT NOT NULL,
                price_5m REAL,
                price_15m REAL,
                price_1h REAL,
                price_4h REAL,
                price_24h REAL,
                return_5m_pct REAL,
                return_15m_pct REAL,
                return_1h_pct REAL,
                return_4h_pct REAL,
                return_24h_pct REAL,
                max_runup_24h_pct REAL,
                max_drawdown_24h_pct REAL,
                status TEXT DEFAULT 'PENDING',
                last_evaluated_at TEXT,
                FOREIGN KEY (signal_id) REFERENCES signals(signal_id) ON DELETE CASCADE
            );
            """)

            # Indexes for high performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_universe_symbol_time ON pumping_universe_events(symbol, timestamp_utc);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_type_time ON signals(signal_type, timestamp_utc);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol_time ON signals(symbol, timestamp_utc);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_returns_status ON forward_returns(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_returns_signal_time ON forward_returns(signal_timestamp_utc);")

            conn.commit()
            logger.info("Database initialized successfully at %s", self.db_path)
