import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SignalType(str, Enum):
    A = "A"  # HTF trend + LTF pullback reclaim
    B = "B"  # Breakout + retest of prior resistance
    C = "C"  # RSI reset in confirmed uptrend
    D = "D"  # RSI momentum extension
    E = "E"  # VWAP reclaim
    F = "F"  # Volume spike / relative volume surge
    G = "G"  # Support / prior-swing-low bounce
    H = "H"  # Bollinger Band squeeze + breakout
    I = "I"  # MACD bullish cross in uptrend
    J = "J"  # Moving average stack alignment
    K = "K"  # Supertrend bullish flip (Bonus)
    L = "L"  # Stochastic RSI oversold cross (Bonus)


SIGNAL_METADATA: Dict[SignalType, Dict[str, str]] = {
    SignalType.A: {
        "tag": "[A] 🔁 PULLBACK RECLAIM",
        "name": "HTF Trend + LTF Pullback Reclaim",
        "emoji": "🔁",
    },
    SignalType.B: {
        "tag": "[B] 🎯 BREAKOUT RETEST",
        "name": "Breakout + Retest Prior Resistance",
        "emoji": "🎯",
    },
    SignalType.C: {
        "tag": "[C] 📉 RSI RESET",
        "name": "RSI Reset in Confirmed Uptrend",
        "emoji": "📉",
    },
    SignalType.D: {
        "tag": "[D] 🚀 RSI MOMENTUM",
        "name": "RSI Momentum Extension (Chase)",
        "emoji": "🚀",
    },
    SignalType.E: {
        "tag": "[E] 📊 VWAP RECLAIM",
        "name": "VWAP Dip & Reclaim",
        "emoji": "📊",
    },
    SignalType.F: {
        "tag": "[F] 📢 VOLUME SPIKE",
        "name": "Volume Spike / Relative Surge",
        "emoji": "📢",
    },
    SignalType.G: {
        "tag": "[G] 🛟 SUPPORT BOUNCE",
        "name": "Support / Swing Low Bounce",
        "emoji": "🛟",
    },
    SignalType.H: {
        "tag": "[H] 🎈 BB SQUEEZE BREAK",
        "name": "Bollinger Band Squeeze & Breakout",
        "emoji": "🎈",
    },
    SignalType.I: {
        "tag": "[I] ⚡ MACD CROSS",
        "name": "MACD Bullish Cross in Uptrend",
        "emoji": "⚡",
    },
    SignalType.J: {
        "tag": "[J] 📐 EMA STACK",
        "name": "EMA Stack Alignment (9>21>50)",
        "emoji": "📐",
    },
    SignalType.K: {
        "tag": "[K] 🟢 SUPERTREND FLIP",
        "name": "Supertrend Bullish Flip",
        "emoji": "🟢",
    },
    SignalType.L: {
        "tag": "[L] 🔀 STOCH RSI CROSS",
        "name": "Stochastic RSI Oversold Bullish Cross",
        "emoji": "🔀",
    },
}


class IndicatorSnapshot(BaseModel):
    """Container for raw numeric indicator readings."""
    data: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.data


class SignalResult(BaseModel):
    """Output produced when a detector module fires."""
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_type: SignalType
    symbol: str
    price_at_signal: float
    candle_timestamp: int  # Exact epoch ms of the trigger candle close to prevent duplicate candle firing
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reasoning: str
    indicator_snapshot: Dict[str, Any] = Field(default_factory=dict)
    timeframe_used: str = "5m"


class SignalLogRecord(BaseModel):
    """Complete persistent log record for a signal firing."""
    signal_id: str
    signal_type: str
    symbol: str
    timestamp_utc: str
    candle_timestamp: int
    price_at_signal: float
    price_change_1h_pct: float
    price_change_4h_pct: float
    volume_surge_ratio: float
    quote_volume_24h: float
    indicator_snapshot_json: str
    reasoning: str
    telegram_sent: bool = False
    telegram_sent_at: Optional[str] = None
    error: Optional[str] = None
