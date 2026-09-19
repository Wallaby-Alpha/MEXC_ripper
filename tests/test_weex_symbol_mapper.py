"""Unit tests for WEEX symbol mapping, contract resolution, and precision formatting."""
import pytest
from src.execution.weex_symbol_mapper import WeexSymbolResolver
from src.execution.weex_executor import WeexExecutor


def test_weex_symbol_resolver_mapping():
    resolver = WeexSymbolResolver(auto_fetch=False)
    # Mock sample contracts
    mock_contracts = [
        {"symbol": "cmt_btcusdt", "tick_size": 1, "size_increment": 0.001, "minOrderSize": 0.001},
        {"symbol": "cmt_suiusdt", "tick_size": 4, "size_increment": 1.0, "minOrderSize": 1.0},
        {"symbol": "cmt_1000pepeusdt", "tick_size": 6, "size_increment": 100.0, "minOrderSize": 100.0},
        {"symbol": "cmt_enausdt", "tick_size": 4, "size_increment": 1.0, "minOrderSize": 1.0},
    ]
    resolver._build_mappings(mock_contracts)

    # 1. Standard coin mapping
    assert resolver.resolve("SUIUSDT") == "SUIUSDT"
    assert resolver.resolve("suiusdt") == "SUIUSDT"
    assert resolver.resolve("BTCUSDT") == "BTCUSDT"
    assert resolver.resolve("ENAUSDT") == "ENAUSDT"

    # 2. Multiplier coin mapping (PEPE -> 1000PEPE)
    assert resolver.resolve("PEPEUSDT") == "1000PEPEUSDT"
    assert resolver.resolve("1000PEPEUSDT") == "1000PEPEUSDT"

    # 3. Unlisted coin mapping (Must return None to protect against bad orders)
    assert resolver.resolve("FAKECOIN999USDT") is None

    # 4. Price precision formatting
    formatted_btc_p = resolver.format_price("BTCUSDT", 62450.384)
    assert formatted_btc_p == "62450.4"

    formatted_sui_p = resolver.format_price("SUIUSDT", 1.854382)
    assert formatted_sui_p == "1.8544"

    # 5. Size increment formatting
    formatted_sui_sz = resolver.format_size("SUIUSDT", 543.82)
    assert formatted_sui_sz == "544"


def test_weex_executor_unlisted_coin_safety():
    """Verify WeexExecutor gracefully skips live execution for unlisted coins."""
    resolver = WeexSymbolResolver(auto_fetch=False)
    resolver.contract_map = {"SUIUSDT": {"symbol": "SUIUSDT", "price_precision": 4, "quantity_precision": -1, "min_order_size": 10.0}}
    resolver.alias_to_canonical = {"SUIUSDT": "SUIUSDT", "suiusdt": "SUIUSDT"}

    executor = WeexExecutor(symbol_resolver=resolver, live_enabled=True)

    # Trade an unlisted coin
    res = executor.open_position(
        symbol="UNLISTED_MEME_COIN_USDT",
        side="BUY",
        entry_price=0.001,
        size_usdt=500.0,
        stop_loss=0.000965,
        take_profit=0.001075,
        setup_name="PRE_BREAKOUT_ACCUMULATION",
        setup_tier="TIER 1 (ALPHA SETUP)",
    )

    # Must be safely skipped, not crash
    assert res["status"] == "SKIPPED_UNLISTED_ON_WEEX"
    assert res["weex_live"] is False
