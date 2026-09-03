from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ForwardReturnStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class ForwardReturnRecord(BaseModel):
    """Tracks forward returns at +5m, +15m, +1h, +4h, and +24h after a signal."""
    signal_id: str
    symbol: str
    price_at_signal: float
    signal_timestamp_utc: str

    # Forward Prices
    price_5m: Optional[float] = None
    price_15m: Optional[float] = None
    price_1h: Optional[float] = None
    price_4h: Optional[float] = None
    price_24h: Optional[float] = None

    # Forward Returns (%)
    return_5m_pct: Optional[float] = None
    return_15m_pct: Optional[float] = None
    return_1h_pct: Optional[float] = None
    return_4h_pct: Optional[float] = None
    return_24h_pct: Optional[float] = None

    # Performance metrics within the 24h window
    max_runup_24h_pct: Optional[float] = None  # Max Favorable Excursion (MFE)
    max_drawdown_24h_pct: Optional[float] = None  # Max Adverse Excursion (MAE)

    # State
    status: ForwardReturnStatus = ForwardReturnStatus.PENDING
    last_evaluated_at: Optional[str] = None
