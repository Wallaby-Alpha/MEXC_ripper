"""WEEX Contract Symbol Resolver & Precision Normalizer (V3 API Spec).

Automatically discovers WEEX's Contract V3 universe (~996 perpetuals)
and the official API-trading allowed symbols (~290 active pairs),
maps MEXC spot tickers (e.g., SUIUSDT, PEPEUSDT) to canonical WEEX V3 symbols (e.g., SUIUSDT, 1000PEPEUSDT),
and formats prices and order quantities according to WEEX pricePrecision and quantityPrecision rules.
"""
import logging
import re
from typing import Dict, Any, Optional, Set, List
import httpx

logger = logging.getLogger(__name__)


class WeexSymbolResolver:
    """Resolves MEXC spot tickers to WEEX canonical V3 perpetual contract symbols."""

    def __init__(
        self,
        exchange_info_url: str = "https://api-contract.weex.com/capi/v3/market/exchangeInfo",
        api_symbols_url: str = "https://api-contract.weex.com/capi/v3/market/apiTradingSymbols",
        timeout: float = 6.0,
        auto_fetch: bool = True,
    ):
        self.exchange_info_url = exchange_info_url
        self.api_symbols_url = api_symbols_url
        self.timeout = timeout
        self.contract_map: Dict[str, Dict[str, Any]] = {}
        self.alias_to_canonical: Dict[str, str] = {}
        self.api_allowed_symbols: Set[str] = set()
        if auto_fetch:
            self.refresh_contracts()

    def refresh_contracts(self):
        """Fetches active contract metadata and API-allowed pairs from WEEX V3 endpoints."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                # 1. Fetch API-supported trading symbols
                try:
                    res_syms = client.get(self.api_symbols_url)
                    if res_syms.status_code == 200:
                        raw_syms = res_syms.json()
                        if isinstance(raw_syms, list):
                            self.api_allowed_symbols = {str(s).strip().upper() for s in raw_syms}
                            logger.info("Loaded %d official WEEX API trading symbols.", len(self.api_allowed_symbols))
                except Exception as sym_err:
                    logger.warning("Could not fetch apiTradingSymbols (%s), allowing all active contracts.", sym_err)

                # 2. Fetch exchangeInfo with price and quantity precisions
                res_info = client.get(self.exchange_info_url)
                if res_info.status_code == 200:
                    data = res_info.json()
                    symbols_list = data.get("symbols", []) if isinstance(data, dict) else data
                    if isinstance(symbols_list, list) and symbols_list:
                        self._build_mappings(symbols_list)
                        logger.info("WEEX Symbol Resolver initialized with %d active contracts.", len(self.contract_map))
                        return

            logger.warning("WEEX public exchangeInfo returned unexpected payload, using fallback mapping.")
        except Exception as exc:
            logger.warning("Could not reach WEEX public endpoints (%s). Using fallback.", exc)

    def _build_mappings(self, contracts: list):
        self.contract_map.clear()
        self.alias_to_canonical.clear()

        for c in contracts:
            if not isinstance(c, dict):
                continue
            raw_sym = c.get("symbol", "").strip()
            if not raw_sym:
                continue

            # Strip legacy 'cmt_' if present to standardize on V3 uppercase
            canonical = raw_sym.replace("cmt_", "").upper()

            # Extract price precision (e.g. 4 for SUIUSDT, 1 for BTCUSDT)
            price_prec = c.get("pricePrecision")
            if price_prec is None:
                # Fallback to legacy tick_size if present
                tick = float(c.get("tick_size") or 0.0001)
                price_prec = int(tick) if tick >= 1.0 else (len(str(tick).split(".")[1]) if "." in str(tick) else 4)
            else:
                price_prec = int(price_prec)

            # Extract quantity precision (e.g. -1 for step 10, 4 for step 0.0001)
            qty_prec = c.get("quantityPrecision")
            if qty_prec is None:
                inc = float(c.get("size_increment") or 1.0)
                if inc >= 10:
                    qty_prec = -len(str(int(inc))) + 1
                elif inc == int(inc):
                    qty_prec = 0
                else:
                    inc_str = f"{inc:.8f}".rstrip("0")
                    qty_prec = len(inc_str.split(".")[1]) if "." in inc_str else 0
            else:
                qty_prec = int(qty_prec)

            min_sz = float(c.get("minOrderSize") or 1.0)
            if min_sz <= 0:
                min_sz = 1.0

            self.contract_map[canonical] = {
                "symbol": canonical,
                "price_precision": price_prec,
                "quantity_precision": qty_prec,
                "min_order_size": min_sz,
                "contract_val": float(c.get("contractVal") or c.get("contract_val") or 1.0),
            }

            # Build multi-key alias dictionary for robust lookup:
            # canonical: SUIUSDT
            # aliases: SUIUSDT, suiusdt, cmt_suiusdt, SUI_USDT, sui_usdt
            clean_lower = canonical.lower()
            self.alias_to_canonical[canonical] = canonical
            self.alias_to_canonical[clean_lower] = canonical
            self.alias_to_canonical[f"cmt_{clean_lower}"] = canonical
            self.alias_to_canonical[f"cmt_{canonical.lower()}"] = canonical
            self.alias_to_canonical[canonical.replace("USDT", "_USDT")] = canonical
            self.alias_to_canonical[clean_lower.replace("usdt", "_usdt")] = canonical

            # Handle 1000x multiplier tokens (e.g. 1000PEPEUSDT -> PEPEUSDT)
            if "1000" in canonical:
                without_1000 = canonical.replace("1000", "")
                without_1000_l = clean_lower.replace("1000", "")
                self.alias_to_canonical[without_1000] = canonical
                self.alias_to_canonical[without_1000_l] = canonical
                self.alias_to_canonical[f"cmt_{without_1000_l}"] = canonical
                self.alias_to_canonical[without_1000_l.replace("usdt", "_usdt")] = canonical

    def resolve(self, mexc_symbol: str) -> Optional[str]:
        """Resolves a MEXC symbol (e.g. 'SUIUSDT' or 'PEPEUSDT') to canonical WEEX V3 symbol (e.g. 'SUIUSDT' or '1000PEPEUSDT').

        Returns None if the coin is not listed or not supported for API trading on WEEX futures.
        """
        if not mexc_symbol:
            return None

        clean_upper = mexc_symbol.strip().upper().replace("/", "").replace("-", "")
        clean_lower = clean_upper.lower()

        resolved = None

        # 1. Exact alias match from live registry
        if clean_upper in self.alias_to_canonical:
            resolved = self.alias_to_canonical[clean_upper]
        elif clean_lower in self.alias_to_canonical:
            resolved = self.alias_to_canonical[clean_lower]
        # 2. Check 1000x multiplier variant (e.g. 'PEPEUSDT' -> '1000PEPEUSDT')
        elif f"1000{clean_upper}" in self.contract_map:
            resolved = f"1000{clean_upper}"
        # 3. Direct match in contract map
        elif clean_upper in self.contract_map:
            resolved = clean_upper

        if not resolved:
            return None

        # 4. Enforce WEEX API trading restriction check
        # WEEX API strictly returns [-1058] for any pair not in apiTradingSymbols
        if self.api_allowed_symbols and resolved not in self.api_allowed_symbols:
            logger.info("[WEEX API UNSUPPORTED] %s (%s) is not in WEEX's official apiTradingSymbols list. Skipping live execution.", mexc_symbol, resolved)
            return None

        return resolved

    def format_price(self, canonical_symbol: str, price: float) -> str:
        """Formats price respecting WEEX contract pricePrecision."""
        meta = self.contract_map.get(canonical_symbol.upper())
        decimals = int(meta.get("price_precision", 4)) if meta else 4
        return f"{price:.{decimals}f}"

    def format_size(self, canonical_symbol: str, raw_size: float) -> str:
        """Formats order size respecting WEEX quantityPrecision and minOrderSize."""
        meta = self.contract_map.get(canonical_symbol.upper())
        if not meta:
            return str(max(int(raw_size), 1))

        min_size = float(meta.get("min_order_size", 1.0))
        qty_prec = int(meta.get("quantity_precision", 0))

        # Respect exchange minOrderSize
        qty = max(float(raw_size), min_size)

        if qty_prec <= 0:
            step = 10 ** abs(qty_prec)
            rounded = int(round(qty / step) * step)
            final_qty = max(rounded, int(min_size))
            return str(final_qty)
        else:
            step = 10 ** (-qty_prec)
            rounded = round(round(qty / step) * step, qty_prec)
            final_qty = max(rounded, min_size)
            return f"{final_qty:.{qty_prec}f}"
