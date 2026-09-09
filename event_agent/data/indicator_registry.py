# =============================================================================
# event_agent/data/indicator_registry.py — Central Indicator Registry
# =============================================================================
"""
Central registry of all macroeconomic and market indicators.
Every indicator has metadata including:
    - source, series_id, semantic_name
    - is_proxy flag (and proxy_for if True)
    - frequency, unit, typical_surprise_std

MANEMP is a standalone MFG_EMPLOYMENT signal.
It is NOT a proxy for ISM Manufacturing PMI.
ISM PMI is a separate indicator not currently available from FRED.
"""

from typing import Any, Dict, Optional


INDICATOR_REGISTRY: Dict[str, Dict[str, Any]] = {
    # -----------------------------------------------------------------------
    # US Economy (from FRED)
    # -----------------------------------------------------------------------
    "US_CPI": {
        "series_id": "CPIAUCSL",
        "source": "FRED",
        "semantic_name": "US Consumer Price Index",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.15,
    },
    "US_CORE_CPI": {
        "series_id": "CPILFESL",
        "source": "FRED",
        "semantic_name": "US Core CPI (ex Food & Energy)",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.10,
    },
    "US_PCE": {
        "series_id": "PCEPI",
        "source": "FRED",
        "semantic_name": "US PCE Price Index",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.12,
    },
    "US_CORE_PCE": {
        "series_id": "PCEPILFE",
        "source": "FRED",
        "semantic_name": "US Core PCE Price Index",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.10,
    },
    "US_NFP": {
        "series_id": "PAYEMS",
        "source": "FRED",
        "semantic_name": "US Nonfarm Payrolls",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "thousands",
        "typical_surprise_std": 50.0,
    },
    "US_UNEMPLOYMENT": {
        "series_id": "UNRATE",
        "source": "FRED",
        "semantic_name": "US Unemployment Rate",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "percent",
        "typical_surprise_std": 0.10,
    },
    "US_JOBLESS_CLAIMS": {
        "series_id": "ICSA",
        "source": "FRED",
        "semantic_name": "US Initial Jobless Claims",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "weekly",
        "unit": "number",
        "typical_surprise_std": 10000.0,
    },
    "US_RETAIL_SALES": {
        "series_id": "RSAFS",
        "source": "FRED",
        "semantic_name": "US Advance Retail Sales",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "millions",
        "typical_surprise_std": 2000.0,
    },
    "US_CONSUMER_SENTIMENT": {
        "series_id": "UMCSENT",
        "source": "FRED",
        "semantic_name": "U of Michigan Consumer Sentiment",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 2.0,
    },
    "US_GDP": {
        "series_id": "GDP",
        "source": "FRED",
        "semantic_name": "US Gross Domestic Product (Nominal)",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "quarterly",
        "unit": "billions",
        "typical_surprise_std": 50.0,
    },
    "US_REAL_GDP": {
        "series_id": "GDPC1",
        "source": "FRED",
        "semantic_name": "US Real GDP",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "quarterly",
        "unit": "billions",
        "typical_surprise_std": 30.0,
    },
    "US_FED_BALANCE_SHEET": {
        "series_id": "WALCL",
        "source": "FRED",
        "semantic_name": "Federal Reserve Total Assets",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "weekly",
        "unit": "millions",
        "typical_surprise_std": 10000.0,
    },
    "US_FED_FUNDS_TARGET": {
        "series_id": "DFEDTARU",
        "source": "FRED",
        "semantic_name": "Fed Funds Target Rate (Upper Bound)",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "irregular",
        "unit": "percent",
        "typical_surprise_std": 0.25,
    },
    "US_FED_FUNDS_EFFECTIVE": {
        "series_id": "FEDFUNDS",
        "source": "FRED",
        "semantic_name": "Effective Federal Funds Rate",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "percent",
        "typical_surprise_std": 0.10,
    },

    # --- Standalone manufacturing signal (NOT ISM proxy) ---
    "MFG_EMPLOYMENT": {
        "series_id": "MANEMP",
        "source": "FRED",
        "semantic_name": "US Manufacturing Employment",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "thousands_of_persons",
        "typical_surprise_std": 15.0,
        "note": "Standalone signal. NOT a proxy for ISM Manufacturing PMI.",
    },

    # -----------------------------------------------------------------------
    # Financial Markets (from FRED)
    # -----------------------------------------------------------------------
    "US_10Y_YIELD": {
        "series_id": "DGS10",
        "source": "FRED",
        "semantic_name": "US 10-Year Treasury Yield",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "percent",
        "typical_surprise_std": 0.05,
    },
    "US_2Y_YIELD": {
        "series_id": "DGS2",
        "source": "FRED",
        "semantic_name": "US 2-Year Treasury Yield",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "percent",
        "typical_surprise_std": 0.05,
    },
    "US_YIELD_SPREAD": {
        "series_id": "T10Y2Y",
        "source": "FRED",
        "semantic_name": "US 10Y-2Y Treasury Yield Spread",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "percent",
        "typical_surprise_std": 0.05,
    },
    "VIX": {
        "series_id": "VIXCLS",
        "source": "FRED",
        "semantic_name": "CBOE Volatility Index (VIX)",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "index",
        "typical_surprise_std": 2.0,
    },
    "WTI_CRUDE": {
        "series_id": "DCOILWTICO",
        "source": "FRED",
        "semantic_name": "WTI Crude Oil Spot Price",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "usd_per_barrel",
        "typical_surprise_std": 2.0,
    },
    "BRENT_CRUDE": {
        "series_id": "DCOILBRENTEU",
        "source": "FRED",
        "semantic_name": "Brent Crude Oil Spot Price",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "usd_per_barrel",
        "typical_surprise_std": 2.0,
    },
    "GOLD": {
        "series_id": "GOLDAMGBD228NLBM",
        "source": "FRED",
        "semantic_name": "Gold Price (London Fixing)",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "usd_per_troy_ounce",
        "typical_surprise_std": 20.0,
    },

    # --- Proxy (explicitly labeled) ---
    "DXY_PROXY": {
        "series_id": "DTWEXBGS",
        "source": "FRED",
        "semantic_name": "Broad Trade-Weighted US Dollar Index",
        "is_proxy": True,
        "proxy_for": "DXY Dollar Index",
        "frequency": "daily",
        "unit": "index",
        "typical_surprise_std": 0.5,
    },

    # -----------------------------------------------------------------------
    # India Macro (from RBI/MOSPI)
    # -----------------------------------------------------------------------
    "INDIA_CPI": {
        "series_id": "INDIA_CPI",
        "source": "MOSPI",
        "semantic_name": "India Consumer Price Index (YoY %)",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "percent_yoy",
        "typical_surprise_std": 0.20,
    },
    "INDIA_GDP": {
        "series_id": "INDIA_GDP",
        "source": "MOSPI",
        "semantic_name": "India GDP Growth (YoY %)",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "quarterly",
        "unit": "percent_yoy",
        "typical_surprise_std": 0.50,
    },
    "RBI_REPO_RATE": {
        "series_id": "RBI_REPO_RATE",
        "source": "RBI",
        "semantic_name": "RBI Policy Repo Rate",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "event_driven",
        "unit": "percent",
        "typical_surprise_std": 0.25,
    },
    "INDIA_PMI_MFG": {
        "series_id": "INDIA_PMI_MFG",
        "source": "S&P_Global",
        "semantic_name": "India Manufacturing PMI",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.8,
    },
    "INDIA_PMI_SVC": {
        "series_id": "INDIA_PMI_SVC",
        "source": "S&P_Global",
        "semantic_name": "India Services PMI",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "monthly",
        "unit": "index",
        "typical_surprise_std": 0.8,
    },

    # -----------------------------------------------------------------------
    # Market Instruments (from yfinance)
    # -----------------------------------------------------------------------
    "NIFTY_50": {
        "series_id": "^NSEI",
        "source": "yfinance",
        "semantic_name": "Nifty 50 Index",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "index_points",
    },
    "INDIA_VIX": {
        "series_id": "^INDIAVIX",
        "source": "yfinance",
        "semantic_name": "India Volatility Index",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "index",
    },
    "USDINR": {
        "series_id": "USDINR=X",
        "source": "yfinance",
        "semantic_name": "USD/INR Exchange Rate",
        "is_proxy": False,
        "proxy_for": None,
        "frequency": "daily",
        "unit": "inr_per_usd",
    },
}


def get_indicator(indicator_id: str) -> Optional[Dict[str, Any]]:
    """Look up an indicator by its registry ID."""
    meta = INDICATOR_REGISTRY.get(indicator_id)
    if meta:
        return {"indicator_id": indicator_id, **meta}
    return None


def get_indicators_by_source(source: str) -> Dict[str, Dict[str, Any]]:
    """Get all indicators from a specific source (FRED, RBI, yfinance, etc.)."""
    return {
        k: v for k, v in INDICATOR_REGISTRY.items()
        if v.get("source") == source
    }


def get_proxies() -> Dict[str, Dict[str, Any]]:
    """Get all proxy indicators (explicitly labeled)."""
    return {
        k: v for k, v in INDICATOR_REGISTRY.items()
        if v.get("is_proxy", False)
    }


def list_all_indicators() -> Dict[str, Dict[str, Any]]:
    """Return the full indicator registry."""
    return dict(INDICATOR_REGISTRY)
