from src.models.signal import SIGNAL_METADATA, SignalResult, SignalType
from src.models.universe import PumpingCoin


def format_volume(val: float) -> str:
    """Format large currency volumes into human readable strings ($350.5K, $2.4M)."""
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    elif val >= 1_000:
        return f"${val / 1_000:.1f}K"
    else:
        return f"${val:.2f}"


def format_price(val: float) -> str:
    """Format prices with appropriate decimal precision."""
    if val >= 100:
        return f"{val:.2f}"
    elif val >= 1:
        return f"{val:.4f}"
    elif val >= 0.01:
        return f"{val:.4f}"
    elif val >= 0.0001:
        return f"{val:.6f}"
    else:
        return f"{val:.8f}"



def format_telegram_alert(signal: SignalResult, coin: PumpingCoin) -> str:
    """Format a signal firing into the standardized Telegram alert message format."""
    meta = SIGNAL_METADATA.get(
        signal.signal_type,
        {"tag": f"[{signal.signal_type.value}] 🎯 SIGNAL", "name": "Signal", "emoji": "🎯"},
    )
    tag_header = meta["tag"]
    symbol = signal.symbol
    price_str = format_price(signal.price_at_signal)
    change_1h_str = f"+{coin.price_change_1h_pct:.2f}%" if coin.price_change_1h_pct >= 0 else f"{coin.price_change_1h_pct:.2f}%"
    change_4h_str = f"+{coin.price_change_4h_pct:.2f}%" if coin.price_change_4h_pct >= 0 else f"{coin.price_change_4h_pct:.2f}%"
    vol_surge_str = f"{coin.volume_surge_ratio:.1f}x"
    vol_24h_str = format_volume(coin.quote_volume_24h)
    time_utc_str = signal.timestamp_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

    message = (
        f"<b>{tag_header} — {symbol}</b>\n"
        f"Price: ${price_str} ({change_1h_str} 1h / {change_4h_str} 4h)\n"
        f"Reasoning: {signal.reasoning}\n"
        f"Vol surge: {vol_surge_str} | 24h Vol: {vol_24h_str}\n"
        f"Time: {time_utc_str}\n"
        f"Signal ID: <code>{signal.signal_id}</code>"
    )
    return message
