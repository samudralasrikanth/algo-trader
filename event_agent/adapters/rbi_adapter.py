# =============================================================================
# event_agent/adapters/rbi_adapter.py — RBI / India Macro Data Adapter
# =============================================================================
"""
Fetches Indian macroeconomic data from public RBI/MOSPI sources.

Sources:
    - RBI DBIE (Database on Indian Economy) — public tables
    - MOSPI — CPI, IIP, GDP releases
    - S&P Global — PMI summaries (free, publicly available)

For Phase 1: uses a combination of scraping and manually maintained
reference data where official APIs are unavailable.
"""

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .base_adapter import BaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# India Macro Indicator Registry
# ---------------------------------------------------------------------------
INDIA_INDICATORS: Dict[str, Dict[str, Any]] = {
    "RBI_REPO_RATE": {
        "name": "RBI Repo Rate",
        "source": "RBI",
        "frequency": "event_driven",
        "unit": "percent",
        "current_value": 6.00,
        "last_updated": "2025-04-09",
        "note": "Updated on RBI MPC announcement dates",
    },
    "RBI_STANCE": {
        "name": "RBI Monetary Policy Stance",
        "source": "RBI",
        "frequency": "bi_monthly",
        "unit": "categorical",
        "current_value": "accommodative",
        "last_updated": "2025-04-09",
    },
    "INDIA_CPI": {
        "name": "India Consumer Price Index (YoY %)",
        "source": "MOSPI",
        "frequency": "monthly",
        "unit": "percent_yoy",
        "typical_surprise_std": 0.20,
    },
    "INDIA_CORE_CPI": {
        "name": "India Core CPI (ex Food/Fuel, YoY %)",
        "source": "MOSPI_derived",
        "frequency": "monthly",
        "unit": "percent_yoy",
        "typical_surprise_std": 0.15,
    },
    "INDIA_IIP": {
        "name": "India Index of Industrial Production (YoY %)",
        "source": "MOSPI",
        "frequency": "monthly",
        "unit": "percent_yoy",
        "typical_surprise_std": 1.5,
    },
    "INDIA_GDP": {
        "name": "India GDP Growth (YoY %)",
        "source": "MOSPI",
        "frequency": "quarterly",
        "unit": "percent_yoy",
        "typical_surprise_std": 0.5,
    },
    "INDIA_PMI_MFG": {
        "name": "India Manufacturing PMI",
        "source": "S&P_Global",
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.8,
    },
    "INDIA_PMI_SVC": {
        "name": "India Services PMI",
        "source": "S&P_Global",
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.8,
    },
    "INDIA_CREDIT_GROWTH": {
        "name": "India Bank Credit Growth (YoY %)",
        "source": "RBI",
        "frequency": "bi_weekly",
        "unit": "percent_yoy",
    },
    "INDIA_LAF_LIQUIDITY": {
        "name": "RBI LAF Net Liquidity (₹ Cr)",
        "source": "RBI",
        "frequency": "daily",
        "unit": "crore_inr",
    },
}

# Path to manually maintained reference data
_REFERENCE_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "india_macro_reference.json"


