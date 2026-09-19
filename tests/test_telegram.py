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


def test_alert_dispatcher_alpha_only_filter(tmp_path, monkeypatch):
    from src.live.alerting import AlertDispatcher

    log_file = tmp_path / "test_alerts.jsonl"
    sent_messages = []

    # Mock httpx.post to intercept Telegram dispatches
    def mock_post(url, json=None, **kwargs):
        sent_messages.append(json)
        class DummyResp:
            status_code = 200
        return DummyResp()

    monkeypatch.setattr("httpx.post", mock_post)

    dispatcher = AlertDispatcher(
        log_path=log_file,
        telegram_bot_token="test_token",
        telegram_chat_id="test_chat",
        alpha_only=True,
    )

    candidate = {
        "symbol": "DOGEUSDT",
        "close": 0.15,
        "timestamp_ms": 1700000000000,
        "rvol_20": 2.5,
        "rsi_14": 60.0,
        "cvd_rolling": 50000.0,
    }
    levels = {
        "stop_loss": 0.14475,
        "take_profit_1": 0.15525,
        "take_profit_2": 0.16125,
        "take_profit_3": 0.16800,
    }

    # 1. Non-Alpha setup should be completely rejected
    dispatcher.dispatch_alert(
        candidate=candidate,
        setup_name="PURE_BREAKOUT_CONTINUATION",
        setup_tier="TIER 1",
        score=85.0,
        reasons=["Clean breakout"],
        trade_levels=levels,
    )
    assert len(sent_messages) == 0
    assert not log_file.exists()

    # 2. Alpha setup should be allowed and dispatched
    dispatcher.dispatch_alert(
        candidate=candidate,
        setup_name="PRE_BREAKOUT_ACCUMULATION",
        setup_tier="TIER 1 (ALPHA SETUP)",
        score=90.0,
        reasons=["Ascending swing pivots"],
        trade_levels=levels,
    )
    assert len(sent_messages) == 1
    assert "PRE-BREAKOUT ALPHA ALERT" in sent_messages[0]["text"]
    assert "65.2% Win Rate | 2.36 Profit Factor" in sent_messages[0]["text"]
    assert log_file.exists()

    # 3. Test pause functionality
    dispatcher.is_paused = True
    dispatcher.dispatch_alert(
        candidate=candidate,
        setup_name="PRE_BREAKOUT_ACCUMULATION",
        setup_tier="TIER 1 (ALPHA SETUP)",
        score=90.0,
        reasons=["Ascending swing pivots"],
        trade_levels=levels,
    )
    assert len(sent_messages) == 1  # Still 1, muted when paused

    # 4. Test live execution notification
    dispatcher.is_paused = False
    exec_res = {
        "weex_live": True,
        "weex_symbol": "DOGE_USDT",
        "order_id": "998877",
        "native_tp_order_id": "tp123",
        "native_sl_order_id": "sl123",
    }
    dispatcher.notify_execution(exec_res, "DOGEUSDT", 0.15, levels)
    assert len(sent_messages) == 2
    assert "WEEX LIVE ORDER FILLED" in sent_messages[1]["text"]
    assert "DOGE_USDT" in sent_messages[1]["text"]


def test_interactive_telegram_bot_commands(tmp_path):
    import json
    from unittest.mock import MagicMock
    from src.live.telegram_bot import InteractiveTelegramBot
    from src.live.alerting import AlertDispatcher

    log_file = tmp_path / "bot_alerts.jsonl"
    # Seed historical alerts (one alpha, one non-alpha)
    alerts_data = [
        {"symbol": "XRPUSDT", "setup_name": "PURE_BREAKOUT_CONTINUATION", "timestamp": "2026-09-18 10:00:00 UTC", "score": 80, "close": 0.5},
        {"symbol": "SUIUSDT", "setup_name": "PRE_BREAKOUT_ACCUMULATION", "timestamp": "2026-09-18 10:05:00 UTC", "score": 92, "close": 1.5, "levels": {"entry_price": 1.5, "take_profit_1": 1.5525, "stop_loss": 1.4475}},
    ]
    with open(log_file, "w") as f:
        for a in alerts_data:
            f.write(json.dumps(a) + "\n")

    mock_scanner = MagicMock()
    mock_scanner.interval = "5m"
    mock_scanner.min_score = 70.0
    mock_scanner.alpha_only = True
    mock_scanner.dispatcher = AlertDispatcher(log_path=log_file, alpha_only=True)
    mock_scanner.paper_trader.open_positions = {}
    mock_scanner.paper_trader.get_summary.return_value = {
        "open_count": 0, "closed_count": 2, "win_rate": 100.0, "total_pnl_usdt": 7.0, "avg_return_pct": 3.5
    }

    bot = InteractiveTelegramBot(token="dummy", chat_id="12345", scanner_ref=mock_scanner)
    sent = []
    bot.send_message = lambda msg, reply_markup=None: sent.append(msg)

    # 1. /status command
    bot._handle_command("/status")
    assert any("Tier 1 Alpha Only" in s for s in sent)
    assert any("Alpha Setups Only" in s for s in sent)

    # 2. /pause & /resume synchronization
    bot._handle_command("/pause")
    assert bot.is_paused is True
    assert mock_scanner.dispatcher.is_paused is True

    bot._handle_command("/resume")
    assert bot.is_paused is False
    assert mock_scanner.dispatcher.is_paused is False

    # 3. /alerts command should only return the alpha setup
    sent.clear()
    bot._handle_command("/alerts")
    assert len(sent) == 1
    assert "SUIUSDT" in sent[0]
    assert "XRPUSDT" not in sent[0]  # Filtered out non-alpha setup
