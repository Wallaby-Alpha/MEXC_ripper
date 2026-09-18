"""Unit tests for MEXC API Client and SQLite Cache."""
import tempfile
from pathlib import Path
import pytest
import pandas as pd

from src.data_ingestion.cache import MarketDataCache
from src.data_ingestion.mexc_client import MexcClient


def test_sqlite_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_market.sqlite"
        cache = MarketDataCache(db_path=db_path)

        # Save dummy klines
        dummy_klines = [
            [1700000000000, "1.0", "1.2", "0.9", "1.1", "1000.0", 1700000300000, "1100.0"],
            [1700000300000, "1.1", "1.3", "1.0", "1.2", "1200.0", 1700000600000, "1440.0"],
        ]
        cache.save_klines("TESTUSDT", "5m", dummy_klines)

        min_t, max_t = cache.get_kline_range("TESTUSDT", "5m")
        assert min_t == 1700000000000
        assert max_t == 1700000300000

        df = cache.get_klines("TESTUSDT", "5m")
        assert len(df) == 2
        assert df["close"].iloc[0] == 1.1


def test_mexc_client_smoke():
    client = MexcClient()
    # Test ping / exchange info
    ex_info = client.get_exchange_info()
    assert "symbols" in ex_info
    assert len(ex_info["symbols"]) > 100
    client.close()
