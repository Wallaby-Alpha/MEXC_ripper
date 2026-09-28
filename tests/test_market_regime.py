"""Unit tests for MarketRegimeGate dynamic tier filter."""
import pytest
import pandas as pd
import numpy as np

from src.live.market_regime import MarketRegimeGate, MarketRegimeResult


def _create_mock_btc_df(prices, interval_min=5):
    """Helper to construct a realistic klines DataFrame from price series."""
    n = len(prices)
    now = 1700000000000
    times = [now + (i * interval_min * 60 * 1000) for i in range(n)]
    return pd.DataFrame({
        "open_time": times,
        "open": prices,
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "close": prices,
        "volume": [100.0] * n,
        "close_time": [t + (interval_min * 60 * 1000) - 1 for t in times],
    })


def test_bullish_market():
    """Verify that an upward trending BTC gives BULLISH regime and base min score."""
    # 60 bars steadily rising from 60,000 to 65,000
    prices = np.linspace(60000, 65000, 60).tolist()
    df = _create_mock_btc_df(prices)

    gate = MarketRegimeGate(enabled=True)
    res = gate.evaluate(df, base_min_score=80.0)

    assert res.allowed is True
    assert res.regime == "BULLISH"
    assert res.effective_min_score == 80.0
    assert res.btc_price == pytest.approx(65000.0)
    assert res.btc_1h_change_pct > 0


def test_caution_pullback():
    """Verify that a mild pullback/drift elevates min score from 80 to 90."""
    # Start high (65k), stay flat for 40 bars, then drift down 0.5% below EMA50
    base = [65000.0] * 40
    # Drift down by ~0.5% (below EMA50, but not a sharp flash drop of -1.0%)
    drift = np.linspace(65000, 64650, 20).tolist()
    prices = base + drift
    df = _create_mock_btc_df(prices)

    gate = MarketRegimeGate(enabled=True, dump_1h_threshold=-1.0, caution_penalty=10.0)
    res = gate.evaluate(df, base_min_score=80.0)

    assert res.allowed is True
    assert res.regime == "CAUTION_PULLBACK"
    assert res.effective_min_score == 90.0
    assert "BTC mild pullback" in res.reason


def test_circuit_breaker_1h_flash_dump():
    """Verify that a sharp drop (>1.0% in 1 hour) triggers the hard circuit breaker."""
    # 50 bars at 65,000, then drop 2.0% in the last 12 bars (1 hour on 5m)
    prices = [65000.0] * 50
    dump = np.linspace(65000, 63500, 12).tolist()  # -2.3% drop
    prices += dump
    df = _create_mock_btc_df(prices)

    gate = MarketRegimeGate(enabled=True, dump_1h_threshold=-1.0)
    res = gate.evaluate(df, base_min_score=80.0)

    assert res.allowed is False
    assert res.regime == "CIRCUIT_BREAKER"
    assert "flash drop" in res.reason


def test_circuit_breaker_15m_fast_dump():
    """Verify that a sudden 15-minute dump (>0.6%) triggers the circuit breaker."""
    # Flat, then sudden drop over 3 bars (15m on 5m candles)
    prices = [65000.0] * 55
    fast_dump = [64800.0, 64600.0, 64400.0]  # -0.92% drop in 3 bars
    prices += fast_dump
    df = _create_mock_btc_df(prices)

    gate = MarketRegimeGate(enabled=True, dump_15m_threshold=-0.6)
    res = gate.evaluate(df, base_min_score=80.0)

    assert res.allowed is False
    assert res.regime == "CIRCUIT_BREAKER"
    assert "15m dump" in res.reason


def test_disabled_regime_gate():
    """Verify that disabling the gate always allows trading at base min score."""
    prices = [65000.0] * 50 + [60000.0] * 10  # Massive dump
    df = _create_mock_btc_df(prices)

    gate = MarketRegimeGate(enabled=False)
    res = gate.evaluate(df, base_min_score=80.0)

    assert res.allowed is True
    assert res.regime == "DISABLED"
    assert res.effective_min_score == 80.0


def test_short_or_empty_df():
    """Verify graceful fallback with empty or short data."""
    gate = MarketRegimeGate(enabled=True)
    res_none = gate.evaluate(None, base_min_score=80.0)
    assert res_none.allowed is True
    assert res_none.effective_min_score == 80.0

    short_df = _create_mock_btc_df([65000.0] * 5)
    res_short = gate.evaluate(short_df, base_min_score=80.0)
    assert res_short.allowed is True
    assert res_short.effective_min_score == 80.0
