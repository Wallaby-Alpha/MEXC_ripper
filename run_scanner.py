"""CLI entry point for Phase 2: Live MEXC Momentum Continuation Scanner, Telegram Bot & Execution."""
import argparse
import logging
import os
import sys
import time
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Load .env file
load_dotenv()

from config import DEFAULT_INTERVAL, DEFAULT_MIN_24H_TURNOVER_USDT
from src.live.scanner import LiveMomentumScanner
from src.live.alerting import AlertDispatcher
from src.live.paper_trader import PaperTrader
from src.live.telegram_bot import InteractiveTelegramBot
from src.execution.weex_executor import WeexExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Suppress excessive HTTP connection logs
logging.getLogger("httpx").setLevel(logging.WARNING)

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(description="MEXC Live Altcoin Momentum Continuation Scanner")
    parser.add_argument("--interval", type=str, default=DEFAULT_INTERVAL, help="Candle interval (default: 5m)")
    parser.add_argument("--poll-sec", type=int, default=60, help="Polling delay between cycles in seconds (default: 60)")
    parser.add_argument("--min-turnover", type=float, default=DEFAULT_MIN_24H_TURNOVER_USDT, help="Min 24h quote volume (default: $50,000)")
    parser.add_argument("--top-coins", type=int, default=40, help="Number of liquid altcoins to scan per cycle (default: 40)")
    parser.add_argument("--min-score", type=float, default=70.0, help="Minimum setup score to alert (default: 70.0)")
    parser.add_argument("--iterations", type=int, default=None, help="Number of scan cycles to run (default: infinite)")
    parser.add_argument("--dry-run", action="store_true", help="Execute single scan iteration and exit")
    parser.add_argument("--no-telegram", action="store_true", help="Disable interactive Telegram bot daemon")
    return parser.parse_args()


def display_open_positions_table(paper_trader: PaperTrader):
    """Renders a rich table of all currently open paper trades."""
    if not paper_trader.open_positions:
        return

    table = Table(title="Active Paper Positions (Trailing Breakeven & Multi-Target)", header_style="bold blue", border_style="blue")
    table.add_column("Symbol", style="bold cyan")
    table.add_column("Archetype", style="magenta")
    table.add_column("Entry Price", justify="right")
    table.add_column("Current Price", justify="right")
    table.add_column("Unrealized PnL", justify="right")
    table.add_column("Peak Run (MFE)", justify="right", style="bold green")
    table.add_column("Stop Loss", justify="right", style="bold red")
    table.add_column("Target (TP2)", justify="right", style="bold yellow")

    for sym, pos in paper_trader.open_positions.items():
        ret = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100.0
        peak = ((pos.highest_price - pos.entry_price) / pos.entry_price) * 100.0
        color = "bold green" if ret >= 0 else "bold red"

        table.add_row(
            sym,
            pos.setup_name,
            f"${pos.entry_price:.6f}",
            f"${pos.current_price:.6f}",
            f"[{color}]{ret:+.2f}%[/{color}]",
            f"+{peak:.2f}%",
            f"${pos.stop_loss:.6f}",
            f"${pos.take_profit_2:.6f} (+15%)",
        )

    console.print(table)


def main():
    args = parse_args()
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    weex_live = os.getenv("WEEX_LIVE_TRADING_ENABLED", "false").lower() == "true"

    exec_mode = "WEEX LIVE CAPITAL" if weex_live else "PAPER TRADING (Zero Live Capital Risk)"

    console.print(
        Panel.fit(
            f"[bold green]MEXC Live Momentum Continuation Scanner & Execution Daemon[/bold green]\n"
            f"Interval: [yellow]{args.interval}[/yellow] | Scan Batch: [cyan]{args.top_coins} liquid alts[/cyan] | Delay: [white]{args.poll_sec}s[/white]\n"
            f"Min Score: [bold cyan]{args.min_score}/100[/bold cyan] | Liquidity Floor: [magenta]${args.min_turnover:,.0f} USDT[/magenta]\n"
            f"Execution Mode: [bold yellow]{exec_mode}[/bold yellow] | Telegram Bot: [{'bold green}ENABLED' if tg_token and not args.no_telegram else 'dim red'}DISABLED{'/bold green' if tg_token and not args.no_telegram else '/dim red'}]",
            border_style="green",
        )
    )

    dispatcher = AlertDispatcher()
    paper_trader = PaperTrader()
    scanner = LiveMomentumScanner(
        dispatcher=dispatcher,
        paper_trader=paper_trader,
        interval=args.interval,
        min_24h_turnover=args.min_turnover,
        min_score=args.min_score,
    )

    # Initialize interactive Telegram Bot if credentials are configured
    tg_bot = None
    if tg_token and tg_chat_id and not args.no_telegram:
        tg_bot = InteractiveTelegramBot(
            token=tg_token,
            chat_id=tg_chat_id,
            scanner_ref=scanner,
        )
        tg_bot.start()

    max_iter = 1 if args.dry_run else args.iterations
    current_iter = 0

    try:
        while True:
            current_iter += 1
            console.print(f"\n[bold cyan]--- Scan Cycle #{current_iter} ---[/bold cyan]")
            alerts = scanner.poll_cycle(max_symbols=args.top_coins)

            if alerts:
                console.print(f"[bold green][OK] Cycle #{current_iter} found {len(alerts)} high-probability momentum setup(s)![/bold green]")
            else:
                console.print(f"[dim]Cycle #{current_iter} complete. No setups meeting score >= {args.min_score} this bar.[/dim]")

            # Display active paper trading positions if any are open
            display_open_positions_table(paper_trader)

            if max_iter is not None and current_iter >= max_iter:
                break

            console.print(f"[dim]Sleeping {args.poll_sec}s until next candle evaluation... (Ctrl+C to stop)[/dim]")
            time.sleep(args.poll_sec)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Scanner stopped by user.[/bold yellow]")
    finally:
        if tg_bot:
            tg_bot.stop()

    # Print Final Paper Trading Summary
    summary = paper_trader.get_summary()
    table = Table(title="Final Paper Trading Session Summary", header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold green")

    table.add_row("Open Paper Positions", str(summary["open_count"]))
    table.add_row("Closed Paper Trades", str(summary["closed_count"]))
    table.add_row("Win Rate (%)", f"{summary['win_rate']:.1f}%")
    table.add_row("Total Simulated PnL", f"${summary['total_pnl_usdt']:+.2f} USDT")
    table.add_row("Average Closed Trade Return", f"{summary['avg_return_pct']:+.2f}%")
    console.print(table)


if __name__ == "__main__":
    main()
