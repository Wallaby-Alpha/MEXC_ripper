"""Abstract base interface for execution backends (paper trading, WEEX, etc.)."""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseExecutor(ABC):
    """Abstract trading execution interface for routing scanner setups to orders."""

    @abstractmethod
    def open_position(
        self,
        symbol: str,
        side: str,  # 'BUY' / 'LONG'
        entry_price: float,
        size_usdt: float,
        stop_loss: float,
        take_profit: float,
        setup_name: str,
        setup_tier: str,
    ) -> Dict[str, Any]:
        """Opens a position or simulated trade with bracket stop-loss and take-profit."""
        pass

    @abstractmethod
    def update_price(self, symbol: str, current_price: float, timestamp_ms: int):
        """Notifies executor of price update for position monitoring / trailing stops."""
        pass

    @abstractmethod
    def close_position(self, symbol: str, reason: str = "MANUAL_CLOSE") -> Optional[Dict[str, Any]]:
        """Closes an open position."""
        pass

    @abstractmethod
    def get_open_positions(self) -> Dict[str, Any]:
        """Returns map of active open positions."""
        pass

    @abstractmethod
    def get_performance_summary(self) -> Dict[str, Any]:
        """Returns performance metrics: win rate, total PnL, open/closed counts."""
        pass