class RBIAdapter(BaseAdapter):
    """
    India macroeconomic data adapter.

    Phase 1 implementation: primarily uses manually maintained reference
    data (JSON) supplemented by live scraping where possible.
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "NiftyEventAgent/3.0 (Research)",
            "Accept": "text/html,application/json",
        })
        self._reference_data = self._load_reference_data()

    def _load_reference_data(self) -> Dict[str, Any]:
        """Load manually maintained India macro reference data."""
        if _REFERENCE_DATA_PATH.exists():
            try:
                with open(_REFERENCE_DATA_PATH, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as exc:
                logger.warning("Failed to load India macro reference: %s", exc)
        return {}

    def _save_reference_data(self) -> None:
        """Persist reference data to disk."""
        _REFERENCE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_REFERENCE_DATA_PATH, "w") as f:
            json.dump(self._reference_data, f, indent=2, default=str)

    # ------------------------------------------------------------------ #
    # BaseAdapter interface
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        """Always available — falls back to reference data."""
        return True

    def fetch_series(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch historical observations from reference data."""
        history = self._reference_data.get(series_id, {}).get("history", [])
        if not history:
            return pd.DataFrame()

        rows = []
        for entry in history:
            obs_date = entry.get("observation_date", "")
            if start_date.isoformat() <= obs_date <= end_date.isoformat():
                rows.append({
                    "series_id": series_id,
                    "observation_date": obs_date,
                    "value": entry.get("value"),
                    "release_date": entry.get("release_date", obs_date),
                    "source": entry.get("source", "manual"),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["observation_date"] = pd.to_datetime(df["observation_date"])
        return df

    def get_latest(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest value for an India macro indicator."""
        # Check reference data first
        ref = self._reference_data.get(series_id, {})
        history = ref.get("history", [])

        if history:
            latest = history[-1]
            return {
                "series_id": series_id,
                "observation_date": latest.get("observation_date"),
                "value": latest.get("value"),
                "release_date": latest.get("release_date", latest.get("observation_date")),
                "source": latest.get("source", "manual"),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        # Fallback to indicator registry defaults
        indicator = INDIA_INDICATORS.get(series_id)
        if indicator and "current_value" in indicator:
            return {
                "series_id": series_id,
                "observation_date": indicator.get("last_updated", date.today().isoformat()),
                "value": indicator["current_value"],
                "release_date": indicator.get("last_updated", date.today().isoformat()),
                "source": "indicator_registry_default",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        return None

    def get_as_of(
        self,
        series_id: str,
        as_of_datetime: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Return the value known at as_of_datetime (point-in-time)."""
        as_of_str = as_of_datetime.strftime("%Y-%m-%d")
        history = self._reference_data.get(series_id, {}).get("history", [])

        # Filter to observations released before as_of_datetime
        available = [
            h for h in history
            if h.get("release_date", h.get("observation_date", "")) <= as_of_str
        ]

        if not available:
            return None

        latest = available[-1]
        return {
            "series_id": series_id,
            "observation_date": latest.get("observation_date"),
            "value": latest.get("value"),
            "release_date": latest.get("release_date"),
            "vintage": as_of_str,
            "source": latest.get("source", "manual"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------ #
    # Manual data entry (for Phase 1)
    # ------------------------------------------------------------------ #
    def record_observation(
        self,
        series_id: str,
        observation_date: str,
        value: float,
        release_date: Optional[str] = None,
        source: str = "manual",
    ) -> None:
        """
        Record a new observation in the reference data.
        Used for manual data entry in Phase 1.
        """
        if series_id not in self._reference_data:
            self._reference_data[series_id] = {"history": []}

        entry = {
            "observation_date": observation_date,
            "value": value,
            "release_date": release_date or observation_date,
            "source": source,
            "entered_at": datetime.now(timezone.utc).isoformat(),
        }

        self._reference_data[series_id]["history"].append(entry)
        # Keep sorted by observation_date
        self._reference_data[series_id]["history"].sort(
            key=lambda x: x["observation_date"]
        )
        self._save_reference_data()
        logger.info("Recorded %s = %s for %s", series_id, value, observation_date)

    # ------------------------------------------------------------------ #
    # Live scraping (where feasible)
    # ------------------------------------------------------------------ #
    def fetch_rbi_repo_rate(self) -> Optional[Dict[str, Any]]:
        """Attempt to scrape current RBI repo rate from public RBI page."""
        try:
            url = "https://www.rbi.org.in/scripts/BS_ViewBulletin.aspx"
            resp = self._session.get(url, timeout=15)
            if resp.status_code == 200:
                # Parse for repo rate — structure varies; fallback to reference
                logger.info("RBI page fetched, using reference data for reliability.")
        except requests.RequestException as exc:
            logger.debug("RBI scrape failed (expected): %s", exc)

        return self.get_latest("RBI_REPO_RATE")

    @staticmethod
    def list_available_indicators() -> Dict[str, Dict[str, Any]]:
        """Return the full India macro indicator registry."""
        return dict(INDIA_INDICATORS)
