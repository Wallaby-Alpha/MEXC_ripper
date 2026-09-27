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
        self.live_positions: Dict[str, Dict[str, Any]] = {}
        self.be_trailed_symbols = set()
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

        # 0. Enforce leverage setting on WEEX upfront before order construction
        if self.live_enabled:
            try:
                self.client.set_leverage(symbol=weex_symbol, leverage=self.leverage)
                logger.info("[WEEX LEVERAGE] Configured %s to %dx leverage", weex_symbol, self.leverage)
            except Exception as lev_err:
                logger.warning("[WEEX LEVERAGE WARNING] %s leverage set warning: %s", weex_symbol, lev_err)

        # Calculate position size: size_usdt is target margin (e.g. $1.00 margin @ 10x = $10.00 notional)
        target_margin = min(size_usdt, 1.50)  # Hard cap: Max $1.50 margin per trade
        notional_usdt = target_margin * self.leverage
        raw_qty = notional_usdt / entry_price if entry_price > 0 else 1.0
        qty_str = self.resolver.format_size(weex_symbol, raw_qty)
        qty = float(qty_str)
        tp_price_str = self.resolver.format_price(weex_symbol, take_profit)
        sl_price_str = self.resolver.format_price(weex_symbol, stop_loss)
        tp_price = float(tp_price_str)
        sl_price = float(sl_price_str)

        # Capital Budget Protection Collar:
        # If exchange minOrderSize forces an order that exceeds margin budget by >30% (max $1.30 margin), ABORT!
        actual_notional = qty * entry_price
        actual_margin = actual_notional / self.leverage if self.leverage > 0 else actual_notional
        max_allowed_margin = target_margin * float(os.getenv("WEEX_MAX_MARGIN_MULTIPLIER", "1.30"))

        if actual_margin > max_allowed_margin or actual_margin > 1.50:
            logger.warning(
                "[WEEX SKIPPED: MARGIN_CAP_EXCEEDED] %s (%s) order qty %s requires $%.2f margin ($%.2f notional), exceeding target margin $%.2f (collar limit: $%.2f). Live order aborted.",
                symbol,
                weex_symbol,
                qty_str,
                actual_margin,
                actual_notional,
                target_margin,
                max_allowed_margin,
            )
            return {
                **paper_res,
                "weex_live": False,
                "status": "SKIPPED_MARGIN_CAP_EXCEEDED",
                "symbol": symbol,
                "weex_symbol": weex_symbol,
                "required_margin": actual_margin,
                "target_margin": target_margin,
                "notional_usdt": actual_notional,
                "note": f"Order requires ${actual_margin:.2f} margin (cap: ${max_allowed_margin:.2f})",
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

            fill_payload = {
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
            self.live_positions[symbol] = fill_payload
            return fill_payload
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

        # If Breakeven Trigger (1.25x SL) was reached, update native exchange SL to Breakeven
        if self.live_enabled and symbol in self.paper.trader.open_positions:
            pos = self.paper.trader.open_positions[symbol]
            if getattr(pos, "be_triggered", False) and symbol not in self.be_trailed_symbols:
                self.be_trailed_symbols.add(symbol)
                weex_symbol = self.resolver.resolve(symbol) or (symbol if "_" in symbol else symbol.replace("USDT", "_USDT"))
                be_price_str = self.resolver.format_price(weex_symbol, pos.stop_loss)
                try:
                    res = self.client.update_position_tpsl(weex_symbol, sl_price=be_price_str)
                    logger.info("[WEEX LIVE STOP TRAILED] %s stop trailed to Breakeven ($%s) on exchange: %s", weex_symbol, be_price_str, res)
                except Exception as tpsl_err:
                    logger.warning("Could not update WEEX exchange SL to breakeven for %s: %s", weex_symbol, tpsl_err)

    def close_position(self, symbol: str, reason: str = "MANUAL_CLOSE") -> Optional[Dict[str, Any]]:
        self.be_trailed_symbols.discard(symbol)
        self.live_positions.pop(symbol, None)
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
        """Returns currently active live positions on WEEX when in live mode."""
        if not self.live_enabled:
            return self.paper.get_open_positions()

        # Query live exchange positions from WEEX V3 Contract API
        try:
            weex_open = self.client.get_open_positions()
            live_dict = {}
            if isinstance(weex_open, list):
                for p in weex_open:
                    raw_s = str(p.get("symbol", "")).upper().replace("CMT_", "").replace("_USDT", "USDT")
                    live_dict[raw_s] = p

            # Reconcile with internally tracked filled positions
            active_live = {}
            for s, info in self.live_positions.items():
                canon = self.resolver.resolve(s) or s
                canon_clean = canon.upper().replace("CMT_", "").replace("_USDT", "USDT")
                if canon_clean in live_dict or s in live_dict:
                    active_live[s] = info
                elif not weex_open:
                    # If API query fails or returned empty temporarily, preserve internally tracked
                    active_live[s] = info

            # Add any live positions found on exchange not yet in active_live
            for s, p in live_dict.items():
                if s not in active_live:
                    active_live[s] = p

            self.live_positions = {k: v for k, v in self.live_positions.items() if k in active_live}
            return active_live
        except Exception as exc:
            logger.warning("Error querying WEEX live positions: %s", exc)

        return self.live_positions

    def get_performance_summary(self) -> Dict[str, Any]:
        return self.paper.get_performance_summary()
