"""Global configuration for MEXC Altcoin Momentum Continuation Scanner."""
import os
from pathlib import Path
from dataclasses import dataclass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REPORTS_DIR = BASE_DIR / "reports"

# Ensure directories exist
for p in [RAW_DATA_DIR, PROCESSED_DATA_DIR, REPORTS_DIR]:
    p.mkdir(parents=True, exist_ok=True)

# Default Backtest Parameters
DEFAULT_START_TIME = "2026-09-01T00:00:00Z"
DEFAULT_END_TIME = "2026-09-10T00:00:00Z"
DEFAULT_INTERVAL = "5m"  # 5 minutes

# API Endpoints
MEXC_SPOT_BASE_URL = "https://api.mexc.com"
MEXC_CONTRACT_BASE_URL = "https://contract.mexc.com"

# Liquidity floor for Point-in-Time universe filtering (24h quote volume in USDT)
DEFAULT_MIN_24H_TURNOVER_USDT = 50_000.0  # $50,000 floor for low/mid caps

# Pre-filter thresholds to control compute costs
PREFILTER_MIN_RVOL_20 = 2.0         # 2.0x 20-bar average volume
PREFILTER_MIN_1H_RETURN_PCT = 3.0   # 3% return over last 12 bars (1 hour on 5m)

# Forward evaluation horizons (in minutes, assuming 5m bars)
FORWARD_HORIZONS = {
    "4h": 48,    # 48 bars * 5m = 4 hours
    "12h": 144,  # 144 bars * 5m = 12 hours
    "24h": 288,  # 288 bars * 5m = 24 hours
    "48h": 576,  # 576 bars * 5m = 48 hours
}

# Target thresholds for continuation labeling
TARGET_MFE_THRESHOLDS = [0.10, 0.25, 0.50]  # +10%, +25%, +50%
CONTINUATION_CRITERIA = {
    "target_gain": 0.15,    # +15% within 24h
    "max_drawdown": 0.08,   # <= 8% drawdown before hitting target
}

# Rate limit settings
MEXC_RATE_LIMIT_WEIGHT_PER_MIN = 1200
DEFAULT_REQUEST_TIMEOUT = 15.0
MAX_RETRIES = 4
BACKOFF_FACTOR = 1.5

# Database path
SQLITE_DB_PATH = RAW_DATA_DIR / "mexc_market_data.sqlite"
