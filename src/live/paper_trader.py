"""Paper trading module: simulates fills, monitors open trades, trails stops to breakeven, and tracks forward PnL."""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    symbol: str
    entry_time_ms: int
    entry_price: float
    setup_name: str
    setup_tier: str
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    size_usdt: float = 1000.0
    current_price: float = field(init=False)
    highest_price: float = field(init=False)
    lowest_price: float = field(init=False)
    status: str = "OPEN"  # OPEN, CLOSED_TP1, CLOSED_TP2, CLOSED_TP3, CLOSED_SL, CLOSED_BE
    tp1_hit: bool = False
    exit_price: Optional[float] = None
    exit_time_ms: Optional[int] = None
    pnl_pct: float = 0.0
    pnl_usdt: float = 0.0

    def __post_init__(self):
        self.current_price = self.entry_price
        self.highest_price = self.entry_price
        self.lowest_price = self.entry_price


class PaperTrader:
    """Simulates paper entries with dynamic TP/SL and breakeven trailing."""

    def __init__(
        self,
        default_size_usdt: float = 1000.0,
    ):
        self.default_size_usdt = default_size_usdt
        self.open_positions: Dict[str, PaperPosition] = {}
        self.closed_positions: List[PaperPosition] = []

    def open_simulated_trade(
        self,
        symbol: str,
        entry_price: float,
        timestamp_ms: int,
        setup_name: str,
        setup_tier: str,
        trade_levels: Dict[str, float],
    ):
        """Opens a simulated paper trade with dynamic levels if not already in position."""
        if symbol in self.open_positions:
            return

        pos = PaperPosition(
            symbol=symbol,
            entry_time_ms=timestamp_ms,
            entry_price=entry_price,
            setup_name=setup_name,
            setup_tier=setup_tier,
            stop_loss=trade_levels.get("stop_loss", entry_price * 0.965),
            take_profit_1=trade_levels.get("take_profit_1", entry_price * 1.040),
            take_profit_2=trade_levels.get("take_profit_2", entry_price * 1.080),
            take_profit_3=trade_levels.get("take_profit_3", entry_price * 1.120),
            size_usdt=self.default_size_usdt,
        )
        self.open_positions[symbol] = pos
        logger.info(
            "[PAPER POSITION OPENED] %s @ $%.6f | SL: $%.6f | TP1: $%.6f (+4.0%%) | TP2: $%.6f ($%.0f USDT virtual)",
            symbol,
            entry_price,
            pos.stop_loss,
            pos.take_profit_1,
            pos.take_profit_2,
            self.default_size_usdt,
        )

    def update_price(self, symbol: str, current_price: float, timestamp_ms: int):
        """Updates open position, checks stops, trailing breakeven, targets, and 6h time stop."""
        if symbol not in self.open_positions:
            return

        pos = self.open_positions[symbol]
        pos.current_price = current_price
        pos.highest_price = max(pos.highest_price, current_price)
        pos.lowest_price = min(pos.lowest_price, current_price)

        # 1. 6-Hour Time Stop Invalidation (Kills stagnant post-pump trades)
        if (timestamp_ms - pos.entry_time_ms) >= 6 * 3600 * 1000:
            self._close_position(pos, current_price, timestamp_ms, "CLOSED_TIMEOUT (6H TIME STOP)")
            return

        # 2. If TP1 hit (+4.0%), trail stop loss to Breakeven (+0.2% fee coverage)
        if not pos.tp1_hit and current_price >= pos.take_profit_1:
            pos.tp1_hit = True
            pos.stop_loss = pos.entry_price * 1.002  # Cover fee / breakeven
            logger.info("[PAPER TRADE TP1 REACHED] %s @ $%.6f (+4.0%%) | Stop trailed to Breakeven", symbol, current_price)

        # 3. Check TP2 (+8.0% runner target)
        if current_price >= pos.take_profit_2:
            self._close_position(pos, current_price, timestamp_ms, "CLOSED_TP2 (+8.0% TARGET)")
            return

        # 4. Check Stop Loss (or Breakeven stop)
        if current_price <= pos.stop_loss:
            reason = "CLOSED_BE" if pos.tp1_hit else "CLOSED_SL"
            self._close_position(pos, current_price, timestamp_ms, reason)
            return

    def _close_position(self, pos: PaperPosition, exit_price: float, timestamp_ms: int, status: str):
        pos.status = status
        pos.exit_price = exit_price
        pos.exit_time_ms = timestamp_ms
        pos.pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
        pos.pnl_usdt = pos.size_usdt * pos.pnl_pct
        self.closed_positions.append(pos)
        del self.open_positions[pos.symbol]

        logger.info(
            "[PAPER POSITION CLOSED] %s | Reason: %s | PnL: %+.2f%% (%+.2f USDT)",
            pos.symbol,
            status,
            pos.pnl_pct * 100.0,
            pos.pnl_usdt,
        )

    def get_summary(self) -> Dict[str, Any]:
        """Returns cumulative performance summary of paper trades."""
        closed_cnt = len(self.closed_positions)
        if closed_cnt == 0:
            return {
                "open_count": len(self.open_positions),
                "closed_count": 0,
                "win_rate": 0.0,
                "total_pnl_usdt": 0.0,
                "avg_return_pct": 0.0,
            }

        wins = sum(1 for p in self.closed_positions if p.pnl_usdt > 0)
        total_pnl = sum(p.pnl_usdt for p in self.closed_positions)
        avg_ret = sum(p.pnl_pct for p in self.closed_positions) / closed_cnt

        return {
            "open_count": len(self.open_positions),
            "closed_count": closed_cnt,
            "win_rate": (wins / closed_cnt) * 100.0,
            "total_pnl_usdt": total_pnl,
            "avg_return_pct": avg_ret * 100.0,
        }

    def get_open_positions(self) -> Dict[str, "PaperPosition"]:
        """Returns currently active open paper positions."""
        return self.open_positions
