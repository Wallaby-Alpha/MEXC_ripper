import pytest
from src.config import ScreeningConfig
from src.scanner.universe_manager import UniverseManager


def test_universe_filtering():
    config = ScreeningConfig()
    manager = UniverseManager(config, None, None)

    # Valid spot pairs
    assert manager.is_valid_symbol("BTCUSDT") is True
    assert manager.is_valid_symbol("SOLUSDT") is True
    assert manager.is_valid_symbol("PEPEUSDT") is True

    # Excluded leveraged tokens
    assert manager.is_valid_symbol("BTC3LUSDT") is False
    assert manager.is_valid_symbol("ETH3SUSDT") is False
    assert manager.is_valid_symbol("SOL5LUSDT") is False
    assert manager.is_valid_symbol("BTCBULLUSDT") is False

    # Excluded stablecoin pairs
    assert manager.is_valid_symbol("USDCUSDT") is False
    assert manager.is_valid_symbol("FDUSDUSDT") is False
    assert manager.is_valid_symbol("TUSDUSDT") is False

    # Non-USDT pairs
    assert manager.is_valid_symbol("ETHBTC") is False
