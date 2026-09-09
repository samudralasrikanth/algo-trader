# =============================================================================
# event_agent/engine/regime_detector.py — 8-Dimension Regime Engine
# =============================================================================
"""
8-dimension regime model with FROZEN weights.

Dimensions:
    1. Risk       — VIX, FII flows, DXY
    2. Monetary   — Fed funds, US 10Y, RBI repo
    3. Inflation  — CPI surprise, crude, gold
    4. Growth     — GDP, PMI, jobless claims
    5. Liquidity  — Fed balance sheet, RBI LAF, credit growth
    6. Volatility — India VIX, realized vol
    7. Geopolitical — news sentiment score (LLM-derived text)
    8. Earnings   — beat/miss ratio

Weights are FROZEN at V1.0. Any modification requires:
    1. Candidate weights proposed by learning loop
    2. Walk-forward OOS validation
    3. Approval gate (human review)
    4. Version bump
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FROZEN INITIAL WEIGHTS — Version W1.0
# DO NOT MODIFY without walk-forward OOS validation + approval gate
# ---------------------------------------------------------------------------
REGIME_WEIGHTS_V1: Dict[str, Dict[str, float]] = {
    "risk": {
        "vix_weight": 0.4,
        "fii_weight": 0.3,
        "dxy_weight": 0.3,
    },
    "monetary": {
        "fed_funds_weight": 0.4,
        "us10y_weight": 0.3,
        "rbi_repo_weight": 0.3,
    },
    "inflation": {
        "cpi_surprise_weight": 0.5,
        "crude_weight": 0.3,
        "gold_weight": 0.2,
    },
    "growth": {
        "gdp_weight": 0.3,
        "pmi_weight": 0.4,
        "claims_weight": 0.3,
    },
    "liquidity": {
        "fed_bs_weight": 0.4,
        "rbi_laf_weight": 0.3,
        "credit_weight": 0.3,
    },
    "volatility": {
        "india_vix_weight": 0.5,
        "realized_vol_weight": 0.5,
    },
    "geopolitical": {
        "news_score_weight": 1.0,
    },
    "earnings": {
        "beat_miss_ratio_weight": 1.0,
    },
}
WEIGHTS_VERSION = "W1.0"

# Regime classification thresholds
REGIME_THRESHOLDS = {
    "risk":        {"RISK_OFF": -0.3, "NEUTRAL": 0.3, "RISK_ON": float("inf")},
    "monetary":    {"DOVISH": -0.3, "NEUTRAL": 0.3, "HAWKISH": float("inf")},
    "inflation":   {"DEFLATIONARY": -0.3, "STABLE": 0.3, "HOT": float("inf")},
    "growth":      {"CONTRACTING": -0.3, "STABLE": 0.3, "EXPANDING": float("inf")},
    "liquidity":   {"TIGHT": -0.3, "NEUTRAL": 0.3, "LOOSE": float("inf")},
    "volatility":  {"LOW": -0.3, "NORMAL": 0.3, "ELEVATED": float("inf")},
    "geopolitical":{"CALM": -0.3, "NEUTRAL": 0.3, "STRESSED": float("inf")},
    "earnings":    {"MISS_HEAVY": -0.3, "MIXED": 0.3, "BEAT_HEAVY": float("inf")},
}

DIMENSIONS = list(REGIME_WEIGHTS_V1.keys())


def _classify_score(score: float, thresholds: Dict[str, float]) -> str:
    """Classify a dimension score into a regime label."""
    labels = list(thresholds.keys())
    bounds = list(thresholds.values())
    for label, upper_bound in zip(labels, bounds):
        if score <= upper_bound:
            return label
    return labels[-1]


def _extract_dimension_inputs(
    market_state: Dict[str, Any],
    features: Dict[str, Any],
    dimension: str,
) -> Dict[str, Optional[float]]:
    """Extract raw inputs for a regime dimension from market state."""
    us_macro = market_state.get("us_macro", {})
    india_macro = market_state.get("india_macro", {})
    volatility_data = features.get("volatility", {})
    surprise_data = features.get("macro_surprises", {})
    commodity_data = features.get("commodities", {})

    if dimension == "risk":
        vix_val = us_macro.get("VIXCLS", {}).get("value")
        # Normalize VIX: >30 = risk_off, 15-20 = neutral, <15 = risk_on
        vix_score = None
        if vix_val is not None:
            if vix_val > 30:
                vix_score = -1.0
            elif vix_val > 20:
                vix_score = -0.5 + (30 - vix_val) / 20
            elif vix_val > 15:
                vix_score = (20 - vix_val) / 10
            else:
                vix_score = 1.0
        return {
            "vix": vix_score,
            "fii": None,  # Will come from FII/DII flow data
            "dxy": None,  # Will come from DXY proxy
        }

    elif dimension == "monetary":
        fed_funds = us_macro.get("FEDFUNDS", {}).get("value")
        us10y = us_macro.get("DGS10", {}).get("value")
        rbi_repo = india_macro.get("RBI_REPO_RATE", {}).get("value")
        return {
            "fed_funds": _normalize_rate(fed_funds, center=5.0, scale=2.0),
            "us10y": _normalize_rate(us10y, center=4.0, scale=1.5),
            "rbi_repo": _normalize_rate(rbi_repo, center=6.0, scale=1.0),
        }

    elif dimension == "inflation":
        cpi_surprise = surprise_data.get("composite_surprise", 0)
        crude = commodity_data.get("wti_crude")
        gold = commodity_data.get("gold")
        return {
            "cpi_surprise": cpi_surprise if cpi_surprise else 0,
            "crude": _normalize_commodity(crude, center=75.0, scale=20.0) if crude else 0,
            "gold": _normalize_commodity(gold, center=2000.0, scale=300.0) if gold else 0,
        }

    elif dimension == "growth":
        return {
            "gdp": None,     # From GDP surprise when available
            "pmi": None,     # From PMI surprise when available
            "claims": None,  # From jobless claims trend
        }

    elif dimension == "liquidity":
        return {
            "fed_bs": None,  # From Fed balance sheet trend
            "rbi_laf": None, # From RBI LAF
            "credit": None,  # From India credit growth
        }

    elif dimension == "volatility":
        india_vix = volatility_data.get("india_vix")
        realized = volatility_data.get("nifty_realized_vol_20d")
        return {
            "india_vix": _normalize_vix(india_vix) if india_vix else 0,
            "realized_vol": _normalize_vol(realized) if realized else 0,
        }

    elif dimension == "geopolitical":
        return {"news_score": 0}  # From LLM-interpreted news sentiment

    elif dimension == "earnings":
        return {"beat_miss_ratio": 0}  # From earnings beat/miss data

    return {}


def _normalize_rate(value, center, scale):
    if value is None:
        return 0
    return (value - center) / scale


def _normalize_commodity(value, center, scale):
    if value is None:
        return 0
    return (value - center) / scale


def _normalize_vix(vix):
    if vix is None:
        return 0
    # India VIX: <12 = low, 12-18 = normal, >18 = elevated
    return (vix - 15) / 6


def _normalize_vol(vol):
    if vol is None:
        return 0
    return (vol - 15) / 5


def detect_regime(
    market_state: Dict[str, Any],
    features: Dict[str, Any],
    weights: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """
    Detect the current 8-dimension regime.

    Returns:
        Dict with each dimension's raw values, normalized scores,
        composite score, and classification.
    """
    active_weights = weights or REGIME_WEIGHTS_V1
    result = {}

    for dimension in DIMENSIONS:
        # Extract raw inputs
        raw_values = _extract_dimension_inputs(market_state, features, dimension)

        # Compute weighted score
        weight_keys = list(active_weights.get(dimension, {}).keys())
        value_keys = list(raw_values.keys())

        weighted_sum = 0.0
        total_weight = 0.0

        for w_key, v_key in zip(weight_keys, value_keys):
            w = active_weights[dimension].get(w_key, 0)
            v = raw_values.get(v_key)
            if v is not None:
                weighted_sum += w * v
                total_weight += w

        dimension_score = weighted_sum / total_weight if total_weight > 0 else 0.0

        # Classify
        thresholds = REGIME_THRESHOLDS.get(dimension, {})
        classification = _classify_score(dimension_score, thresholds)

        result[dimension] = {
            "raw_values": raw_values,
            "dimension_score": round(dimension_score, 3),
            "state": classification,
            "has_data": total_weight > 0,
        }

    # Composite regime
    all_scores = [
        r["dimension_score"]
        for r in result.values()
        if r.get("has_data")
    ]

    composite_score = float(np.mean(all_scores)) if all_scores else 0.0
    data_coverage = sum(1 for r in result.values() if r.get("has_data")) / len(DIMENSIONS)

    if composite_score > 0.3:
        composite_regime = "BULLISH"
    elif composite_score < -0.3:
        composite_regime = "BEARISH"
    else:
        composite_regime = "NEUTRAL"

    result["composite_score"] = round(composite_score, 3)
    result["composite_regime"] = composite_regime
    result["confidence"] = round(min(data_coverage * 100, 100), 0)
    result["weights_version"] = WEIGHTS_VERSION
    result["dimensions_with_data"] = sum(1 for r in result.values() if isinstance(r, dict) and r.get("has_data"))
    result["total_dimensions"] = len(DIMENSIONS)

    return result
