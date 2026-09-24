import time
import uuid
import hmac
import hashlib
import base64
import json
import logging
from typing import Dict, Any, Optional, Union
import httpx

logger = logging.getLogger(__name__)


class WeexClient:
    """Handles communication with WEEX Spot and Contract/Futures REST API."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        contract_base_url: str = "https://api-contract.weex.com",
        spot_base_url: str = "https://api-spot.weex.com",
        timeout: float = 10.0,
    ):
        self.api_key = api_key.strip().strip("'\"") if api_key else ""
        self.api_secret = api_secret.strip().strip("'\"") if api_secret else ""
        self.passphrase = passphrase.strip().strip("'\"") if passphrase else ""
        self.contract_base_url = contract_base_url.rstrip("/")
        self.spot_base_url = spot_base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """Generates HMAC-SHA256 Base64-encoded signature according to WEEX API documentation:
        Pre-hash: timestamp + METHOD + requestPath + body
        """
        message = f"{timestamp}{method.upper()}{request_path}{body}"
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        sign = self.generate_signature(timestamp, method, request_path, body) if self.api_secret else ""
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "User-Agent": "MEXC-WEEX-Momentum-Scanner/1.0",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        is_contract: bool = True,
    ) -> Dict[str, Any]:
        base_url = self.contract_base_url if is_contract else self.spot_base_url
        full_path = path
        query_str = ""
        if params:
            query_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            full_path = f"{path}?{query_str}"

        body_str = json.dumps(data) if data else ""
        headers = self._get_headers(method, full_path, body_str)
        url = f"{base_url}{full_path}"

        response = self.client.request(
            method=method,
            url=url,
            headers=headers,
            content=body_str if data else None,
        )

        try:
            res_json = response.json()
        except Exception:
            res_json = None

        if response.status_code != 200:
            logger.error("WEEX API request error [%d]: %s", response.status_code, response.text)
            if isinstance(res_json, dict):
                return res_json
            response.raise_for_status()

        if isinstance(res_json, dict):
            code = res_json.get("code")
            msg = res_json.get("msg", "")
            if code and code not in ("0", "00000", "200"):
                logger.error("WEEX API returned error [%s]: %s (url: %s)", code, msg, url)
        return res_json or {}

    # ------------------------------------------------------------------------
    # Public & Account Endpoints
    # ------------------------------------------------------------------------

    def get_server_time(self) -> int:
        """Fetch WEEX server timestamp."""
        res = self._request("GET", "/capi/v3/market/time", is_contract=True)
        return int(res.get("data", {}).get("serverTime", time.time() * 1000))

    def get_account_assets(self, is_contract: bool = True) -> Dict[str, Any]:
        """Fetch account balance and available equity."""
        path = "/capi/v3/account/balance" if is_contract else "/api/v3/account/"
        return self._request("GET", path, is_contract=is_contract)

    def set_leverage(self, symbol: str, leverage: int = 10) -> bool:
        """Sets isolated leverage for both long and short positions on the symbol."""
        payload = {
            "symbol": symbol,
            "isolatedLongLeverage": str(leverage),
            "isolatedShortLeverage": str(leverage),
        }
        res = self._request("POST", "/capi/v3/account/leverage", data=payload, is_contract=True)
        if not isinstance(res, dict):
            return False
        code = str(res.get("code", ""))
        return (
            code in ("0", "00000", "200")
            or res.get("symbol") == symbol
            or "crossLeverage" in res
            or "isolatedLongLeverage" in res
            or res.get("success", False)
        )

    def place_order(
        self,
        symbol: str,
        side: str,  # 'open_long', 'open_short', 'BUY', 'SELL'
        order_type: str = "market",  # 'market' or 'limit'
        size: Union[float, str] = 1.0,
        price: Optional[float] = None,
        tp_price: Optional[Union[float, str]] = None,
        sl_price: Optional[Union[float, str]] = None,
        preset_take_profit_price: Optional[float] = None,
        preset_stop_loss_price: Optional[float] = None,
        is_contract: bool = True,
    ) -> Dict[str, Any]:
        """Place order on WEEX V3 Contract API with optional native attached TP/SL triggers.
        WEEX V3 requires client order IDs to have the 'b-' prefix.
        """
        # Clean side and positionSide for WEEX V3 Contract API:
        side_lower = str(side).lower()
        if side_lower in ("close_long", "sell_close"):
            order_side = "SELL"
            pos_side = "LONG"
        elif side_lower in ("close_short", "buy_close"):
            order_side = "BUY"
            pos_side = "SHORT"
        elif "short" in side_lower or "sell" in side_lower:
            order_side = "SELL"
            pos_side = "SHORT"
        else:
            order_side = "BUY"
            pos_side = "LONG"

        client_oid = f"b-mexc-{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}"

        # Clean quantity representation
        try:
            qty_val = float(size)
            size_str = str(int(qty_val)) if qty_val.is_integer() else str(qty_val)
        except (ValueError, TypeError):
            size_str = str(size)

        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": order_side,
            "positionSide": pos_side,
            "type": order_type.upper(),
            "quantity": size_str,
            "newClientOrderId": client_oid,
        }

        # Resolve TP/SL from either tp_price or legacy preset_take_profit_price
        target_tp = tp_price if tp_price is not None else preset_take_profit_price
        target_sl = sl_price if sl_price is not None else preset_stop_loss_price

        if target_tp is not None:
            try:
                if float(target_tp) > 0:
                    payload["tpTriggerPrice"] = str(target_tp)
                    payload["tpWorkingType"] = "MARK_PRICE"
            except (ValueError, TypeError):
                pass

        if target_sl is not None:
            try:
                if float(target_sl) > 0:
                    payload["slTriggerPrice"] = str(target_sl)
                    payload["slWorkingType"] = "MARK_PRICE"
            except (ValueError, TypeError):
                pass

        if price is not None and order_type.upper() == "LIMIT":
            payload["price"] = str(price)
            payload["timeInForce"] = "GTC"

        endpoint = "/capi/v3/order" if is_contract else "/api/v3/order"
        return self._request("POST", endpoint, data=payload, is_contract=is_contract)

    def set_position_tpsl(
        self,
        symbol: str,
        position_side: str,  # "LONG" or "SHORT"
        tp_price: Optional[Union[float, str]] = None,
        sl_price: Optional[Union[float, str]] = None,
    ) -> bool:
        """Sets or updates native position-level Take Profit / Stop Loss trigger prices on WEEX.
        Uses /capi/v3/order/tpsl so exchange UI displays the active TP/SL lines.
        """
        payload = {
            "symbol": symbol,
            "holdSide": position_side.upper(),
            "positionSide": position_side.upper(),
            "planType": "PROFIT_LOSS",
            "workingType": "MARK_PRICE",
            "triggerType": "MARK_PRICE",
        }
        if tp_price is not None and float(tp_price) > 0:
            payload["takeProfitPrice"] = str(tp_price)
            payload["tpTriggerPrice"] = str(tp_price)
        if sl_price is not None and float(sl_price) > 0:
            payload["stopLossPrice"] = str(sl_price)
            payload["slTriggerPrice"] = str(sl_price)

        try:
            res = self._request("POST", "/capi/v3/order/tpsl", data=payload, is_contract=True)
            if isinstance(res, dict):
                code = str(res.get("code", ""))
                return code in ("0", "00000", "200") or res.get("success", False)
            return False
        except Exception as exc:
            logger.warning("Failed to update position TP/SL on /capi/v3/order/tpsl: %s", exc)
            return False

    def place_tpsl_order(
        self,
        symbol: str,
        plan_type: str,  # 'TAKE_PROFIT' or 'STOP_LOSS'
        trigger_price: Union[float, str],
        size: Union[float, str],
        position_side: str = "LONG",  # 'LONG' or 'SHORT'
        execute_price: float = 0.0,   # 0 for market execution on trigger
        trigger_type: str = "CONTRACT_PRICE",
    ) -> Dict[str, Any]:
        """Places a native exchange-level conditional Take-Profit or Stop-Loss plan order on WEEX."""
        tpsl_oid = f"b-tp-{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}"

        try:
            qty_val = float(size)
            qty_str = str(int(qty_val)) if qty_val.is_integer() else str(qty_val)
        except (ValueError, TypeError):
            qty_str = str(size)

        if isinstance(trigger_price, (int, float)):
            trig_str = f"{trigger_price:.8f}".rstrip("0").rstrip(".")
        else:
            trig_str = str(trigger_price)

        exec_str = "0" if execute_price == 0 else f"{execute_price:.8f}".rstrip("0").rstrip(".")

        payload = {
            "symbol": symbol,
            "clientOrderId": tpsl_oid,
            "newClientOrderId": tpsl_oid,
            "planType": plan_type.upper(),
            "triggerPrice": trig_str,
            "executePrice": exec_str,
            "quantity": qty_str,
            "positionSide": position_side.upper(),
            "triggerPriceType": "MARK_PRICE" if "mark" in str(trigger_type).lower() else "CONTRACT_PRICE",
        }

        # Primary WEEX V3 contract TPSL endpoint with fallback
        try:
            return self._request("POST", "/capi/v3/placeTpSlOrder", data=payload, is_contract=True)
        except Exception as exc:
            logger.warning("Primary TPSL endpoint failed (%s), attempting fallback /capi/v3/algoOrder...", exc)
            return self._request("POST", "/capi/v3/algoOrder", data=payload, is_contract=True)

    def cancel_tpsl_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancels a native conditional TP/SL order on WEEX."""
        payload = {"symbol": symbol, "orderId": str(order_id)}
        try:
            return self._request("POST", "/capi/v3/cancelTpSlOrder", data=payload, is_contract=True)
        except Exception:
            return self._request("POST", "/api/v3/trade/cancel-tpsl", data=payload, is_contract=True)

    def get_open_tpsl_orders(self, symbol: str) -> Dict[str, Any]:
        """Retrieves pending native exchange-level TP/SL orders for a symbol."""
        params = {"symbol": symbol}
        return self._request("GET", "/capi/v3/currentPlanOrder", params=params, is_contract=True)

    def set_leverage(
        self,
        symbol: str,
        leverage: int = 10,
        is_contract: bool = True,
    ) -> Dict[str, Any]:
        """Configure contract leverage for a trading pair on WEEX."""
        lev_str = str(leverage)
        payload = {
            "symbol": symbol.upper(),
            "isolatedLongLeverage": lev_str,
            "isolatedShortLeverage": lev_str,
        }
        return self._request("POST", "/capi/v3/account/leverage", data=payload, is_contract=is_contract)

    def cancel_order(self, symbol: str, order_id: str, is_contract: bool = True) -> Dict[str, Any]:
        """Cancel an open order."""
        payload = {"symbol": symbol, "orderId": order_id}
        return self._request("POST", "/api/v3/trade/cancel", data=payload, is_contract=is_contract)

    def close(self):
        self.client.close()
