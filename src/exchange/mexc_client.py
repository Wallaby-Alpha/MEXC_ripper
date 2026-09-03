import asyncio
from typing import Any, Dict, List, Optional
import aiohttp
import pandas as pd
from src.config import MexcConfig
from src.logger import get_logger

logger = get_logger("mexc_client")


class MexcClient:
    """Async client for MEXC Spot Market API with concurrency limiting and retry handling."""

    def __init__(self, config: MexcConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["X-MEXC-APIKEY"] = self.config.api_key
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_24hr_tickers(self) -> List[Dict[str, Any]]:
        """Fetch 24-hour ticker price change statistics for all spot markets."""
        url = f"{self.base_url}/api/v3/ticker/24hr"
        session = await self._get_session()
        async with self.semaphore:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data if isinstance(data, list) else [data]
                    else:
                        text = await response.text()
                        logger.error("Failed to fetch 24hr tickers: HTTP %d %s", response.status, text)
                        return []
            except Exception as e:
                logger.error("Exception fetching 24hr tickers: %s", str(e))
                return []

    async def get_klines(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch klines/candlestick bars for a symbol and return as a structured DataFrame.
        
        MEXC Klines response format:
        [
            [
                1499040000000,      // Open time
                "0.01634790",       // Open
                "0.80000000",       // High
                "0.01575800",       // Low
                "0.01577100",       // Close
                "148976.11427815",  // Volume
                1499644799999,      // Close time
                "2434.19055334"     // Quote asset volume
            ]
        ]
        """
        url = f"{self.base_url}/api/v3/klines"
        params: Dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        session = await self._get_session()
        async with self.semaphore:
            try:
                if self.config.request_delay_ms > 0:
                    await asyncio.sleep(self.config.request_delay_ms / 1000.0)

                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        raw = await response.json()
                        if not raw or not isinstance(raw, list):
                            return None

                        # Columns: open_time, open, high, low, close, volume, close_time, quote_volume
                        df = pd.DataFrame(
                            raw,
                            columns=[
                                "open_time",
                                "open",
                                "high",
                                "low",
                                "close",
                                "volume",
                                "close_time",
                                "quote_volume",
                            ],
                        )

                        # Cast types
                        numeric_cols = ["open", "high", "low", "close", "volume", "quote_volume"]
                        for col in numeric_cols:
                            df[col] = pd.to_numeric(df[col], errors="coerce")

                        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
                        df["close_time"] = pd.to_numeric(df["close_time"], errors="coerce")
                        return df
                    else:
                        text = await response.text()
                        logger.warning("Failed klines for %s %s: HTTP %d %s", symbol, interval, response.status, text)
                        return None
            except Exception as e:
                logger.error("Exception fetching klines for %s %s: %s", symbol, interval, str(e))
                return None

    async def get_multi_timeframe_klines(
        self, symbol: str
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch 1h, 15m, and 5m klines concurrently for a single symbol."""
        t_1h, t_15m, t_5m = await asyncio.gather(
            self.get_klines(symbol, interval="1h", limit=self.config.kline_limit_1h),
            self.get_klines(symbol, interval="15m", limit=self.config.kline_limit_15m),
            self.get_klines(symbol, interval="5m", limit=self.config.kline_limit_5m),
            return_exceptions=True,
        )

        return {
            "1h": t_1h if isinstance(t_1h, pd.DataFrame) else None,
            "15m": t_15m if isinstance(t_15m, pd.DataFrame) else None,
            "5m": t_5m if isinstance(t_5m, pd.DataFrame) else None,
        }
