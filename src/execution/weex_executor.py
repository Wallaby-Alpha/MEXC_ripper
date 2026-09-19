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
        self.leverage = int(os.getenv("WEEX_LEVERAGE", "10"))

        # Strict safety gate: defaults to False unless explicitly set to 'true' in env
        if live_enabled is not None:
            self.live_enabled = live_enabled
        else:
            self.live_enabled = os.getenv("WEEX_LIVE_TRADING_ENABLED", "false").strip().lower() == "true"

        if not self.live_enabled:
            logger.info("WEEX Executor initialized in DRY-RUN / PAPER MODE (Zero live capital risk).")
        else:
            logger.warning("WEEX Executor initialized in LIVE CAPITAL TRADING MODE (Leverage: %dx Isolated) with Native Exchange TP/SL enforcement!", self.leverage)

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size_usdt: float,
        stop_loss: float,
        take_profit: float,
        setup_name: str = "MOMENTUM_EXPANSION",
        setup_tier: str = "TIER 2",
    ) -> Dict[str, Any]:
        """Opens position on WEEX futures with 10x leverage and native exchange-level TP/SL."""
        # 1. Update internal paper ledger regardless
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

        # Resolve MEXC symbol to canonical WEEX contract symbol (e.g. SUIUSDT)
        weex_symbol = self.resolver.resolve(symbol)
        if not weex_symbol:
            logger.warning("[WEEX SKIPPED] %s is not listed as a perpetual contract on WEEX. Software paper position logged.", symbol)
            return {
                **paper_res,
                "weex_live": False,
                "status": "SKIPPED_UNLISTED_ON_WEEX",
                "note": f"{symbol} not listed on WEEX perpetual contracts",
            }

        # Calculate position size: size_usdt is margin allocated (e.g. $10 at 10x = $100 notional)
        notional_usdt = size_usdt * self.leverage
        raw_qty = notional_usdt / entry_price if entry_price > 0 else 1.0
        qty_str = self.resolver.format_size(weex_symbol, raw_qty)
        qty = float(qty_str)
        tp_price_str = self.resolver.format_price(weex_symbol, take_profit)
        sl_price_str = self.resolver.format_price(weex_symbol, stop_loss)
        tp_price = float(tp_price_str)
        sl_price = float(sl_price_str)

        # Capital Budget Protection Collar:
        # If exchange minOrderSize forces an order that exceeds margin budget by >30%, abort live execution!
        actual_notional = qty * entry_price
        actual_margin = actual_notional / self.leverage if self.leverage > 0 else actual_notional
        max_allowed_margin = size_usdt * float(os.getenv("WEEX_MAX_MARGIN_MULTIPLIER", "1.30"))

        if actual_margin > max_allowed_margin:
            logger.warning(
                "[WEEX SKIPPED: MIN_ORDER_EXCEEDS_BUDGET] %s (%s) min order %s requires $%.2f margin ($%.2f notional), exceeding target margin $%.2f (collar limit: $%.2f). Live order aborted.",
                symbol,
                weex_symbol,
                qty_str,
                actual_margin,
                actual_notional,
                size_usdt,
                max_allowed_margin,
            )
            return {
                **paper_res,
                "weex_live": False,
                "status": "SKIPPED_MIN_ORDER_EXCEEDS_BUDGET",
                "symbol": symbol,
                "weex_symbol": weex_symbol,
                "required_margin": actual_margin,
                "target_margin": size_usdt,
                "notional_usdt": actual_notional,
                "note": f"Min order {qty_str} requires ${actual_margin:.2f} margin (budget: ${size_usdt:.2f})",
            }

        if not self.live_enabled:
            logger.info(
                "[WEEX DRY-RUN] Would have placed %s on WEEX for %s (%s): Margin $%.2f (Notional $%.2f @ %dx) | Qty %s | SL: $%s | TP: $%s",
                side,
                symbol,
                weex_symbol,
                actual_margin,
                actual_notional,
                self.leverage,
                qty_str,
                sl_price_str,
                tp_price_str,
            )
            return {
                **paper_res,
                "weex_live": False,
                "weex_symbol": weex_symbol,
                "size_usdt": actual_margin,
                "notional_usdt": actual_notional,
                "note": "Dry-run execution",
            }

        # Live Execution on WEEX with 10x Leverage and Native Exchange TP/SL
        try:
            # 0. Enforce 10x leverage on the exchange before placing order
            try:
                self.client.set_leverage(symbol=weex_symbol, leverage=self.leverage)
                logger.info("[WEEX LEVERAGE] Configured %s to %dx leverage", weex_symbol, self.leverage)
            except Exception as lev_err:
                logger.warning("[WEEX LEVERAGE WARNING] %s leverage set warning: %s", weex_symbol, lev_err)

            logger.info("[WEEX LIVE ORDER] Submitting market entry for %s as %s (%s, Qty: %s, Margin: $%.2f @ %dx)...", symbol, weex_symbol, side, qty_str, actual_margin, self.leverage)
            pos_side = "LONG" if side.upper() in ("BUY", "LONG") else "SHORT"

            # 1. Market Entry Order with attached native TP/SL triggers (tpTriggerPrice, slTriggerPrice)
            order_res = self.client.place_order(
                symbol=weex_symbol,
                side="open_long" if pos_side == "LONG" else "open_short",
                order_type="market",
                size=qty_str,
                tp_price=tp_price_str,
                sl_price=sl_price_str,
                is_contract=True,
            )
            data = order_res.get("data", order_res) if isinstance(order_res, dict) else {}
            main_order_id = ""
            if isinstance(data, dict) and data.get("orderId"):
                main_order_id = str(data["orderId"])
            elif isinstance(order_res, dict) and order_res.get("orderId"):
                main_order_id = str(order_res["orderId"])

            code = str(order_res.get("code", "")) if isinstance(order_res, dict) else ""
            msg = order_res.get("msg") or order_res.get("errorMessage") or ""

            success = (
                (code in ("0", "00000", "200") and bool(main_order_id))
                or (isinstance(data, dict) and data.get("success", False) and bool(main_order_id))
                or (bool(main_order_id) and main_order_id != "N/A")
            )

            if not success or not main_order_id or main_order_id == "N/A":
                err_code = code or "REJECTED"
                err_msg = f"[{err_code}] {msg}" if msg else f"WEEX rejected order (code: {err_code})"
                logger.error("[WEEX REJECTED] %s (%s): %s", symbol, weex_symbol, err_msg)
                return {
                    **paper_res,
                    "weex_live": False,
                    "status": "WEEX_REJECTED",
                    "size_usdt": actual_margin,
                    "notional_usdt": actual_notional,
                    "leverage": self.leverage,
                    "error": err_msg,
                    "raw": order_res,
                }

            logger.info("[WEEX ENTRY FILLED] %s (%s) Order ID: %s", symbol, weex_symbol, main_order_id)

            return {
                "status": "FILLED_WEEX_LIVE",
                "symbol": symbol,
                "weex_symbol": weex_symbol,
                "order_id": main_order_id,
                "native_tp_order_id": "ATTACHED_ON_ENTRY",
                "native_sl_order_id": "ATTACHED_ON_ENTRY",
                "weex_live": True,
                "size_usdt": actual_margin,
                "notional_usdt": actual_notional,
                "leverage": self.leverage,
                "response": order_res,
            }
        except Exception as exc:
            logger.error("[WEEX EXECUTION FAILED] %s: %s", symbol, exc)
            return {
                **paper_res,
                "status": "FAILED",
                "symbol": symbol,
                "size_usdt": size_usdt,
                "leverage": self.leverage,
                "error": str(exc),
                "weex_live": False,
            }

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
