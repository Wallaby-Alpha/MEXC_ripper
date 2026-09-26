"""Paper trading executor implementation of BaseExecutor."""
import time
from typing import Dict, Any, Optional
from src.execution.base_executor import BaseExecutor
from src.live.paper_trader import PaperTrader


class PaperExecutor(BaseExecutor):
    """Execution engine for virtual paper trades."""

    def __init__(self, paper_trader: Optional[PaperTrader] = None, default_size_usdt: float = 1000.0):
        self.trader = paper_trader or PaperTrader(default_size_usdt=default_size_usdt)

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size_usdt: float,
        stop_loss: float,
        take_profit: float,
        setup_name: str,
        setup_tier: str,
    ) -> Dict[str, Any]:
        timestamp_ms = int(time.time() * 1000)
        levels = {
            "stop_loss": stop_loss,
            "take_profit_1": entry_price * 1.040,
            "take_profit_2": take_profit if (take_profit and take_profit > (entry_price * 1.040)) else (entry_price * 1.080),
            "take_profit_3": entry_price * 1.120,
        }
        self.trader.open_simulated_trade(
            symbol=symbol,
            entry_price=entry_price,
            timestamp_ms=timestamp_ms,
            setup_name=setup_name,
            setup_tier=setup_tier,
            trade_levels=levels,
        )
        return {
            "status": "FILLED_SIMULATED",
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "size_usdt": size_usdt,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

    def update_price(self, symbol: str, current_price: float, timestamp_ms: int):
        self.trader.update_price(symbol, current_price, timestamp_ms)

    def close_position(self, symbol: str, reason: str = "MANUAL_CLOSE") -> Optional[Dict[str, Any]]:
        if symbol in self.trader.open_positions:
            pos = self.trader.open_positions[symbol]
            now_ms = int(time.time() * 1000)
            self.trader._close_position(pos, pos.current_price, now_ms, reason)
            return {"status": "CLOSED", "symbol": symbol, "exit_price": pos.current_price}
        return None

    def get_open_positions(self) -> Dict[str, Any]:
        return self.trader.open_positions

    def get_performance_summary(self) -> Dict[str, Any]:
        return self.trader.get_summary()
