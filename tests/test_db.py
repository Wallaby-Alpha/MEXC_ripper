import os
import sqlite3
import tempfile
import pytest
from src.db.database import Database
from src.db.repository import ScannerRepository
from src.models.returns import ForwardReturnRecord, ForwardReturnStatus
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingUniverseEvent, UniverseEventType


import gc

@pytest.fixture
def temp_repo():
    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp_file.name
    tmp_file.close()

    db = Database(db_path)
    repo = ScannerRepository(db)
    yield repo

    # Cleanup
    del repo
    del db
    gc.collect()
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        if os.path.exists(wal_path):
            os.remove(wal_path)
        if os.path.exists(shm_path):
            os.remove(shm_path)
    except OSError:
        pass



def test_insert_signal_and_deduplication(temp_repo):
    signal = SignalResult(
        signal_type=SignalType.A,
        symbol="BTCUSDT",
        price_at_signal=65000.0,
        candle_timestamp=1700000000000,
        reasoning="Pullback reclaim fired on 5m",
        indicator_snapshot={"ema50": 64800.0},
    )

    # 1. First insert should succeed
    inserted = temp_repo.insert_signal(
        signal=signal,
        change_1h=3.5,
        change_4h=7.0,
        volume_surge_ratio=2.8,
        quote_volume_24h=1000000.0,
    )
    assert inserted is True

    # 2. Check deduplication: same candle timestamp & signal type should be rejected
    is_dup = temp_repo.is_duplicate_candle_signal("BTCUSDT", "A", 1700000000000)
    assert is_dup is True

    inserted_dup = temp_repo.insert_signal(
        signal=signal,
        change_1h=3.5,
        change_4h=7.0,
        volume_surge_ratio=2.8,
        quote_volume_24h=1000000.0,
    )
    assert inserted_dup is False

    # 3. New candle timestamp on same symbol and signal type should succeed
    signal_new_candle = SignalResult(
        signal_type=SignalType.A,
        symbol="BTCUSDT",
        price_at_signal=65100.0,
        candle_timestamp=1700000300000,
        reasoning="New candle trigger",
        indicator_snapshot={"ema50": 64850.0},
    )
    assert temp_repo.insert_signal(
        signal=signal_new_candle,
        change_1h=3.6,
        change_4h=7.1,
        volume_surge_ratio=2.9,
        quote_volume_24h=1000000.0,
    ) is True


def test_log_universe_events(temp_repo):
    event_enter = PumpingUniverseEvent(
        symbol="ETHUSDT",
        event_type=UniverseEventType.ENTER,
        timestamp_utc="2026-09-03T12:00:00+00:00",
        price=3500.0,
        price_change_1h_pct=4.2,
        price_change_4h_pct=6.5,
        volume_surge_ratio=3.0,
        quote_volume_24h=20000000.0,
        reason="1h +4.2%",
    )
    row_id = temp_repo.log_universe_event(event_enter)
    assert row_id is not None and row_id > 0


def test_forward_returns_update(temp_repo):
    signal = SignalResult(
        signal_type=SignalType.F,
        symbol="AVAXUSDT",
        price_at_signal=40.0,
        candle_timestamp=1700000000000,
        reasoning="Volume spike",
    )
    temp_repo.insert_signal(signal, 5.0, 10.0, 4.0, 500000.0)

    pending = temp_repo.get_pending_forward_returns(limit=10)
    assert len(pending) == 1
    assert pending[0]["signal_id"] == signal.signal_id

    # Update forward returns
    record = ForwardReturnRecord(
        signal_id=signal.signal_id,
        symbol="AVAXUSDT",
        price_at_signal=40.0,
        signal_timestamp_utc=pending[0]["signal_timestamp_utc"],
        price_5m=40.8,
        return_5m_pct=2.0,
        price_15m=41.2,
        return_15m_pct=3.0,
        status=ForwardReturnStatus.PARTIALLY_FILLED,
    )
    temp_repo.update_forward_return(record)

    recent = temp_repo.get_recent_signals(limit=5)
    assert len(recent) == 1
    assert recent[0]["return_5m_pct"] == 2.0
    assert recent[0]["return_15m_pct"] == 3.0
