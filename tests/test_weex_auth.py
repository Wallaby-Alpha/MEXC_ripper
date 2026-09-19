"""Unit tests for WEEX HMAC-SHA256 authentication and execution bridge."""
import pytest
from src.execution.weex_client import WeexClient
from src.execution.weex_executor import WeexExecutor
from src.execution.paper_executor import PaperExecutor
from src.execution.weex_symbol_mapper import WeexSymbolResolver


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
    resolver = WeexSymbolResolver(auto_fetch=False)
    executor = WeexExecutor(symbol_resolver=resolver, live_enabled=False)
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


def test_weex_native_tpsl_placement(monkeypatch):
    """Test that live execution places entry AND native exchange-level TP and SL plan orders."""
    client = WeexClient(api_key="k", api_secret="s", passphrase="p")

    calls = []

    def mock_place_order(symbol, side, order_type="market", size=1.0, **kwargs):
        calls.append({"type": "order", "symbol": symbol, "side": side, "size": size, **kwargs})
        return {"code": "00000", "data": {"orderId": "main_12345"}}

    def mock_place_tpsl(symbol, plan_type, trigger_price, size, position_side="LONG", **kwargs):
        calls.append({
            "type": "tpsl",
            "symbol": symbol,
            "plan_type": plan_type,
            "trigger_price": trigger_price,
            "size": size,
            "position_side": position_side,
        })
        return {"code": "00000", "data": {"orderId": f"{plan_type}_999"}}

    def mock_set_leverage(symbol, leverage, **kwargs):
        calls.append({"type": "leverage", "symbol": symbol, "leverage": leverage})
        return {"code": "00000"}

    monkeypatch.setattr(client, "set_leverage", mock_set_leverage)
    monkeypatch.setattr(client, "place_order", mock_place_order)
    monkeypatch.setattr(client, "place_tpsl_order", mock_place_tpsl)

    resolver = WeexSymbolResolver(auto_fetch=False)
    resolver._build_mappings([
        {"symbol": "SUIUSDT", "pricePrecision": 4, "quantityPrecision": 0, "minOrderSize": 1.0}
    ])

    executor = WeexExecutor(weex_client=client, symbol_resolver=resolver, live_enabled=True)
    res = executor.open_position(
        symbol="SUIUSDT",
        side="BUY",
        entry_price=2.00,
        size_usdt=1000.0,
        stop_loss=1.93,     # -3.5%
        take_profit=2.15,   # +7.5%
        setup_name="PRE_BREAKOUT_ACCUMULATION",
        setup_tier="TIER 1 (ALPHA SETUP)",
    )

    assert res["status"] == "FILLED_WEEX_LIVE"
    assert res["order_id"] == "main_12345"
    assert res["native_tp_order_id"] == "TAKE_PROFIT_999"
    assert res["native_sl_order_id"] == "STOP_LOSS_999"

    # Verify calls
    assert len(calls) == 4
    assert calls[0]["type"] == "leverage"
    assert calls[0]["leverage"] == 10
    assert calls[1]["type"] == "order"
    assert calls[1]["symbol"] == "SUIUSDT"
    assert calls[2]["type"] == "tpsl"
    assert calls[2]["plan_type"] == "TAKE_PROFIT"
    assert float(calls[2]["trigger_price"]) == 2.15
    assert calls[3]["type"] == "tpsl"
    assert calls[3]["plan_type"] == "STOP_LOSS"
    assert float(calls[3]["trigger_price"]) == 1.93

    # Now verify close cancels lingering TP/SL orders
    canceled = []
    def mock_cancel_tpsl(symbol, order_id):
        canceled.append(order_id)
        return {"code": "00000"}

    monkeypatch.setattr(client, "cancel_tpsl_order", mock_cancel_tpsl)
    executor.close_position("SUIUSDT", reason="TAKE_PROFIT_REACHED")
    assert "TAKE_PROFIT_999" in canceled
    assert "STOP_LOSS_999" in canceled
