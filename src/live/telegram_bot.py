"""Interactive Telegram Bot service for real-time monitoring and control of the momentum scanner."""
import time
import json
import logging
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)


class InteractiveTelegramBot:
    """Long-polling Telegram Bot daemon that responds to commands and broadcasts alerts."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        scanner_ref: Any,
        poll_timeout: int = 20,
    ):
        self.token = token
        self.chat_id = chat_id
        self.scanner = scanner_ref
        self.poll_timeout = poll_timeout
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.client = httpx.Client(timeout=float(poll_timeout + 10))
        self.last_update_id = 0
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.start_time = time.time()
        self.is_paused = False

    def start(self):
        """Starts the interactive bot listener in a background daemon thread."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram Bot token or chat_id missing. Interactive bot disabled.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._polling_loop, daemon=True, name="TelegramBotThread")
        self.thread.start()
        logger.info("Interactive Telegram Bot started successfully.")
        self.send_message(
            "🤖 *MEXC Momentum Scanner Bot Online (3R EDITION)!*\n"
            "🎯 *Strategy Filter*: Tier 1 Alpha Only (`PRE_BREAKOUT_ACCUMULATION`)\n"
            "📊 *Target Structure*: `3R Target (+10.5%) | 1.25R BE Trigger (+4.38%)`\n"
            "🎯 *Primary Target (3R)*: `+10.5% (+105% at 10x)` | 🛑 *Stop Loss (1R)*: `-3.5%`\n\n"
            "Send `/help` for available commands."
        )

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        self.client.close()

    def send_message(self, text: str, reply_markup: Optional[Dict[str, Any]] = None):
        """Sends a markdown-formatted message to the authorized chat."""
        try:
            payload: Dict[str, Any] = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            res = self.client.post(f"{self.base_url}/sendMessage", json=payload, timeout=8.0)
            if res.status_code != 200:
                logger.warning("Telegram send_message failed (%d: %s). Retrying as plain text...", res.status_code, res.text)
                payload.pop("parse_mode", None)
                res2 = self.client.post(f"{self.base_url}/sendMessage", json=payload, timeout=8.0)
                if res2.status_code == 200:
                    logger.info("Telegram message delivered successfully as plain text.")
                else:
                    logger.error("Telegram plain text retry failed (%d: %s)", res2.status_code, res2.text)
            else:
                logger.info("Telegram message delivered successfully.")
        except Exception as exc:
            logger.error("Failed sending Telegram message: %s", exc)

    def _polling_loop(self):
        """Long-polling loop for incoming updates from Telegram."""
        while self.running:
            try:
                params = {
                    "offset": self.last_update_id + 1,
                    "timeout": self.poll_timeout,
                    "allowed_updates": ["message"],
                }
                res = self.client.get(f"{self.base_url}/getUpdates", params=params)
                if res.status_code != 200:
                    if res.status_code == 409:
                        logger.error("Telegram 409 Conflict: Another bot instance is polling this token! Retrying in 15s...")
                        time.sleep(15.0)
                    else:
                        logger.warning("Telegram getUpdates returned %d: %s", res.status_code, res.text)
                        time.sleep(3.0)
                    continue

                data = res.json()
                for update in data.get("result", []):
                    self.last_update_id = update["update_id"]
                    msg = update.get("message")
                    if not msg or "text" not in msg:
                        continue

                    # Security check: verify incoming chat ID matches authorized chat
                    sender_chat_id = str(msg.get("chat", {}).get("id", ""))
                    if sender_chat_id != str(self.chat_id):
                        logger.warning("Unauthorized access attempt from chat_id %s", sender_chat_id)
                        continue

                    self._handle_command(msg["text"].strip())

            except Exception as exc:
                logger.debug("Telegram polling error: %s", exc)
                time.sleep(2.0)

    def _handle_command(self, text: str):
        """Routes slash commands."""
        cmd = text.split()[0].lower()

        if cmd in ("/start", "/help"):
            help_text = (
                "🚀 *MEXC Momentum Continuation Scanner Bot*\n\n"
                "*Available Commands:*\n"
                "📊 `/status` — System health, uptime & monitored coins\n"
                "⚡ `/weex` — Live WEEX account balance, connection & positions\n"
                "📈 `/positions` — View active open paper trades & PnL\n"
                "🏆 `/stats` — Win rate & cumulative performance\n"
                "🚨 `/alerts` — Recent triggered setup signals\n"
                "⏸ `/pause` — Mute live signal alerts\n"
                "▶️ `/resume` — Unmute live signal alerts"
            )
            self.send_message(help_text)

        elif cmd == "/weex":
            executor = getattr(self.scanner, "executor", None)
            if not executor:
                self.send_message("❌ No executor attached to this scanner instance.")
                return

            if not getattr(executor, "live_enabled", False):
                self.send_message("📝 *WEEX Status*: Bot is running in **DRY-RUN / PAPER MODE** (live capital execution is disabled).")
                return

            ok, msg = executor.verify_connection()
            if not ok:
                self.send_message(f"🚨 *WEEX API Error*: {msg}\nPlease check your WEEX API credentials in `.env`.")
                return

            live_pos = executor.get_open_positions()
            pos_count = len(live_pos) if isinstance(live_pos, (dict, list)) else 0
            lines = [
                "⚡ *WEEX Live Exchange Status (3R Bot)*",
                "",
                f"• *Connection*: 🟢 Active & Authenticated",
                f"• *{msg}*",
                f"• *Live Open Positions on WEEX*: `{pos_count} / 4`",
            ]
            if isinstance(live_pos, dict) and live_pos:
                lines.append("\n*Open Contracts on WEEX:*")
                for s, p in live_pos.items():
                    sz = p.get("total") or p.get("size") or p.get("holdAmount") or "N/A"
                    lines.append(f"  • `{s}`: size `{sz}`")
            self.send_message("\n".join(lines))

        elif cmd == "/status":
            uptime_min = int((time.time() - self.start_time) / 60)
            is_alpha_only = getattr(self.scanner, "alpha_only", True)
            try:
                margin_val = float(getattr(self.scanner, "trade_size_usdt", 1.0))
            except (TypeError, ValueError):
                margin_val = 1.0
            strat_desc = "🌟 *Tier 1 Alpha Only* (`PRE_BREAKOUT_ACCUMULATION`)" if is_alpha_only else "🌐 *All Setups*"
            exec_mode = f"⚡ *WEEX Live* (10x Isolated, ${margin_val:.2f} Margin, Native TP/SL)" if (getattr(self.scanner, "executor", None) and getattr(self.scanner.executor, "live_enabled", False)) else "📝 *Paper Trading* (Zero Risk)"
            regime = getattr(self.scanner, "current_regime", None)
            regime_line = ""
            if regime and hasattr(regime, "regime"):
                try:
                    regime_name = str(regime.regime)
                    regime_icon = "🟢" if regime_name == "BULLISH" else ("🟡" if regime_name == "CAUTION_PULLBACK" else "🔴")
                    p_val = float(getattr(regime, "btc_price", 0.0))
                    chg_val = float(getattr(regime, "btc_1h_change_pct", 0.0))
                    score_val = float(getattr(regime, "effective_min_score", 80.0))
                    regime_line = f"• *Market Regime*: {regime_icon} `{regime_name}` (BTC: `${p_val:,.0f}` | 1h: `{chg_val:+.2f}%` | Min Score: `{score_val:.0f}`)\n"
                except Exception:
                    regime_line = ""

            status_text = (
                "⚡ *Scanner Operational Status (3R Edition)*\n\n"
                f"• *Status*: {'⏸ Paused' if self.is_paused else '🟢 Active & Scanning'}\n"
                f"{regime_line}"
                f"• *Strategy Filter*: {strat_desc}\n"
                f"• *Telegram Filter*: 🔒 `Alpha Setups Only (65.2% WR, 2.36 PF)`\n"
                f"• *Execution*: {exec_mode}\n"
                f"• *Targets*: 🎯 `TP +10.5% (3R Target | 100% Exit)` | 🛡️ `BE Trigger +4.38% (1.25R)` | 🛑 `SL -3.5% (1R)`\n"
                f"• *Interval*: `{self.scanner.interval}`\n"
                f"• *Uptime*: `{uptime_min} minutes`\n"
                f"• *Open Trades*: `{len(self.scanner.paper_trader.open_positions)}`\n"
                f"• *Min Score Threshold*: `{self.scanner.min_score}/100`"
            )
            self.send_message(status_text)

        elif cmd == "/positions":
            open_pos = self.scanner.paper_trader.open_positions
            if not open_pos:
                self.send_message("💤 *No Active Positions*\nCurrently monitoring market for fresh Pre-Breakout setups.")
                return

            lines = ["📈 *Active Paper Positions:*", ""]
            for sym, pos in open_pos.items():
                ret = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100.0
                peak = ((pos.highest_price - pos.entry_price) / pos.entry_price) * 100.0
                pnl_emoji = "🟢" if ret >= 0 else "🔴"

                be_str = "TRAILED TO BE (+0.2%)" if getattr(pos, "be_triggered", False) else f"${getattr(pos, 'be_trigger', 0.0):.6f} (+4.38%)"
                lines.append(
                    f"{pnl_emoji} *{sym}* ({pos.setup_name})\n"
                    f"  • Entry: `${pos.entry_price:.6f}`\n"
                    f"  • Current: `${pos.current_price:.6f}` (*{ret:+.2f}%*)\n"
                    f"  • Peak Run (MFE): `+{peak:.2f}%`\n"
                    f"  • Stop Loss (1R): `${pos.stop_loss:.6f}` (-3.5%)\n"
                    f"  • BE Trigger (1.25R): `{be_str}`\n"
                    f"  • Take Profit (3R Target): `${pos.take_profit_1:.6f}` (+10.5% | 100% Exit)\n"
                    f"  • Risk / Reward: `1 : 3.0`\n"
                )
            self.send_message("\n".join(lines))

        elif cmd == "/stats":
            summary = self.scanner.paper_trader.get_summary()
            stats_text = (
                "🏆 *Trading Performance Summary*\n\n"
                f"• *Open Positions*: `{summary['open_count']}`\n"
                f"• *Closed Trades*: `{summary['closed_count']}`\n"
                f"• *Win Rate*: `*{summary['win_rate']:.1f}%*`\n"
                f"• *Total Simulated PnL*: `*{summary['total_pnl_usdt']:+.2f} USDT*`\n"
                f"• *Avg Closed Trade Return*: `{summary['avg_return_pct']:+.2f}%`"
            )
            self.send_message(stats_text)

        elif cmd == "/alerts":
            alerts_path = self.scanner.dispatcher.log_path
            if not alerts_path.exists():
                self.send_message("No historical alerts logged yet.")
                return

            try:
                with open(alerts_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                parsed = [json.loads(line) for line in lines if line.strip()]
                # If alpha_only is active, strictly filter for PRE_BREAKOUT_ACCUMULATION
                if getattr(self.scanner, "alpha_only", True):
                    parsed = [a for a in parsed if a.get("setup_name") == "PRE_BREAKOUT_ACCUMULATION"]

                recent = parsed[-5:]
                if not recent:
                    self.send_message("💤 No Pre-Breakout Alpha alerts recorded yet.")
                    return

                out = ["🚨 *Last 5 Triggered Pre-Breakout Setups (3R Strategy):*", ""]
                for a in reversed(recent):
                    lvl = a.get("levels", {})
                    tp_val = lvl.get("take_profit_1") or lvl.get("take_profit", 0)
                    out.append(
                        f"• *{a['symbol']}* ({a.get('setup_tier', 'TIER 1 (ALPHA SETUP)')})\n"
                        f"  Time: `{a['timestamp']}` | Score: `{a['score']:.0f}/100`\n"
                        f"  Price: `${lvl.get('entry_price', a.get('close', 0)):.6f}`\n"
                        f"  🎯 Take Profit (3R): `${tp_val:.6f}` (+10.5% | 100% Exit)\n"
                        f"  🛡️ BE Trigger (1.25R): `${lvl.get('be_trigger', 0):.6f}` (+4.38%)\n"
                        f"  🛑 Stop Loss (1R): `${lvl.get('stop_loss', 0):.6f}` (-3.5% | R:R 1:3.0)\n"
                    )
                self.send_message("\n".join(out))
            except Exception as exc:
                self.send_message(f"Error reading alerts: {exc}")

        elif cmd == "/pause":
            self.is_paused = True
            if hasattr(self.scanner, "dispatcher"):
                self.scanner.dispatcher.is_paused = True
            self.send_message("⏸ *Alert notifications paused.* The scanner continues tracking positions silently.")

        elif cmd == "/resume":
            self.is_paused = False
            if hasattr(self.scanner, "dispatcher"):
                self.scanner.dispatcher.is_paused = False
            self.send_message("▶️ *Alert notifications resumed.*")

        else:
            self.send_message("❓ Unknown command. Type `/help` for list of commands.")
