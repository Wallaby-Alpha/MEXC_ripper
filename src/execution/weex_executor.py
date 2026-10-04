"""WEEX execution bridge implementing BaseExecutor with strict live-trading safety gate."""
import os
import time
import logging
from typing import Dict, Any, Optional, Tuple, List
from src.execution.base_executor import BaseExecutor
from src.execution.weex_client import WeexClient
from src.execution.paper_executor import PaperExecutor
from src.execution.weex_symbol_mapper import WeexSymbolResolver

logger = logging.getLogger(__name__)


def _safe_float_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    if not raw:
        return default
    clean = str(raw).split("#")[0].strip().strip('"').strip("'")
    try:
        return float(clean)
    except (ValueError, TypeError):
        return default


def _safe_int_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if not raw:
        return default
    clean = str(raw).split("#")[0].strip().strip('"').strip("'")
    try:
        return int(clean)
    except (ValueError, TypeError):
        return default


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
            api_key=str(os.getenv("WEEX_API_KEY", "")).split("#")[0].strip().strip('"').strip("'"),
            api_secret=str(os.getenv("WEEX_API_SECRET", "")).split("#")[0].strip().strip('"').strip("'"),
            passphrase=str(os.getenv("WEEX_PASSPHRASE", "")).split("#")[0].strip().strip('"').strip("'"),
        )
        self.paper = paper_fallback or PaperExecutor()
        self.resolver = symbol_resolver or WeexSymbolResolver()
        self.active_tpsl_orders: Dict[str, Dict[str, Any]] = {}
        self.live_positions: Dict[str, Dict[str, Any]] = {}
        self.leverage = _safe_int_env("WEEX_LEVERAGE", 10)

        # Strict safety gate: defaults to False unless explicitly set to 'true' in env
        if live_enabled is not None:
            self.live_enabled = live_enabled
        else:
            raw_enabled = str(os.getenv("WEEX_LIVE_TRADING_ENABLED", "false")).split("#")[0].strip().strip('"').strip("'").lower()
            self.live_enabled = raw_enabled == "true"

        if not self.live_enabled:
            logger.info("WEEX Executor initialized in DRY-RUN / PAPER MODE (Zero live capital risk).")
        else:
            logger.warning("WEEX Executor initialized in LIVE CAPITAL TRADING MODE (Leverage: %dx Isolated) with Native Exchange TP/SL enforcement!", self.leverage)
            ok, msg = self.verify_connection()
            if ok:
                logger.info("[WEEX LIVE CONNECTION VERIFIED] %s", msg)
            else:
                logger.error("[WEEX LIVE CONNECTION ERROR] %s", msg)

    def verify_connection(self) -> Tuple[bool, str]:
        """Tests live API connectivity and returns equity balance or error message."""
        if not self.live_enabled:
            return True, "DRY-RUN / PAPER MODE"
        if not self.client.api_key:
            return False, "WEEX_API_KEY is missing or empty in .env"
        try:
            res = self.client.get_account_assets(is_contract=True)
            data = res.get("data", res) if isinstance(res, dict) else res
            balance_str = "0.00"
            if isinstance(data, list) and data:
                for b in data:
                    if isinstance(b, dict) and b.get("asset") == "USDT":
                        balance_str = str(b.get("equity") or b.get("available") or b.get("balance") or "0.00")
                        break
            elif isinstance(data, dict):
                balance_str = str(data.get("equity") or data.get("available") or data.get("balance") or "0.00")
            return True, f"Connected to WEEX V3 Contract API | Equity: ${balance_str} USDT"
        except Exception as exc:
            return False, f"Connection Failed: {exc}"

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
        max_multiplier = _safe_float_env("WEEX_MAX_MARGIN_MULTIPLIER", 1.30)
        max_allowed_margin = target_margin * max_multiplier

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

            tp_order_id = "ATTACHED_ON_ENTRY"
            sl_order_id = "ATTACHED_ON_ENTRY"

            # 2. Register native Position TP/SL on exchange so WEEX UI displays the active TP/SL lines
            try:
                pos_ok = self.client.set_position_tpsl(
                    symbol=weex_symbol,
                    position_side=pos_side,
                    tp_price=tp_price_str,
                    sl_price=sl_price_str,
                )
                logger.info("[WEEX POSITION TP/SL] %s TP: $%s, SL: $%s -> %s", weex_symbol, tp_price_str, sl_price_str, "SUCCESS" if pos_ok else "FAILED")
            except Exception as pos_err:
                logger.warning("Could not set position TP/SL via /capi/v3/order/tpsl: %s", pos_err)

            # 3. Also place native conditional Trigger Orders on exchange (shows under Trigger/Plan Orders on WEEX)
            try:
                tp_res = self.client.place_tpsl_order(
                    symbol=weex_symbol,
                    plan_type="TAKE_PROFIT",
                    trigger_price=tp_price_str,
                    size=qty_str,
                    position_side=pos_side,
                )
                if isinstance(tp_res, dict) and (tp_res.get("orderId") or (isinstance(tp_res.get("data"), dict) and tp_res["data"].get("orderId"))):
                    tp_oid = str(tp_res.get("orderId") or tp_res["data"]["orderId"])
                    tp_order_id = tp_oid
                    logger.info("[WEEX NATIVE TP REGISTERED] %s Take Profit trigger order active @ $%s (Order ID: %s)", weex_symbol, tp_price_str, tp_oid)
            except Exception as tp_err:
                logger.warning("Dedicated TP trigger order failed: %s", tp_err)

            try:
                sl_res = self.client.place_tpsl_order(
                    symbol=weex_symbol,
                    plan_type="STOP_LOSS",
                    trigger_price=sl_price_str,
                    size=qty_str,
                    position_side=pos_side,
                )
                if isinstance(sl_res, dict) and (sl_res.get("orderId") or (isinstance(sl_res.get("data"), dict) and sl_res["data"].get("orderId"))):
                    sl_oid = str(sl_res.get("orderId") or sl_res["data"]["orderId"])
                    sl_order_id = sl_oid
                    logger.info("[WEEX NATIVE SL REGISTERED] %s Stop Loss trigger order active @ $%s (Order ID: %s)", weex_symbol, sl_price_str, sl_oid)
            except Exception as sl_err:
                logger.warning("Dedicated SL trigger order failed: %s", sl_err)

            self.active_tpsl_orders[symbol] = {
                "tp_order_id": tp_order_id,
                "sl_order_id": sl_order_id,
                "tp_price": tp_price_str,
                "sl_price": sl_price_str,
            }

            fill_payload = {
                "status": "FILLED_WEEX_LIVE",
                "symbol": symbol,
                "weex_symbol": weex_symbol,
                "order_id": main_order_id,
                "native_tp_order_id": tp_order_id,
                "native_sl_order_id": sl_order_id,
                "weex_live": True,
                "size_usdt": actual_margin,
                "notional_usdt": actual_notional,
                "qty_str": qty_str,
                "entry_price": entry_price,
                "entry_time_ms": int(time.time() * 1000),
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

        if not self.live_enabled:
            return

        # Check for Breakeven Ratchet on Live WEEX Position (+1.5% gain halfway to TP1)
        pos_info = self.live_positions.get(symbol)
        if pos_info and not pos_info.get("be_ratcheted", False):
            pos_info["current_price"] = current_price
            entry_p = float(pos_info.get("entry_price", 0.0))
            if entry_p > 0 and current_price >= entry_p * 1.015:
                weex_symbol = pos_info.get("weex_symbol") or self.resolver.resolve(symbol)
                qty_str = pos_info.get("qty_str")
                be_price = entry_p * 1.002
                be_price_str = self.resolver.format_price(weex_symbol, be_price)
                try:
                    self.client.set_position_tpsl(
                        symbol=weex_symbol,
                        position_side="LONG",
                        sl_price=be_price_str,
                    )
                    logger.info(
                        "[WEEX LIVE BREAKEVEN RATCHET] %s hit +1.5%% gain! Trailed native SL to Breakeven @ $%s (+0.2%% fee cushion)",
                        symbol,
                        be_price_str,
                    )
                    # Update dedicated trigger SL order if present
                    tpsl_info = self.active_tpsl_orders.get(symbol, {})
                    old_sl_id = tpsl_info.get("sl_order_id")
                    if old_sl_id and old_sl_id != "ATTACHED_ON_ENTRY":
                        try:
                            self.client.cancel_tpsl_order(weex_symbol, old_sl_id)
                        except Exception:
                            pass
                        try:
                            sl_res = self.client.place_tpsl_order(
                                symbol=weex_symbol,
                                plan_type="STOP_LOSS",
                                trigger_price=be_price_str,
                                size=qty_str,
                                position_side="LONG",
                            )
                            if isinstance(sl_res, dict) and (
                                sl_res.get("orderId")
                                or (isinstance(sl_res.get("data"), dict) and sl_res["data"].get("orderId"))
                            ):
                                tpsl_info["sl_order_id"] = str(sl_res.get("orderId") or sl_res["data"]["orderId"])
                                tpsl_info["sl_price"] = be_price_str
                        except Exception as e_sl:
                            logger.warning("Could not replace SL trigger order to breakeven: %s", e_sl)
                    pos_info["be_ratcheted"] = True
                except Exception as rat_err:
                    logger.warning("Failed updating native stop loss to breakeven for %s: %s", symbol, rat_err)
        elif pos_info:
            pos_info["current_price"] = current_price

    def close_position(self, symbol: str, reason: str = "MANUAL_CLOSE") -> Optional[Dict[str, Any]]:
        pos_info = self.live_positions.pop(symbol, None)
        if not self.live_enabled:
            return self.paper.close_position(symbol, reason)

        # Close on WEEX & cancel lingering native TP/SL orders
        try:
            weex_symbol = self.resolver.resolve(symbol) or (symbol if "_" in symbol else symbol.replace("USDT", "_USDT"))

            # Determine size to close
            qty_str = None
            if pos_info and "qty_str" in pos_info:
                qty_str = str(pos_info["qty_str"])
            else:
                try:
                    open_pos = self.client.get_open_positions()
                    for p in open_pos:
                        raw_s = str(p.get("symbol", "")).upper().replace("CMT_", "").replace("_USDT", "USDT")
                        canon = self.resolver.resolve(symbol) or symbol
                        if raw_s in (symbol.upper(), canon.upper()):
                            sz = float(p.get("total") or p.get("size") or p.get("positionAmt") or p.get("holdAmount") or 0.0)
                            if sz > 0:
                                qty_str = self.resolver.format_size(weex_symbol, sz)
                                break
                except Exception as sz_err:
                    logger.warning("Could not query live size for %s: %s", symbol, sz_err)

            # Cancel open conditional / trigger / plan orders for this symbol first
            tpsl_info = self.active_tpsl_orders.pop(symbol, {})
            for order_key in ("tp_order_id", "sl_order_id"):
                oid = tpsl_info.get(order_key)
                if oid and oid != "ATTACHED_ON_ENTRY":
                    try:
                        self.client.cancel_tpsl_order(weex_symbol, oid)
                        logger.info("[WEEX TRIGGER ORDER CANCELED] %s trigger order %s canceled", weex_symbol, oid)
                    except Exception:
                        pass

            # Market close the position on WEEX
            close_size = qty_str if qty_str else "1.0"
            res = self.client.place_order(
                symbol=weex_symbol,
                side="close_long",
                order_type="market",
                size=close_size,
                is_contract=True,
            )
            logger.info("[WEEX LIVE POSITION CLOSED] %s (%s) closed (Reason: %s, Qty: %s, Res: %s)", symbol, weex_symbol, reason, close_size, res)
        except Exception as exc:
            logger.error("Failed closing WEEX live position for %s: %s", symbol, exc)

        return self.paper.close_position(symbol, reason)

    def enforce_time_stops(self, max_age_ms: int = 24 * 3600 * 1000) -> List[str]:
        """Scans tracked live positions and actively closes stagnant underwater trades open >= 24 hours.
        CRITICAL: Never closes a position that is in profit or developing normally!
        """
        if not self.live_enabled:
            return []

        now_ms = int(time.time() * 1000)
        closed_symbols = []

        # 1. Check internally tracked live positions
        for sym, info in list(self.live_positions.items()):
            entry_t = info.get("entry_time_ms")
            entry_p = float(info.get("entry_price", 0.0))
            curr_p = float(info.get("current_price", entry_p))

            # Never close a trade in profit on time stop!
            if entry_p > 0 and curr_p >= entry_p * 1.002:
                continue

            if entry_t and (now_ms - entry_t) >= max_age_ms:
                dur_hours = (now_ms - entry_t) / (3600 * 1000)
                logger.info("[WEEX 24H TIME STOP TRIGGERED] Closing stagnant underwater %s (held %.1f hours)", sym, dur_hours)
                self.close_position(sym, reason="CLOSED_TIMEOUT (24H TIME STOP)")
                closed_symbols.append(sym)

        # 2. Check exchange live positions for any untracked or stale positions >= 24h
        try:
            exchange_positions = self.client.get_open_positions()
            for p in exchange_positions:
                raw_sym = str(p.get("symbol", "")).upper().replace("CMT_", "").replace("_USDT", "USDT")
                # Do not close if exchange position has positive unrealized PnL!
                unrealized = float(p.get("unrealizedPL") or p.get("unrealisedPnl") or p.get("upl") or 0.0)
                if unrealized > 0:
                    continue

                ctime_raw = p.get("cTime") or p.get("openTime") or p.get("ctime") or p.get("uTime")
                if ctime_raw:
                    try:
                        ctime_ms = int(ctime_raw)
                        if (now_ms - ctime_ms) >= max_age_ms:
                            dur_hours = (now_ms - ctime_ms) / (3600 * 1000)
                            logger.info("[WEEX EXCHANGE 24H TIME STOP] Closing stale underwater %s (held %.1f hours on exchange)", raw_sym, dur_hours)
                            self.close_position(raw_sym, reason="CLOSED_TIMEOUT (24H TIME STOP)")
                            if raw_sym not in closed_symbols:
                                closed_symbols.append(raw_sym)
                    except (ValueError, TypeError):
                        pass
        except Exception as exc:
            logger.warning("Error checking exchange positions for time stops: %s", exc)

        return closed_symbols

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
