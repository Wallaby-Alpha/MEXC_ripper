from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class UniverseEventType(str, Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"


class PumpingCoin(BaseModel):
    """Represents a coin currently in the pumping universe."""
    symbol: str
    price: float
    price_change_1h_pct: float
    price_change_4h_pct: float
    volume_surge_ratio: float
    quote_volume_24h: float
    entered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trigger_reason: str

    def to_context_dict(self) -> Dict[str, Any]:
        return {
            "price": self.price,
            "change_1h_pct": self.price_change_1h_pct,
            "change_4h_pct": self.price_change_4h_pct,
            "volume_surge_ratio": self.volume_surge_ratio,
            "quote_volume_24h": self.quote_volume_24h,
            "entered_at": self.entered_at.isoformat(),
        }


class PumpingUniverseEvent(BaseModel):
    """Persistent event logged whenever a coin enters or exits the pumping universe."""
    id: Optional[int] = None
    symbol: str
    event_type: UniverseEventType
    timestamp_utc: str
    price: float
    price_change_1h_pct: float
    price_change_4h_pct: float
    volume_surge_ratio: float
    quote_volume_24h: float
    reason: str
    metrics_json: Optional[str] = None
