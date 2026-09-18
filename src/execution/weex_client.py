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
        return response.json()

    # ------------------------------------------------------------------------
    # Public & Account Endpoints
    # ------------------------------------------------------------------------

    def get_server_time(self) -> int:
        """Fetch WEEX server timestamp."""
        res = self._request("GET", "/api/v3/public/time", is_contract=True)
        return int(res.get("data", {}).get("serverTime", time.time() * 1000))

    def get_account_assets(self, is_contract: bool = True) -> Dict[str, Any]:
        """Fetch account balance and available equity."""
        return self._request("GET", "/api/v3/account/assets", is_contract=is_contract)

    # ------------------------------------------------------------------------
    # Trade Execution Endpoints
    # ------------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,  # 'open_long', 'open_short', 'close_long', 'close_short'
        order_type: str = "market",  # 'market' or 'limit'
        size: float = 1.0,
        price: Optional[float] = None,
        is_contract: bool = True,
    ) -> Dict[str, Any]:
        """Place order on WEEX."""
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "size": str(size),
        }
        if price is not None and order_type == "limit":
            payload["price"] = str(price)

        return self._request("POST", "/api/v3/trade/order", data=payload, is_contract=is_contract)

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
