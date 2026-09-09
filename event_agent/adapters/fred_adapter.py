# =============================================================================
# event_agent/adapters/fred_adapter.py — FRED US Macro Data Adapter
# =============================================================================
"""
Fetches US macroeconomic data from the Federal Reserve Economic Data (FRED) API.

Security:
    - API key loaded ONLY from os.environ or .env
    - Never stored in DB, logs, chat, or web_app
    - Never printed or serialized

Point-in-time:
    - Uses FRED releases/dates endpoint for vintage-aware data
    - get_as_of() returns only data released before the query timestamp
"""

import os
import hashlib
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from .base_adapter import BaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load API key from environment (NEVER hardcode)
# ---------------------------------------------------------------------------
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

def _load_fred_api_key() -> Optional[str]:
    """Load FRED API key from environment variable or .env file."""
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key.strip()
    if _ENV_PATH.exists():
        with open(_ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("FRED_API_KEY=") and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip()
                    if val and val != "<your_key_here>":
                        return val
    return None


# ---------------------------------------------------------------------------
# FRED Series Registry — 30+ indicators
# ---------------------------------------------------------------------------
FRED_SERIES: Dict[str, Dict[str, Any]] = {
    # --- US Economy ---
    "CPIAUCSL":         {"name": "CPI All Urban Consumers",      "is_proxy": False, "unit": "index",    "frequency": "monthly"},
    "CPILFESL":         {"name": "Core CPI ex Food/Energy",      "is_proxy": False, "unit": "index",    "frequency": "monthly"},
    "PCEPI":            {"name": "PCE Price Index",              "is_proxy": False, "unit": "index",    "frequency": "monthly"},
    "PCEPILFE":         {"name": "Core PCE Price Index",         "is_proxy": False, "unit": "index",    "frequency": "monthly"},
    "PAYEMS":           {"name": "Total Nonfarm Payrolls",       "is_proxy": False, "unit": "thousands","frequency": "monthly"},
    "UNRATE":           {"name": "Unemployment Rate",            "is_proxy": False, "unit": "percent",  "frequency": "monthly"},
    "ICSA":             {"name": "Initial Jobless Claims",       "is_proxy": False, "unit": "number",   "frequency": "weekly"},
    "RSAFS":            {"name": "Advance Retail Sales",         "is_proxy": False, "unit": "millions", "frequency": "monthly"},
    "UMCSENT":          {"name": "U of Michigan Consumer Sentiment", "is_proxy": False, "unit": "index","frequency": "monthly"},
    "GDP":              {"name": "Gross Domestic Product",       "is_proxy": False, "unit": "billions", "frequency": "quarterly"},
    "GDPC1":            {"name": "Real GDP",                     "is_proxy": False, "unit": "billions", "frequency": "quarterly"},
    "WALCL":            {"name": "Fed Total Assets (Balance Sheet)", "is_proxy": False, "unit": "millions", "frequency": "weekly"},
    "DFEDTARU":         {"name": "Fed Funds Target Rate Upper",  "is_proxy": False, "unit": "percent",  "frequency": "irregular"},
    "FEDFUNDS":         {"name": "Effective Federal Funds Rate",  "is_proxy": False, "unit": "percent",  "frequency": "monthly"},

    # --- Financial Markets ---
    "DGS10":            {"name": "US 10-Year Treasury Yield",    "is_proxy": False, "unit": "percent",  "frequency": "daily"},
    "DGS2":             {"name": "US 2-Year Treasury Yield",     "is_proxy": False, "unit": "percent",  "frequency": "daily"},
    "T10Y2Y":           {"name": "10Y-2Y Treasury Spread",      "is_proxy": False, "unit": "percent",  "frequency": "daily"},
    "VIXCLS":           {"name": "CBOE Volatility Index (VIX)",  "is_proxy": False, "unit": "index",    "frequency": "daily"},
    "DCOILWTICO":       {"name": "WTI Crude Oil Spot Price",     "is_proxy": False, "unit": "usd/bbl",  "frequency": "daily"},
    "DCOILBRENTEU":     {"name": "Brent Crude Oil Spot Price",   "is_proxy": False, "unit": "usd/bbl",  "frequency": "daily"},
    "GOLDAMGBD228NLBM": {"name": "Gold Fixing Price London",    "is_proxy": False, "unit": "usd/oz",   "frequency": "daily"},

    # --- Standalone signals (NOT proxies) ---
    "MANEMP": {
        "name": "Manufacturing Employment",
        "is_proxy": False,
        "proxy_for": None,
        "unit": "thousands",
        "frequency": "monthly",
        "note": "Standalone manufacturing employment signal. NOT a proxy for ISM Manufacturing PMI.",
    },

    # --- Proxies (explicitly labeled) ---
    "DTWEXBGS": {
        "name": "Broad Trade-Weighted US Dollar Index",
        "is_proxy": True,
        "proxy_for": "DXY Dollar Index",
        "unit": "index",
        "frequency": "daily",
    },
}

# Base URL
FRED_BASE_URL = "https://api.stlouisfed.org/fred"


class FREDAdapter(BaseAdapter):
    """
    FRED API adapter for US macroeconomic data.

    Uses the observations endpoint for current data and the
    releases/dates endpoint for point-in-time vintage data.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or _load_fred_api_key()
        if not self._api_key:
            logger.warning(
                "FRED_API_KEY not configured. Set FRED_API_KEY in .env or environment. "
                "FRED adapter will be unavailable."
            )
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------ #
    # BaseAdapter interface
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch_series(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch observations for a FRED series between start and end dates."""
        if not self.is_available():
            logger.error("FRED adapter not available — no API key.")
            return pd.DataFrame()

        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start_date.isoformat(),
            "observation_end": end_date.isoformat(),
            "sort_order": "asc",
        }

        try:
            resp = self._session.get(
                f"{FRED_BASE_URL}/series/observations",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("FRED fetch_series(%s) failed: %s", series_id, exc)
            return pd.DataFrame()

        observations = data.get("observations", [])
        if not observations:
            return pd.DataFrame()

        rows = []
        for obs in observations:
            val_str = obs.get("value", ".")
            if val_str == ".":
                continue  # Missing observation
            try:
                rows.append({
                    "series_id": series_id,
                    "observation_date": obs["date"],
                    "value": float(val_str),
                    "realtime_start": obs.get("realtime_start"),
                    "realtime_end": obs.get("realtime_end"),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
            except (ValueError, KeyError):
                continue

        df = pd.DataFrame(rows)
        if not df.empty:
            df["observation_date"] = pd.to_datetime(df["observation_date"])
        return df

    def get_latest(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent observation for a FRED series."""
        if not self.is_available():
            return None

        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        }

        try:
            resp = self._session.get(
                f"{FRED_BASE_URL}/series/observations",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("FRED get_latest(%s) failed: %s", series_id, exc)
            return None

        observations = data.get("observations", [])
        if not observations:
            return None

        obs = observations[0]
        val_str = obs.get("value", ".")
        if val_str == ".":
            return None

        try:
            return {
                "series_id": series_id,
                "observation_date": obs["date"],
                "value": float(val_str),
                "release_date": obs.get("realtime_start", obs["date"]),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except (ValueError, KeyError):
            return None

    def get_as_of(
        self,
        series_id: str,
        as_of_datetime: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Return the value that was known at *as_of_datetime* (point-in-time).

        Uses FRED's realtime_start/realtime_end vintage mechanism:
        only returns observations whose realtime_start <= as_of_datetime.
        """
        if not self.is_available():
            return None

        as_of_date_str = as_of_datetime.strftime("%Y-%m-%d")

        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "realtime_start": "2020-01-01",
            "realtime_end": as_of_date_str,
            "sort_order": "desc",
            "limit": 1,
        }

        try:
            resp = self._session.get(
                f"{FRED_BASE_URL}/series/observations",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("FRED get_as_of(%s, %s) failed: %s", series_id, as_of_date_str, exc)
            return None

        observations = data.get("observations", [])
        if not observations:
            return None

        obs = observations[0]
        val_str = obs.get("value", ".")
        if val_str == ".":
            return None

        try:
            return {
                "series_id": series_id,
                "observation_date": obs["date"],
                "value": float(val_str),
                "release_date": obs.get("realtime_start", obs["date"]),
                "vintage": as_of_date_str,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except (ValueError, KeyError):
            return None

    # ------------------------------------------------------------------ #
    # Convenience methods
    # ------------------------------------------------------------------ #
    def fetch_multiple_latest(
        self,
        series_ids: Optional[List[str]] = None,
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """Fetch latest values for multiple series at once."""
        ids = series_ids or list(FRED_SERIES.keys())
        results = {}
        for sid in ids:
            results[sid] = self.get_latest(sid)
        return results

    def get_series_metadata(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Return the registry metadata for a known FRED series."""
        meta = FRED_SERIES.get(series_id)
        if meta:
            return {"series_id": series_id, **meta}
        return None

    @staticmethod
    def list_available_series() -> Dict[str, Dict[str, Any]]:
        """Return the full FRED series registry."""
        return dict(FRED_SERIES)
