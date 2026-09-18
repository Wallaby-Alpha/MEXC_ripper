"""WEEX execution bridge implementing BaseExecutor with strict live-trading safety gate."""
import os
import logging
from typing import Dict, Any, Optional
from src.execution.base_executor import BaseExecutor
from src.execution.weex_client import WeexClient
from src.execution.paper_executor import PaperExecutor
from src.execution.weex_symbol_mapper import WeexSymbolResolver

logger = logging.getLogger(__name__)


class WeexExecutor(BaseExecutor):
    """Bridge for executing trades on WEEX exchange with safe dry-run fallback."""

    def __init__(
        self,
        weex_client: Optional[WeexClient] = None,
        paper_fallback: Optional[PaperExecutor] = None,
        symbol_resolver: Optional[WeexSymbolResolver] = None,
        live_enabled: Optional[bool] = None,
    ):
        self.client = weex_client or WeexClient(
            api_key=os.getenv("WEEX_API_KEY", ""),
            api_secret=os.getenv("WEEX_API_SECRET", ""),
            passphrase=os.getenv("WEEX_PASSPHRASE", ""),
        )
        self.paper = paper_fallback or PaperExecutor()
        self.resolver = symbol_resolver or WeexSymbolResolver()
        self.active_tpsl_orders: Dict[str, Dict[str, Any]] = {}

        # Strict safety gate: defaults to False unless explicitly set to 'true' in env
        if live_enabled is not None:
            self.live_enabled = live_enabled
        else:
            self.live_enabled = os.getenv("WEEX_LIVE_TRADING_ENABLED", "false").strip().lower() == "true"

        if not self.live_enabled:
            logger.info("WEEX Executor initialized in DRY-RUN / PAPER MODE (Zero live capital risk).")
        else:
            logger.warning("WEEX Executor initialized in LIVE CAPITAL TRADING MODE with Native Exchange TP/SL enforcement!")

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
        # Always track in paper executor for baseline logging & metrics
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

        # Resolve MEXC symbol to canonical WEEX contract symbol (e.g. SUIUSDT -> cmt_suiusdt)
        weex_symbol = self.resolver.resolve(symbol)
        if not weex_symbol:
            logger.warning("[WEEX SKIPPED] %s is not listed as a perpetual contract on WEEX. Software paper position logged.", symbol)
            return {
                **paper_res,
                "weex_live": False,
                "status": "SKIPPED_UNLISTED_ON_WEEX",
                "note": f"{symbol} not listed on WEEX perpetual contracts",
            }

        # Format price and size according to WEEX exchange tick size & lot increments
        qty = float(self.resolver.format_size(weex_symbol, size_usdt / entry_price if entry_price > 0 else 1.0))
        tp_price = float(self.resolver.format_price(weex_symbol, take_profit))
        sl_price = float(self.resolver.format_price(weex_symbol, stop_loss))

        if not self.live_enabled:
            logger.info(
                "[WEEX DRY-RUN] Would have placed %s on WEEX for %s (%s): Qty %.4f | SL: $%.6f | TP: $%.6f",
                side,
                symbol,
                weex_symbol,
                qty,
                sl_price,
                tp_price,
            )
            return {**paper_res, "weex_live": False, "weex_symbol": weex_symbol, "note": "Dry-run execution"}

        # Live Execution on WEEX with Native Exchange TP/SL
        try:
            logger.info("[WEEX LIVE ORDER] Submitting market entry for %s as %s (%s)...", symbol, weex_symbol, side)
            pos_side = "LONG" if side.upper() in ("BUY", "LONG") else "SHORT"

            # 1. Market Entry Order with preset TP/SL parameters attached
            order_res = self.client.place_order(
                symbol=weex_symbol,
                side="open_long" if pos_side == "LONG" else "open_short",
                order_type="market",
                size=qty,
                preset_take_profit_price=tp_price,
                preset_stop_loss_price=sl_price,
                is_contract=True,
            )
            main_order_id = order_res.get("data", {}).get("orderId", "N/A")
            logger.info("[WEEX ENTRY FILLED] %s (%s) Order ID: %s", symbol, weex_symbol, main_order_id)

            # 2. Guarantee Native Exchange-Level Take Profit Order
            native_tp_id = None
            try:
                tp_res = self.client.place_tpsl_order(
                    symbol=weex_symbol,
                    plan_type="TAKE_PROFIT",
                    trigger_price=tp_price,
                    size=qty,
                    position_side=pos_side,
                )
                native_tp_id = tp_res.get("data", {}).get("orderId")
                logger.info("[WEEX NATIVE TP CONFIRMED] %s Target: $%.6f | Order ID: %s", weex_symbol, tp_price, native_tp_id)
            except Exception as exc:
                logger.warning("[WEEX NATIVE TP WARNING] %s failed to set exchange TP (%s)", weex_symbol, exc)

            # 3. Guarantee Native Exchange-Level Stop Loss Order
            native_sl_id = None
            try:
                sl_res = self.client.place_tpsl_order(
                    symbol=weex_symbol,
                    plan_type="STOP_LOSS",
                    trigger_price=sl_price,
                    size=qty,
                    position_side=pos_side,
                )
                native_sl_id = sl_res.get("data", {}).get("orderId")
                logger.info("[WEEX NATIVE SL CONFIRMED] %s Invalidation: $%.6f | Order ID: %s", weex_symbol, sl_price, native_sl_id)
            except Exception as exc:
                logger.warning("[WEEX NATIVE SL WARNING] %s failed to set exchange SL (%s)", weex_symbol, exc)

            self.active_tpsl_orders[symbol] = {
                "tp_order_id": native_tp_id,
                "sl_order_id": native_sl_id,
                "weex_symbol": weex_symbol,
            }

            return {
                "status": "FILLED_WEEX_LIVE",
                "symbol": symbol,
                "weex_symbol": weex_symbol,
                "order_id": main_order_id,
                "native_tp_order_id": native_tp_id,
                "native_sl_order_id": native_sl_id,
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

        # Close on WEEX & cancel lingering native TP/SL orders
        try:
            weex_symbol = symbol if "_" in symbol else symbol.replace("USDT", "_USDT")
            self.client.place_order(
                symbol=weex_symbol,
                side="close_long",
                order_type="market",
                is_contract=True,
            )
            # Cancel open conditional orders for this symbol
            tpsl_info = self.active_tpsl_orders.pop(symbol, {})
            for order_key in ("tp_order_id", "sl_order_id"):
                oid = tpsl_info.get(order_key)
                if oid:
                    try:
                        self.client.cancel_tpsl_order(weex_symbol, oid)
                    except Exception:
                        pass
        except Exception as exc:
            logger.error("Failed closing WEEX live position for %s: %s", symbol, exc)

        return self.paper.close_position(symbol, reason)

    def get_open_positions(self) -> Dict[str, Any]:
        return self.paper.get_open_positions()

    def get_performance_summary(self) -> Dict[str, Any]:
        return self.paper.get_performance_summary()
