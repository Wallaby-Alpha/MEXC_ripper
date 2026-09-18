import json
from eval_colab_backtester import _parse_json_or_jsonl, _parse_telegram_messages

def test_telegram_export_parsing():
    sample_telegram_export = {
        "name": "MEXC Ripper",
        "type": "bot_chat",
        "id": 8885892475,
        "messages": [
            {
                "id": 133321,
                "type": "message",
                "date": "2026-09-17T22:35:19",
                "date_unixtime": "1789698919",
                "from": "Till",
                "from_id": "user6710861096",
                "text": [{"type": "bot_command", "text": "/start"}],
            },
            {
                "id": 133322,
                "type": "message",
                "date": "2026-09-17T22:38:33",
                "date_unixtime": "1789699113",
                "from": "MEXC Ripper",
                "from_id": "user8885892475",
                "text": [
                    "🤖 ",
                    {"type": "bold", "text": "MEXC Momentum Scanner Bot Online!"},
                    "\nSend ",
                    {"type": "code", "text": "/help"},
                ],
            },
            {
                "id": 133323,
                "type": "message",
                "date": "2026-09-17T22:40:00",
                "date_unixtime": "1789699200",
                "from": "MEXC Ripper",
                "from_id": "user8885892475",
                "text": [
                    {"type": "bold", "text": "[BREAKOUT_15M] 🎯 SIGNAL — ENAUSDT"},
                    "\nPrice: $0.6540 (+8.20% 1h / +18.40% 4h)\nReasoning: Consolidation breakout\nVol surge: 3.5x | 24h Vol: $4.20M\nTime: 2026-09-17 22:40:00 UTC\nSignal ID: sig_123",
                ],
            },
            {
                "id": 133324,
                "type": "message",
                "date": "2026-09-17T22:45:00",
                "date_unixtime": "1789699500",
                "from": "MEXC Ripper",
                "from_id": "user8885892475",
                "text": "🚀 MEXC MOMENTUM SETUP: SUIUSDT\nSetup: PULLBACK_CONTINUATION\nEntry: $1.8500\nStop Loss: $1.7482 (-5.5%)\nTarget 1: $2.0165 (+9.0%)\nTarget 2: $2.1275 (+15.0%)\nTarget 3: $2.3125 (+25.0%)",
            },
        ],
    }

    alerts = _parse_json_or_jsonl(json.dumps(sample_telegram_export))
    assert len(alerts) == 2

    # ENA alert
    ena = alerts[0]
    assert ena["symbol"] == "ENAUSDT"
    assert ena["setup_name"] == "BREAKOUT_15M"
    assert ena["entry_price"] == 0.6540
    assert ena["timestamp_ms"] == 1789699200000

    # SUI alert
    sui = alerts[1]
    assert sui["symbol"] == "SUIUSDT"
    assert sui["setup_name"] == "PULLBACK_CONTINUATION"
    assert sui["entry_price"] == 1.8500
    assert sui["stop_loss"] == 1.7482
    assert sui["take_profit_1"] == 2.0165
    assert sui["take_profit_2"] == 2.1275
    assert sui["take_profit_3"] == 2.3125
    assert sui["timestamp_ms"] == 1789699500000
    print("test_telegram_export_parsing passed successfully!")


if __name__ == "__main__":
    test_telegram_export_parsing()
