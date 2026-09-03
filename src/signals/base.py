from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import pandas as pd
from src.models.signal import SignalResult, SignalType
from src.models.universe import PumpingCoin


class BaseSignalDetector(ABC):
    """Abstract base class for all pluggable entry heuristic detectors."""

    def __init__(self, signal_type: SignalType, config: Dict[str, Any]):
        self.signal_type = signal_type
        self.config = config
        self.enabled: bool = config.get("enabled", True)

    @abstractmethod
    def evaluate(
        self,
        coin: PumpingCoin,
        klines_1h: Optional[pd.DataFrame],
        klines_15m: Optional[pd.DataFrame],
        klines_5m: Optional[pd.DataFrame],
    ) -> Optional[SignalResult]:
        """Evaluate the heuristic against market candles.
        Returns SignalResult if triggered, None otherwise."""
        pass
