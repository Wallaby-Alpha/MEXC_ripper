import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env file
load_dotenv()


class AppConfig(BaseModel):
    name: str = "mexc-momentum-scanner"
    version: str = "1.0.0"
    db_path: str = "data/scanner_data.db"
    log_dir: str = "logs"


class ScreeningConfig(BaseModel):
    poll_interval_seconds: int = 60
    min_price_change_1h_pct: float = 3.0
    min_price_change_4h_pct: float = 6.0
    min_quote_volume_24h_usd: float = 200000.0
    volume_surge_multiplier: float = 2.5
    quote_currency: str = "USDT"
    exclude_patterns: List[str] = Field(
        default_factory=lambda: ["3L", "3S", "5L", "5S", "DOWN", "UP", "BEAR", "BULL"]
    )
    stablecoins: List[str] = Field(
        default_factory=lambda: [
            "USDC", "USDT", "BUSD", "TUSD", "DAI", "FDUSD", "EUR", "TRY", "USDD", "PYUSD", "USDP"
        ]
    )


class MexcConfig(BaseModel):
    base_url: str = "https://api.mexc.com"
    timeout_seconds: int = 10
    kline_limit_1h: int = 60
    kline_limit_15m: int = 80
    kline_limit_5m: int = 100
    max_concurrent_requests: int = 12
    request_delay_ms: int = 50
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    rate_limit_msgs_per_second: float = 20.0
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    dry_run: bool = False


class ForwardReturnsConfig(BaseModel):
    enabled: bool = True
    check_interval_seconds: int = 60
    intervals_minutes: List[int] = Field(default_factory=lambda: [5, 15, 60, 240, 1440])
    batch_size: int = 50


class SignalModuleConfig(BaseModel):
    enabled: bool = True
    params: Dict[str, Any] = Field(default_factory=dict)


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    screening: ScreeningConfig = Field(default_factory=ScreeningConfig)
    mexc: MexcConfig = Field(default_factory=MexcConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    signals: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    forward_returns: ForwardReturnsConfig = Field(default_factory=ForwardReturnsConfig)


def load_config(config_path: str = "config.yaml") -> Config:
    """Load configuration from YAML file and apply environment variable overrides."""
    data: Dict[str, Any] = {}
    path = Path(config_path)

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    config = Config(**data)

    # Environment variable overrides
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_token:
        config.telegram.bot_token = bot_token

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        config.telegram.chat_id = chat_id

    dry_run_env = os.getenv("DRY_RUN")
    if dry_run_env is not None:
        config.telegram.dry_run = dry_run_env.lower() in ("1", "true", "yes")

    mexc_key = os.getenv("MEXC_API_KEY")
    if mexc_key:
        config.mexc.api_key = mexc_key

    mexc_secret = os.getenv("MEXC_API_SECRET")
    if mexc_secret:
        config.mexc.api_secret = mexc_secret

    return config
