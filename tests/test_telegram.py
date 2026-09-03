import pytest
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin
from src.telegram.formatter import format_price, format_telegram_alert, format_volume


def test_telegram_alert_formatter():
    signal = SignalResult(
        signal_type=SignalType.A,
        symbol="DOGEUSDT",
        price_at_signal=0.1425,
        candle_timestamp=1700000000000,
        reasoning="1h EMA50 rising (+0.082%), 5m pulled back (2.1% dip) and closed back above EMA20 ($0.1410).",
        indicator_snapshot={"ema20": 0.1410, "ema50": 0.1390},
    )

    coin = PumpingCoin(
        symbol="DOGEUSDT",
        price=0.1425,
        price_change_1h_pct=5.2,
        price_change_4h_pct=11.4,
        volume_surge_ratio=3.5,
        quote_volume_24h=12500000.0,
        trigger_reason="1h +5.2%, 4h +11.4%",
    )

    formatted = format_telegram_alert(signal, coin)
    assert "[A] 🔁 PULLBACK RECLAIM — DOGEUSDT" in formatted
    assert "Price: $0.1425 (+5.20% 1h / +11.40% 4h)" in formatted
    assert "Vol surge: 3.5x | 24h Vol: $12.50M" in formatted
    assert signal.signal_id in formatted
    assert "Time:" in formatted
    assert "Reasoning:" in formatted


def test_format_helpers():
    assert format_volume(2500000) == "$2.50M"
    assert format_volume(450000) == "$450.0K"
    assert format_price(1234.567) == "1234.57"
    assert format_price(1.23456) == "1.2346"
    assert format_price(0.00001234) == "0.00001234"
