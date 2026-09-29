"""Unit tests for LiveMomentumScanner poll_cycle in OPTObot-v4."""
import pytest
from unittest.mock import MagicMock
from src.live.scanner import LiveMomentumScanner
from src.live.market_regime import MarketRegimeGate


def test_scanner_poll_cycle_executes_without_errors():
    mock_client = MagicMock()
    # Mock BTC and ETH klines
    bars_btc = [[1700000000000 + i * 300000, 65000.0, 65100.0, 64900.0, 65050.0, 100.0, 1700000000000 + (i+1) * 300000 - 1, 6505000.0] for i in range(80)]
    mock_client.get_klines.return_value = bars_btc
    mock_client.get_ticker_24hr.return_value = [
        {"symbol": "BTCUSDT", "quoteVolume": "1000000000"},
        {"symbol": "ETHUSDT", "quoteVolume": "500000000"},
        {"symbol": "ZROUSDT", "quoteVolume": "5000000"},
    ]
    mock_client.get_agg_trades.return_value = []

    gate = MarketRegimeGate(enabled=True)
    scanner = LiveMomentumScanner(
        client=mock_client,
        interval="15m",
        min_score=80.0,
        alpha_only=True,
        regime_gate=gate,
    )

    # Execute one poll cycle
    alerts = scanner.poll_cycle()
    assert isinstance(alerts, list)
    assert scanner.current_regime is not None
