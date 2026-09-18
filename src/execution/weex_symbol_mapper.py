"""WEEX Contract Symbol Resolver & Precision Normalizer.

Automatically discovers WEEX's contract universe (~1,000 perpetuals),
maps MEXC spot tickers (e.g., SUIUSDT, PEPEUSDT) to canonical WEEX symbols (e.g., cmt_suiusdt, cmt_1000pepeusdt),
and formats prices and sizes according to exchange tick size and lot increments.
"""
import logging
import re
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class WeexSymbolResolver:
    """Resolves MEXC spot tickers to WEEX canonical perpetual contract symbols."""

    def __init__(
        self,
        contracts_url: str = "https://api-contract.weex.com/capi/v2/market/contracts",
        timeout: float = 6.0,
        auto_fetch: bool = True,
    ):
        self.contracts_url = contracts_url
        self.timeout = timeout
        self.contract_map: Dict[str, Dict[str, Any]] = {}
        self.alias_to_canonical: Dict[str, str] = {}
        if auto_fetch:
            self.refresh_contracts()

    def refresh_contracts(self):
        """Fetches active contract metadata from WEEX public API."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(self.contracts_url)
                if res.status_code == 200:
                    contracts = res.json()
                    if isinstance(contracts, list):
                        self._build_mappings(contracts)
                        logger.info("WEEX Symbol Resolver initialized with %d active contracts.", len(self.contract_map))
                        return
            logger.warning("WEEX public contracts returned unexpected payload, using heuristic mapping.")
        except Exception as exc:
            logger.warning("Could not reach WEEX public contracts endpoint (%s). Using heuristic fallback.", exc)

    def _build_mappings(self, contracts: list):
        self.contract_map.clear()
        self.alias_to_canonical.clear()

        for c in contracts:
            if not isinstance(c, dict):
                continue
            canonical = c.get("symbol", "").strip().lower()
            if not canonical:
                continue

            try:
                tick = float(c.get("tick_size") or 0.0001)
            except (ValueError, TypeError):
                tick = 0.0001
            if tick <= 0:
                tick = 0.0001

            try:
                inc = float(c.get("size_increment") or 1.0)
            except (ValueError, TypeError):
                inc = 1.0
            if inc <= 0:
                inc = 1.0

            try:
                min_sz = float(c.get("minOrderSize") or 1.0)
            except (ValueError, TypeError):
                min_sz = 1.0
            if min_sz <= 0:
                min_sz = 1.0

            self.contract_map[canonical] = {
                "symbol": canonical,
                "tick_size": tick,
                "size_increment": inc,
                "min_order_size": min_sz,
                "contract_val": float(c.get("contract_val") or 1.0),
            }

            # Build alias keys:
            # e.g., 'cmt_suiusdt' -> 'suiusdt', 'sui_usdt', 'sui'
            clean = canonical.replace("cmt_", "")
            self.alias_to_canonical[canonical] = canonical
            self.alias_to_canonical[clean] = canonical
            self.alias_to_canonical[clean.replace("usdt", "_usdt")] = canonical
            self.alias_to_canonical[clean.replace("_", "")] = canonical

            # Handle 1000x multiplier tokens (e.g. 1000pepe -> pepe)
            if "1000" in clean:
                without_1000 = clean.replace("1000", "")
                self.alias_to_canonical[without_1000] = canonical
                self.alias_to_canonical[without_1000.replace("usdt", "_usdt")] = canonical

    def resolve(self, mexc_symbol: str) -> Optional[str]:
        """Resolves a MEXC symbol (e.g. 'SUIUSDT' or 'BTCUSDT') to WEEX canonical symbol (e.g. 'cmt_suiusdt').

        Returns None if the coin is not listed on WEEX futures.
        """
        if not mexc_symbol:
            return None

        clean = mexc_symbol.strip().lower().replace("/", "").replace("-", "")

        # 1. Exact alias match from live registry
        if clean in self.alias_to_canonical:
            return self.alias_to_canonical[clean]

        # 2. Check with 'cmt_' prefix
        cmt_key = f"cmt_{clean}"
        if cmt_key in self.contract_map:
            return cmt_key

        # 3. Check 1000x multiplier variant (e.g. 'PEPEUSDT' -> 'cmt_1000pepeusdt')
        multiplier_key = f"cmt_1000{clean}"
        if multiplier_key in self.contract_map:
            return multiplier_key

        # 4. If registry is populated, but symbol was not found, it is not listed on WEEX
        if self.contract_map:
            logger.info("Symbol %s is not tradeable as a perpetual contract on WEEX.", mexc_symbol)
            return None

        # 5. Offline Heuristic Fallback (if registry fetch failed)
        return f"cmt_{clean}"

    def format_price(self, canonical_symbol: str, price: float) -> str:
        """Formats price respecting WEEX contract tick size (decimal count or price increment)."""
        meta = self.contract_map.get(canonical_symbol)
        raw_tick = meta.get("tick_size", 4.0) if meta else 4.0

        # In WEEX API, tick_size is typically an integer specifying decimal places (e.g. 1 for BTC, 4 for SUI)
        if raw_tick >= 1.0:
            decimals = int(raw_tick)
            return f"{price:.{decimals}f}"

        # If tick_size is provided as a fractional increment (e.g. 0.0001)
        tick_str = f"{raw_tick:.8f}".rstrip("0")
        decimals = len(tick_str.split(".")[1]) if "." in tick_str else 4
        rounded_price = round(round(price / raw_tick) * raw_tick, decimals)
        return f"{rounded_price:.{decimals}f}"

    def format_size(self, canonical_symbol: str, raw_size: float) -> str:
        """Formats order size respecting WEEX lot size increments and minOrderSize."""
        meta = self.contract_map.get(canonical_symbol)
        increment = meta["size_increment"] if (meta and meta.get("size_increment", 0) > 0) else 1.0
        min_size = meta["min_order_size"] if (meta and meta.get("min_order_size", 0) > 0) else 1.0

        if raw_size < min_size:
            raw_size = min_size

        inc_str = f"{increment:.8f}".rstrip("0")
        decimals = len(inc_str.split(".")[1]) if "." in inc_str else 0

        rounded_size = round(round(raw_size / increment) * increment, decimals)
        if decimals == 0:
            return str(int(rounded_size))
        return f"{rounded_size:.{decimals}f}"
