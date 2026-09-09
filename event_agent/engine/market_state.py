# =============================================================================
# event_agent/engine/market_state.py — Comprehensive Market State Builder
# =============================================================================
"""
Builds a point-in-time market state snapshot from all adapters.
This is the input to the regime engine and prediction model.

Every field includes a computed_at timestamp for PIT verification.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MarketState:
    """
    Immutable market state snapshot at a specific point in time.
    Collected from FRED, RBI, yfinance, and economic calendar.
    """

    def __init__(self):
        self._state: Dict[str, Any] = {
            "snapshot_timestamp": None,
            "us_macro": {},
            "india_macro": {},
            "market_prices": {},
            "volatility": {},
            "fx": {},
            "commodities": {},
            "flows": {},
            "surprises": {},
            "events": [],
            "data_quality_warnings": [],
        }

    def build(
        self,
        fred_adapter=None,
        rbi_adapter=None,
        market_provider=None,
        economic_calendar=None,
        pit_store=None,
    ) -> Dict[str, Any]:
        """
        Build complete market state from all adapters.
        Each value includes computed_at for PIT verification.
        """
        now = datetime.now(timezone.utc)
        self._state["snapshot_timestamp"] = now.isoformat()

        # US Macro from FRED
        if fred_adapter and fred_adapter.is_available():
            key_series = [
                "CPIAUCSL", "PAYEMS", "UNRATE", "ICSA", "FEDFUNDS",
                "DGS10", "DGS2", "T10Y2Y", "VIXCLS",
                "DCOILWTICO", "GOLDAMGBD228NLBM", "WALCL",
            ]
            for sid in key_series:
                result = fred_adapter.get_latest(sid)
                if result:
                    result["computed_at"] = now.isoformat()
                    self._state["us_macro"][sid] = result

        # India Macro from RBI
        if rbi_adapter and rbi_adapter.is_available():
            for indicator_id in [
                "RBI_REPO_RATE", "RBI_STANCE", "INDIA_CPI",
                "INDIA_GDP", "INDIA_PMI_MFG", "INDIA_PMI_SVC",
            ]:
                result = rbi_adapter.get_latest(indicator_id)
                if result:
                    result["computed_at"] = now.isoformat()
                    self._state["india_macro"][indicator_id] = result

        # Market Prices from yfinance
        if market_provider:
            from ..adapters.market_data_adapter import MARKET_INSTRUMENTS
            for symbol, meta in MARKET_INSTRUMENTS.items():
                price = market_provider.get_current_price(symbol)
                if price is not None:
                    category = meta.get("type", "other")
                    entry = {
                        "symbol": symbol,
                        "name": meta["name"],
                        "price": price,
                        "type": category,
                        "computed_at": now.isoformat(),
                    }
                    if category == "volatility":
                        self._state["volatility"][symbol] = entry
                    elif category == "fx":
                        self._state["fx"][symbol] = entry
                    elif category == "commodity":
                        self._state["commodities"][symbol] = entry
                    else:
                        self._state["market_prices"][symbol] = entry

        # Recent surprises from calendar
        if economic_calendar:
            recent = economic_calendar.get_recent_surprises(limit=10)
            self._state["surprises"] = {
                "recent_events": recent,
                "count": len(recent),
                "computed_at": now.isoformat(),
            }

        # Pending releases
        if economic_calendar:
            pending = economic_calendar.get_pending_releases()
            self._state["events"] = pending

        return self._state

    def get_state(self) -> Dict[str, Any]:
        """Return the current state snapshot."""
        return dict(self._state)

    def get_value(self, path: str) -> Optional[Any]:
        """
        Get a value from the state using dot-separated path.
        Example: get_value("us_macro.DGS10.value")
        """
        parts = path.split(".")
        current = self._state
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current

    def to_snapshot_dict(self) -> Dict[str, Any]:
        """
        Serialize the full state for prediction_snapshot storage.
        This is what gets frozen at prediction lock time.
        """
        return {
            "snapshot_timestamp": self._state.get("snapshot_timestamp"),
            "us_macro": dict(self._state.get("us_macro", {})),
            "india_macro": dict(self._state.get("india_macro", {})),
            "market_prices": dict(self._state.get("market_prices", {})),
            "volatility": dict(self._state.get("volatility", {})),
            "fx": dict(self._state.get("fx", {})),
            "commodities": dict(self._state.get("commodities", {})),
            "flows": dict(self._state.get("flows", {})),
            "surprises": dict(self._state.get("surprises", {})),
            "events": list(self._state.get("events", [])),
            "data_quality_warnings_count": len(
                self._state.get("data_quality_warnings", [])
            ),
        }
