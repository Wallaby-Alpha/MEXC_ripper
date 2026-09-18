"""WEEX execution bridge implementing BaseExecutor with strict live-trading safety gate."""
import os
import logging
from typing import Dict, Any, Optional
from src.execution.base_executor import BaseExecutor
from src.execution.weex_client import WeexClient
from src.execution.paper_executor import PaperExecutor

logger = logging.getLogger(__name__)


class WeexExecutor(BaseExecutor):
    """Bridge for executing trades on WEEX exchange with safe dry-run fallback."""

    def __init__(
        self,
        weex_client: Optional[WeexClient] = None,
        paper_fallback: Optional[PaperExecutor] = None,
        live_enabled: Optional[bool] = None,
    ):
        self.client = weex_client or WeexClient(
            api_key=os.getenv("WEEX_API_KEY", ""),
            api_secret=os.getenv("WEEX_API_SECRET", ""),
            passphrase=os.getenv("WEEX_PASSPHRASE", ""),
        )
        self.paper = paper_fallback or PaperExecutor()

        # Strict safety gate: defaults to False unless explicitly set to 'true' in env
        if live_enabled is not None:
            self.live_enabled = live_enabled
        else:
            self.live_enabled = os.getenv("WEEX_LIVE_TRADING_ENABLED", "false").strip().lower() == "true"

        if not self.live_enabled:
            logger.info("WEEX Executor initialized in DRY-RUN / PAPER MODE (Zero live capital risk).")
        else:
            logger.warning("WEEX Executor initialized in LIVE CAPITAL TRADING MODE!")

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
        # Always track in paper executor for historical logging & metrics
        paper_res = self.paper.open_position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            size_usdt=size_usdt,
            stop_loss=stop_loss,
            take_profit=take_profit,
            setup_name=setup_name,
            setup_tier=setup_tier,
        )

        if not self.live_enabled:
            logger.info(
                "[WEEX DRY-RUN] Would have placed %s on WEEX for %s: Size $%.0f USDT | SL: $%.6f | TP: $%.6f",
                side,
                symbol,
                size_usdt,
                stop_loss,
                take_profit,
            )
            return {**paper_res, "weex_live": False, "note": "Dry-run execution"}

        # Live Execution on WEEX
        try:
            logger.info("[WEEX LIVE ORDER] Placing %s for %s on WEEX...", side, symbol)
            # Contract symbol formatting (e.g., BTC_USDT)
            weex_symbol = symbol if "_" in symbol else symbol.replace("USDT", "_USDT")
            order_res = self.client.place_order(
                symbol=weex_symbol,
                side="open_long" if side.upper() in ("BUY", "LONG") else "open_short",
                order_type="market",
                size=size_usdt / entry_price if entry_price > 0 else 1.0,
                is_contract=True,
            )
            return {
                "status": "FILLED_WEEX_LIVE",
                "symbol": symbol,
                "order_id": order_res.get("data", {}).get("orderId"),
                "weex_live": True,
                "response": order_res,
            }
        except Exception as exc:
            logger.error("[WEEX EXECUTION FAILED] %s: %s", symbol, exc)
            return {"status": "FAILED", "symbol": symbol, "error": str(exc), "weex_live": True}

    def update_price(self, symbol: str, current_price: float, timestamp_ms: int):
        self.paper.update_price(symbol, current_price, timestamp_ms)

    def close_position(self, symbol: str, reason: str = "MANUAL_CLOSE") -> Optional[Dict[str, Any]]:
        if not self.live_enabled:
            return self.paper.close_position(symbol, reason)

        # Close on WEEX
        try:
            weex_symbol = symbol if "_" in symbol else symbol.replace("USDT", "_USDT")
            self.client.place_order(
                symbol=weex_symbol,
                side="close_long",
                order_type="market",
                is_contract=True,
            )
        except Exception as exc:
            logger.error("Failed closing WEEX live position for %s: %s", symbol, exc)

        return self.paper.close_position(symbol, reason)

    def get_open_positions(self) -> Dict[str, Any]:
        return self.paper.get_open_positions()

    def get_performance_summary(self) -> Dict[str, Any]:
        return self.paper.get_performance_summary()
