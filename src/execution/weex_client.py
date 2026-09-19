"""WEEX REST API Client with HMAC-SHA256 Base64 authentication (V3 Interface)."""
import time
import hmac
import hashlib
import base64
import json
import logging
from typing import Dict, Any, Optional
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
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
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
        if response.status_code != 200:
            logger.error("WEEX API request error [%d]: %s", response.status_code, response.text)
            response.raise_for_status()

        res_json = response.json()
        if isinstance(res_json, dict):
            code = res_json.get("code")
            msg = res_json.get("msg", "")
            if code and code != "00000":
                logger.error("WEEX API returned error [%s]: %s (url: %s)", code, msg, url)
        return res_json

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

    # ------------------------------------------------------------------------
    # Trade Execution Endpoints
    # ------------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,  # 'open_long', 'open_short', 'BUY', 'SELL'
        order_type: str = "market",  # 'market' or 'limit'
        size: float = 1.0,
        price: Optional[float] = None,
        preset_take_profit_price: Optional[float] = None,
        preset_stop_loss_price: Optional[float] = None,
        is_contract: bool = True,
    ) -> Dict[str, Any]:
        """Place order on WEEX with optional preset exchange-level TP/SL."""
        # Clean side and positionSide for WEEX V3 Contract API:
        # side: "BUY" or "SELL"
        # positionSide: "LONG" or "SHORT"
        # type: "MARKET" or "LIMIT"
        # quantity: str(size)
        if "short" in str(side).lower() or "sell" in str(side).lower():
            order_side = "SELL"
            pos_side = "SHORT"
        else:
            order_side = "BUY"
            pos_side = "LONG"

        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": order_side,
            "positionSide": pos_side,
            "type": order_type.upper(),
            "quantity": str(size),
            "size": str(size),  # include both for v2/v3 compatibility
        }
        if price is not None and order_type.upper() == "LIMIT":
            payload["price"] = str(price)

        if preset_take_profit_price is not None and preset_take_profit_price > 0:
            payload["presetTakeProfitPrice"] = f"{preset_take_profit_price:.8f}".rstrip("0").rstrip(".")

        if preset_stop_loss_price is not None and preset_stop_loss_price > 0:
            payload["presetStopLossPrice"] = f"{preset_stop_loss_price:.8f}".rstrip("0").rstrip(".")

        # In WEEX Contract V3, the canonical endpoint is /capi/v3/order
        endpoint = "/capi/v3/order" if is_contract else "/api/v3/order"
        try:
            return self._request("POST", endpoint, data=payload, is_contract=is_contract)
        except Exception as exc:
            if is_contract:
                logger.warning("Primary endpoint %s failed (%s), attempting fallback /capi/v2/order/placeOrder...", endpoint, exc)
                payload_v2 = {**payload, "side": str(side).lower()}
                return self._request("POST", "/capi/v2/order/placeOrder", data=payload_v2, is_contract=True)
            raise

    def place_tpsl_order(
        self,
        symbol: str,
        plan_type: str,  # 'TAKE_PROFIT' or 'STOP_LOSS'
        trigger_price: float,
        size: float,
        position_side: str = "LONG",  # 'LONG' or 'SHORT'
        execute_price: float = 0.0,   # 0 for market execution on trigger
        trigger_type: str = "MARK_PRICE",
    ) -> Dict[str, Any]:
        """Places a native exchange-level conditional Take-Profit or Stop-Loss plan order on WEEX."""
        payload = {
            "symbol": symbol,
            "planType": plan_type.upper(),
            "triggerPrice": f"{trigger_price:.8f}".rstrip("0").rstrip("."),
            "executePrice": "0" if execute_price == 0 else f"{execute_price:.8f}".rstrip("0").rstrip("."),
            "quantity": f"{size:.4f}".rstrip("0").rstrip(".") if size > 0 else "0",
            "size": f"{size:.4f}".rstrip("0").rstrip(".") if size > 0 else "0",
            "positionSide": position_side.upper(),
            "triggerPriceType": "MARK_PRICE" if "mark" in str(trigger_type).lower() else "CONTRACT_PRICE",
            "triggerType": trigger_type,
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

    def set_leverage(self, symbol: str, leverage: int = 5, is_contract: bool = True) -> Dict[str, Any]:
        """Configure contract leverage for a trading pair."""
        payload = {"symbol": symbol, "leverage": str(leverage)}
        return self._request("POST", "/api/v3/trade/leverage", data=payload, is_contract=is_contract)

    def cancel_order(self, symbol: str, order_id: str, is_contract: bool = True) -> Dict[str, Any]:
        """Cancel an open order."""
        payload = {"symbol": symbol, "orderId": order_id}
        return self._request("POST", "/api/v3/trade/cancel", data=payload, is_contract=is_contract)

    def close(self):
        self.client.close()
