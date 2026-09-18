"""Alert dispatcher: Rich visual console formatting, JSONL audit logging, Telegram & Discord webhooks."""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import DATA_DIR

logger = logging.getLogger(__name__)
console = Console()


class AlertDispatcher:
    """Dispatches high-probability momentum continuation candidate alerts to console, JSONL, and webhooks."""

    def __init__(
        self,
        log_path: Optional[Path] = None,
        webhook_url: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        discord_webhook_url: Optional[str] = None,
    ):
        self.log_path = log_path or (DATA_DIR / "scanner_alerts.jsonl")
        self.webhook_url = webhook_url or os.getenv("ALERT_WEBHOOK_URL")
        self.telegram_bot_token = telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.discord_webhook_url = discord_webhook_url or os.getenv("DISCORD_WEBHOOK_URL")

    def dispatch_alert(
        self,
        candidate: Dict[str, Any],
        setup_name: str,
        setup_tier: str,
        score: float,
        reasons: List[str],
        trade_levels: Dict[str, float],
    ):
        """Format and broadcast candidate signal."""
        sym = candidate["symbol"]
        price = candidate["close"]
        rvol = candidate.get("rvol_20", 1.0)
        rsi = candidate.get("rsi_14", 50.0)
        cvd = candidate.get("cvd_rolling", 0.0)
        dt_str = datetime.utcfromtimestamp(candidate["timestamp_ms"] / 1000).strftime("%Y-%m-%d %H:%M:%S UTC")

        stop_loss = trade_levels.get("stop_loss", price * 0.94)
        tp1 = trade_levels.get("take_profit_1", price * 1.10)
        tp2 = trade_levels.get("take_profit_2", price * 1.15)
        tp3 = trade_levels.get("take_profit_3", price * 1.25)
        risk_pct = abs((stop_loss - price) / price) * 100.0
        reward_pct = ((tp2 - price) / price) * 100.0
        rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 2.5

        # 1. Console Rich Alert Card
        tier_color = "bold green" if "TIER 1" in setup_tier else "bold yellow"
        alert_title = f"[ALERT] MOMENTUM SETUP DETECTED: {sym} ({setup_tier})"

        table = Table(show_header=True, header_style="bold magenta", border_style="cyan")
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", style="bold white")
        table.add_column("Trade Execution Levels", style="bold yellow")

        table.add_row("Setup Archetype", f"[{tier_color}]{setup_name}[/{tier_color}]", f"Entry Price: [bold green]${price:.6f}[/bold green]")
        table.add_row("Setup Score", f"[bold cyan]{score:.1f} / 100[/bold cyan]", f"Stop Loss: [bold red]${stop_loss:.6f}[/bold red] (-{risk_pct:.1f}%)")
        table.add_row("RVOL (20-bar)", f"{rvol:.2f}x baseline", f"TP 1 (Scalp / BE): [green]${tp1:.6f}[/green] (+{((tp1-price)/price)*100:.1f}%)")
        table.add_row("Order Flow CVD", f"{cvd:+,.0f} delta", f"TP 2 (Target MFE): [bold green]${tp2:.6f}[/bold green] (+{reward_pct:.1f}%)")
        table.add_row("RSI (14)", f"{rsi:.1f}", f"TP 3 (Runner): [bold green]${tp3:.6f}[/bold green] (+{((tp3-price)/price)*100:.1f}%)")
        table.add_row("Risk / Reward", f"[bold green]1 : {rr_ratio:.1f}[/bold green]", f"MEXC URL: https://www.mexc.com/exchange/{sym}")

        console.print(Panel(table, title=alert_title, border_style="green", expand=False))
        console.print(f"[bold yellow]Preconditions Met:[/bold yellow] {' | '.join(reasons)}\n")

        # 2. Append to JSONL audit file
        payload = {
            "timestamp": dt_str,
            "timestamp_ms": candidate["timestamp_ms"],
            "symbol": sym,
            "setup_name": setup_name,
            "setup_tier": setup_tier,
            "score": score,
            "reasons": reasons,
            "levels": {
                "entry_price": price,
                "stop_loss": stop_loss,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "risk_reward_ratio": rr_ratio,
            },
            "features": {k: v for k, v in candidate.items() if isinstance(v, (int, float, str, bool))},
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as exc:
            logger.error("Failed writing alert to JSONL: %s", exc)

        # 3. Dispatch to Webhooks / Telegram / Discord
        self._send_external_notifications(sym, price, setup_name, setup_tier, score, reasons, trade_levels, rr_ratio)

    def _send_external_notifications(
        self, sym: str, price: float, setup: str, tier: str, score: float, reasons: List[str], levels: Dict[str, float], rr: float
    ):
        text_msg = (
            f"🚀 *MEXC MOMENTUM SETUP: {sym}*\n"
            f"*Setup*: {setup} ({tier})\n"
            f"*Score*: {score:.0f}/100 | *R:R*: 1:{rr:.1f}\n\n"
            f"💵 *Entry*: `${price:.6f}`\n"
            f"🛑 *Stop Loss*: `${levels.get('stop_loss', 0):.6f}`\n"
            f"🎯 *Target 1*: `${levels.get('take_profit_1', 0):.6f}` (+10%)\n"
            f"🎯 *Target 2*: `${levels.get('take_profit_2', 0):.6f}` (+15%)\n"
            f"🎯 *Target 3*: `${levels.get('take_profit_3', 0):.6f}` (+25%)\n\n"
            f"⚡ *Drivers*: {', '.join(reasons)}\n"
            f"🔗 [Trade on MEXC](https://www.mexc.com/exchange/{sym})"
        )

        # Telegram
        if self.telegram_bot_token and self.telegram_chat_id:
            try:
                tg_url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                httpx.post(tg_url, json={"chat_id": self.telegram_chat_id, "text": text_msg, "parse_mode": "Markdown"}, timeout=5.0)
            except Exception as exc:
                logger.warning("Telegram alert failed: %s", exc)

        # Discord
        if self.discord_webhook_url:
            try:
                discord_payload = {
                    "embeds": [{
                        "title": f"🚀 MEXC Momentum Setup: {sym}",
                        "description": f"**{setup}** ({tier})\nScore: **{score:.0f}/100**",
                        "color": 5763719,
                        "fields": [
                            {"name": "Entry Price", "value": f"${price:.6f}", "inline": True},
                            {"name": "Stop Loss", "value": f"${levels.get('stop_loss', 0):.6f}", "inline": True},
                            {"name": "Target (MFE)", "value": f"${levels.get('take_profit_2', 0):.6f} (+15%)", "inline": True},
                            {"name": "Preconditions", "value": " • ".join(reasons), "inline": False},
                        ],
                        "url": f"https://www.mexc.com/exchange/{sym}",
                    }]
                }
                httpx.post(self.discord_webhook_url, json=discord_payload, timeout=5.0)
            except Exception as exc:
                logger.warning("Discord alert failed: %s", exc)
