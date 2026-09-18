"""Resilient HTTP client for MEXC public REST endpoints."""
import time
import logging
from typing import List, Dict, Any, Optional
import httpx

from config import (
    MEXC_SPOT_BASE_URL,
    MEXC_CONTRACT_BASE_URL,
    DEFAULT_REQUEST_TIMEOUT,
    MAX_RETRIES,
    BACKOFF_FACTOR,
)

logger = logging.getLogger(__name__)


class MexcRateLimitError(Exception):
    pass


class MexcAPIError(Exception):
    pass


class MexcClient:
    """Handles communication with MEXC public API with rate limit safety and exponential retries."""

    def __init__(
        self,
        spot_base_url: str = MEXC_SPOT_BASE_URL,
        contract_base_url: str = MEXC_CONTRACT_BASE_URL,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ):
        self.spot_base_url = spot_base_url.rstrip("/")
        self.contract_base_url = contract_base_url.rstrip("/")
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "MEXC-Momentum-Scanner/1.0", "Accept": "application/json"},
        )
        self._last_request_time = 0.0
        self._min_interval = 0.05  # 50ms between calls to avoid bursting

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._throttle()
        retries = 0
        backoff = BACKOFF_FACTOR

        while retries <= MAX_RETRIES:
            try:
                response = self.client.request(method, url, params=params)

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", backoff * (2**retries)))
                    logger.warning("MEXC 429 Rate Limit hit. Sleeping %.2f seconds...", retry_after)
                    time.sleep(retry_after)
                    retries += 1
                elif response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        "MEXC server error %d. Retrying in %.2f seconds...",
                        response.status_code,
                        backoff * (2**retries),
                    )
                    time.sleep(backoff * (2**retries))
                    retries += 1
                else:
                    response.raise_for_status()

            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                retries += 1
                if retries > MAX_RETRIES:
                    logger.error("MEXC API request failed after %d retries: %s", MAX_RETRIES, exc)
                    raise
                time.sleep(backoff * (2**retries))

        raise MexcAPIError(f"Failed request to {url} after {MAX_RETRIES} attempts.")

    # -------------------------------------------------------------
    # Spot Endpoints
    # -------------------------------------------------------------

    def get_exchange_info(self) -> Dict[str, Any]:
        """Fetch exchange trading rules and symbol universe."""
        url = f"{self.spot_base_url}/api/v3/exchangeInfo"
        return self._request("GET", url)

    def get_ticker_24hr(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch 24-hour rolling window price change statistics."""
        url = f"{self.spot_base_url}/api/v3/ticker/24hr"
        params = {"symbol": symbol} if symbol else None
        res = self._request("GET", url, params=params)
        return res if isinstance(res, list) else [res]

    def get_klines(
        self,
        symbol: str,
        interval: str = "5m",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> List[List[Any]]:
        """Fetch kline/candlestick bars for a symbol."""
        url = f"{self.spot_base_url}/api/v3/klines"
        params: Dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        res = self._request("GET", url, params=params)
        return res if isinstance(res, list) else []

    def paginate_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> List[List[Any]]:
        """Paginate klines across [start_time, end_time] in chunks of 1000 bars."""
        all_bars: List[List[Any]] = []
        current_start = start_time

        # Interval duration in milliseconds
        interval_ms_map = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        bar_ms = interval_ms_map.get(interval, 300_000)

        while current_start <= end_time:
            batch = self.get_klines(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_time,
                limit=1000,
            )
            if not batch:
                break

            all_bars.extend(batch)
            last_open = int(batch[-1][0])
            next_start = last_open + bar_ms

            if next_start <= current_start or last_open >= end_time:
                break
            current_start = next_start

        # Deduplicate by open_time
        seen = set()
        deduped = []
        for b in all_bars:
            ot = int(b[0])
            if ot not in seen:
                seen.add(ot)
                deduped.append(b)

        return sorted(deduped, key=lambda x: int(x[0]))

    def get_agg_trades(
        self,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Get aggregate market trades."""
        url = f"{self.spot_base_url}/api/v3/aggTrades"
        params: Dict[str, Any] = {"symbol": symbol, "limit": min(limit, 1000)}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        res = self._request("GET", url, params=params)
        return res if isinstance(res, list) else []

    def paginate_agg_trades(
        self,
        symbol: str,
        start_time: int,
        end_time: int,
        max_trades: int = 10_000,
    ) -> List[Dict[str, Any]]:
        """Paginate aggregate trades for CVD calculations."""
        all_trades: List[Dict[str, Any]] = []
        current_start = start_time

        while current_start <= end_time and len(all_trades) < max_trades:
            batch = self.get_agg_trades(
                symbol=symbol,
                start_time=current_start,
                end_time=end_time,
                limit=1000,
            )
            if not batch:
                break

            all_trades.extend(batch)
            last_time = int(batch[-1]["T"])
            if last_time <= current_start or len(batch) < 1000:
                break
            current_start = last_time + 1

        return all_trades

    # -------------------------------------------------------------
    # Contract / Futures Endpoints (Optional/Secondary)
    # -------------------------------------------------------------

    def get_funding_rate_history(
        self, symbol: str, page_num: int = 1, page_size: int = 20
    ) -> List[Dict[str, Any]]:
        """Fetch funding rate history for contract/futures pairs (e.g. BTC_USDT)."""
        url = f"{self.contract_base_url}/api/v1/contract/funding_rate/history"
        # MEXC contract symbol usually formatted as BASE_USDT
        contract_sym = symbol if "_" in symbol else symbol.replace("USDT", "_USDT")
        params = {"symbol": contract_sym, "page_num": page_num, "page_size": page_size}
        try:
            res = self._request("GET", url, params=params)
            if isinstance(res, dict) and res.get("success"):
                return res.get("data", {}).get("resultList", [])
            return []
        except Exception as exc:
            logger.debug("Funding rate lookup skipped for %s: %s", symbol, exc)
            return []

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
