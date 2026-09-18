"""Unit tests for WEEX HMAC-SHA256 authentication and execution bridge."""
import pytest
from src.execution.weex_client import WeexClient
from src.execution.weex_executor import WeexExecutor
from src.execution.paper_executor import PaperExecutor


def test_weex_signature_generation():
    client = WeexClient(
        api_key="test_key",
        api_secret="test_secret_12345",
        passphrase="test_passphrase",
    )
    timestamp = "1700000000000"
    method = "POST"
    path = "/api/v3/trade/order"
    body = '{"symbol":"BTC_USDT","side":"open_long","size":"1.0"}'

    sig = client.generate_signature(timestamp, method, path, body)
    assert isinstance(sig, str)
    assert len(sig) > 10

    # Deterministic check: Re-generating with identical inputs must produce identical Base64 signature
    sig2 = client.generate_signature(timestamp, method, path, body)
    assert sig == sig2

    # Mutating path or body must change signature
    sig_diff = client.generate_signature(timestamp, method, path + "2", body)
    assert sig != sig_diff
    client.close()


def test_weex_executor_safety_gate():
    # 1. With live_enabled=False, must NEVER call live endpoints and must fall back safely to paper trading
    executor = WeexExecutor(live_enabled=False)
    assert executor.live_enabled is False

    res = executor.open_position(
        symbol="ENAUSDT",
        side="BUY",
        entry_price=0.158,
        size_usdt=1000.0,
        stop_loss=0.150,
        take_profit=0.182,
        setup_name="RETEST_HOLD_SPRINGBOARD",
        setup_tier="TIER 1",
    )

    assert res["weex_live"] is False
    assert res["status"] == "FILLED_SIMULATED"
    assert "ENAUSDT" in executor.get_open_positions()

    # Test price update and stop loss / breakeven
    executor.update_price("ENAUSDT", 0.174, 1789695700000)
    pos = executor.get_open_positions()["ENAUSDT"]
    assert pos.tp1_hit is True  # Reached TP1 (+9%), stop loss trailed to breakeven


def test_paper_executor():
    paper = PaperExecutor(default_size_usdt=500.0)
    res = paper.open_position(
        symbol="DOTUSDT",
        side="BUY",
        entry_price=1.10,
        size_usdt=500.0,
        stop_loss=1.04,
        take_profit=1.26,
        setup_name="PRE_BREAKOUT_ACCUMULATION",
        setup_tier="TIER 2",
    )
    assert res["status"] == "FILLED_SIMULATED"
    assert "DOTUSDT" in paper.get_open_positions()
