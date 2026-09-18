"""SQLite caching layer for market data, klines, aggTrades, and universe metadata."""
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd

from config import SQLITE_DB_PATH


import contextlib


class MarketDataCache:
    """Manages SQLite storage for raw market data to avoid re-fetching."""

    def __init__(self, db_path: Path = SQLITE_DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Klines table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS klines (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    close_time INTEGER NOT NULL,
                    quote_volume REAL NOT NULL,
                    PRIMARY KEY (symbol, interval, open_time)
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_klines_sym_time 
                ON klines (symbol, interval, open_time);
            """)

            # AggTrades table for CVD
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agg_trades (
                    symbol TEXT NOT NULL,
                    trade_id TEXT,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    trade_time INTEGER NOT NULL,
                    is_buyer_maker INTEGER NOT NULL
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_agg_trades_sym_time 
                ON agg_trades (symbol, trade_time);
            """)

            # Symbol metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS symbol_metadata (
                    symbol TEXT PRIMARY KEY,
                    base_asset TEXT,
                    quote_asset TEXT,
                    status TEXT,
                    first_kline_time INTEGER,
                    quote_volume_24h REAL,
                    updated_at INTEGER
                );
            """)

            # Funding rate history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS funding_rates (
                    symbol TEXT NOT NULL,
                    settle_time INTEGER NOT NULL,
                    funding_rate REAL NOT NULL,
                    PRIMARY KEY (symbol, settle_time)
                );
            """)
            conn.commit()

    def save_klines(self, symbol: str, interval: str, klines: List[List[Any]]):
        """Save a list of kline rows from MEXC API:
        [openTime, open, high, low, close, volume, closeTime, quoteVolume]
        """
        if not klines:
            return
        records = [
            (
                symbol,
                interval,
                int(k[0]),
                float(k[1]),
                float(k[2]),
                float(k[3]),
                float(k[4]),
                float(k[5]),
                int(k[6]),
                float(k[7]) if len(k) > 7 else 0.0,
            )
            for k in klines
        ]
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO klines 
                (symbol, interval, open_time, open, high, low, close, volume, close_time, quote_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                records,
            )
            conn.commit()

    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch klines as a sorted Pandas DataFrame."""
        query = "SELECT open_time, open, high, low, close, volume, close_time, quote_volume FROM klines WHERE symbol = ? AND interval = ?"
        params: List[Any] = [symbol, interval]

        if start_time is not None:
            query += " AND open_time >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND open_time <= ?"
            params.append(end_time)

        query += " ORDER BY open_time ASC"

        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if not df.empty:
            df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df.set_index("datetime", inplace=False)
        return df

    def get_kline_range(self, symbol: str, interval: str) -> Tuple[Optional[int], Optional[int]]:
        """Return (min_open_time, max_open_time) cached for a symbol/interval."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MIN(open_time), MAX(open_time) FROM klines WHERE symbol = ? AND interval = ?",
                (symbol, interval),
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0]), int(row[1])
            return None, None

    def save_agg_trades(self, symbol: str, trades: List[Dict[str, Any]]):
        """Save aggTrades list."""
        if not trades:
            return
        records = [
            (
                symbol,
                str(t.get("a", t.get("f", ""))),
                float(t["p"]),
                float(t["q"]),
                int(t["T"]),
                1 if t.get("m", False) else 0,
            )
            for t in trades
        ]
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO agg_trades (symbol, trade_id, price, quantity, trade_time, is_buyer_maker)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                records,
            )
            conn.commit()

    def get_agg_trades(
        self,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch trades for CVD computation."""
        query = "SELECT trade_time, price, quantity, is_buyer_maker FROM agg_trades WHERE symbol = ?"
        params: List[Any] = [symbol]

        if start_time is not None:
            query += " AND trade_time >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND trade_time <= ?"
            params.append(end_time)

        query += " ORDER BY trade_time ASC"
        with self._get_connection() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def save_symbol_metadata(self, metadata: List[Dict[str, Any]]):
        """Save symbol universe metadata."""
        if not metadata:
            return
        records = [
            (
                m["symbol"],
                m.get("baseAsset", ""),
                m.get("quoteAsset", ""),
                m.get("status", "1"),
                m.get("first_kline_time"),
                float(m.get("quoteVolume", 0.0)),
                int(m.get("updated_at", 0)),
            )
            for m in metadata
        ]
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO symbol_metadata 
                (symbol, base_asset, quote_asset, status, first_kline_time, quote_volume_24h, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                records,
            )
            conn.commit()

    def get_symbol_metadata(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """Retrieve symbol metadata."""
        query = "SELECT * FROM symbol_metadata"
        params: List[Any] = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        with self._get_connection() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def save_funding_rates(self, symbol: str, rates: List[Dict[str, Any]]):
        """Save contract funding rates."""
        if not rates:
            return
        records = [
            (symbol, int(r["settleTime"]), float(r["fundingRate"]))
            for r in rates
            if "settleTime" in r and "fundingRate" in r
        ]
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO funding_rates (symbol, settle_time, funding_rate)
                VALUES (?, ?, ?)
            """,
                records,
            )
            conn.commit()

    def get_funding_rates(self, symbol: str, end_time: Optional[int] = None, limit: int = 10) -> pd.DataFrame:
        """Retrieve recent funding rates strictly <= end_time."""
        query = "SELECT settle_time, funding_rate FROM funding_rates WHERE symbol = ?"
        params: List[Any] = [symbol]
        if end_time is not None:
            query += " AND settle_time <= ?"
            params.append(end_time)
        query += " ORDER BY settle_time DESC LIMIT ?"
        params.append(limit)
        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        return df.iloc[::-1].reset_index(drop=True)  # Return chronological
