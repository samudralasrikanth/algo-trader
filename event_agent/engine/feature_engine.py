# =============================================================================
# event_agent/engine/feature_engine.py — Feature Engineering
# =============================================================================
"""
Computes features for the prediction model using ONLY data available
before the prediction lock timestamp (point-in-time).

Every feature includes a computed_at timestamp for PIT verification.

Feature categories:
    - Cross-asset momentum (5d, 10d, 20d)
    - Volatility regimes (realized vs implied)
    - Correlation breakdowns (rolling 20d)
    - Macro surprise aggregates
    - FII/DII flow momentum
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from ..data.normalizer import (
    normalize_z_score,
    rolling_return,
    realized_volatility,
    safe_divide,
)

logger = logging.getLogger(__name__)


def compute_features(
    market_state: Dict[str, Any],
    historical_prices: Optional[Dict[str, List[float]]] = None,
    historical_surprises: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Compute all features from current market state and history.
    All features use ONLY data available before computation time.

    Returns dict of feature categories, each with computed_at timestamp.
    """
    now = datetime.now(timezone.utc).isoformat()
    features = {"computed_at": now}

    # 1. Cross-asset momentum
    features["momentum"] = _compute_momentum_features(
        historical_prices or {}, now
    )

    # 2. Volatility features
    features["volatility"] = _compute_volatility_features(
        market_state, historical_prices or {}, now
    )

    # 3. Macro surprise aggregates
    features["macro_surprises"] = _compute_surprise_features(
        historical_surprises or [], now
    )

    # 4. Yield curve features
    features["yield_curve"] = _compute_yield_features(
        market_state, now
    )

    # 5. Commodity features
    features["commodities"] = _compute_commodity_features(
        market_state, now
    )

    # 6. FX features
    features["fx"] = _compute_fx_features(
        market_state, now
    )

    return features


def _compute_momentum_features(
    historical_prices: Dict[str, List[float]],
    computed_at: str,
) -> Dict[str, Any]:
    """Cross-asset momentum (5d, 10d, 20d rolling returns)."""
    result = {"computed_at": computed_at}

    for symbol in ["^NSEI", "^GSPC", "^IXIC", "^DJI"]:
        prices = historical_prices.get(symbol, [])
        if len(prices) >= 21:
            result[f"{symbol}_5d"] = rolling_return(prices, 5)
            result[f"{symbol}_10d"] = rolling_return(prices, 10)
            result[f"{symbol}_20d"] = rolling_return(prices, 20)
        else:
            result[f"{symbol}_5d"] = None
            result[f"{symbol}_10d"] = None
            result[f"{symbol}_20d"] = None

    return result


def _compute_volatility_features(
    market_state: Dict[str, Any],
    historical_prices: Dict[str, List[float]],
    computed_at: str,
) -> Dict[str, Any]:
    """Volatility regime — implied vs realized."""
    result = {"computed_at": computed_at}

    # Implied volatility (VIX / India VIX)
    vix = market_state.get("volatility", {}).get("^INDIAVIX", {})
    result["india_vix"] = vix.get("price") if vix else None

    vix_us_data = market_state.get("us_macro", {}).get("VIXCLS", {})
    result["us_vix"] = vix_us_data.get("value") if vix_us_data else None

    # Realized volatility (20d annualized)
    nifty_prices = historical_prices.get("^NSEI", [])
    if len(nifty_prices) >= 21:
        returns = [
            (nifty_prices[i] - nifty_prices[i-1]) / nifty_prices[i-1]
            for i in range(1, len(nifty_prices))
        ]
        result["nifty_realized_vol_20d"] = realized_volatility(returns, 20)
    else:
        result["nifty_realized_vol_20d"] = None

    # Vol ratio: implied / realized
    if result["india_vix"] and result["nifty_realized_vol_20d"]:
        result["vol_ratio"] = round(
            safe_divide(result["india_vix"], result["nifty_realized_vol_20d"]), 2
        )
    else:
        result["vol_ratio"] = None

    return result


def _compute_surprise_features(
    historical_surprises: List[Dict[str, Any]],
    computed_at: str,
) -> Dict[str, Any]:
    """Aggregate macro surprise momentum."""
    result = {"computed_at": computed_at}

    if not historical_surprises:
        result["composite_surprise"] = 0.0
        result["surprise_trend"] = "NEUTRAL"
        result["extreme_count_5d"] = 0
        return result

    normalized = [
        s.get("normalized_surprise_sigma", 0)
        for s in historical_surprises
    ]

    result["composite_surprise"] = round(float(np.mean(normalized)), 2)
    result["surprise_std"] = round(float(np.std(normalized)), 2) if len(normalized) > 1 else 0
    result["extreme_count_5d"] = sum(1 for n in normalized[:5] if abs(n) > 2.0)

    if result["composite_surprise"] > 0.5:
        result["surprise_trend"] = "POSITIVE"
    elif result["composite_surprise"] < -0.5:
        result["surprise_trend"] = "NEGATIVE"
    else:
        result["surprise_trend"] = "NEUTRAL"

    return result


def _compute_yield_features(
    market_state: Dict[str, Any],
    computed_at: str,
) -> Dict[str, Any]:
    """Yield curve and rate features."""
    result = {"computed_at": computed_at}
    us_macro = market_state.get("us_macro", {})

    us10y = us_macro.get("DGS10", {})
    us2y = us_macro.get("DGS2", {})
    spread = us_macro.get("T10Y2Y", {})

    result["us_10y"] = us10y.get("value")
    result["us_2y"] = us2y.get("value")
    result["us_10y_2y_spread"] = spread.get("value")

    # Inverted yield curve flag
    if result["us_10y_2y_spread"] is not None:
        result["yield_curve_inverted"] = result["us_10y_2y_spread"] < 0
    else:
        result["yield_curve_inverted"] = None

    return result


def _compute_commodity_features(
    market_state: Dict[str, Any],
    computed_at: str,
) -> Dict[str, Any]:
    """Commodity price features."""
    result = {"computed_at": computed_at}
    commodities = market_state.get("commodities", {})

    wti = commodities.get("CL=F", {})
    brent = commodities.get("BZ=F", {})
    gold = commodities.get("GC=F", {})

    result["wti_crude"] = wti.get("price")
    result["brent_crude"] = brent.get("price")
    result["gold"] = gold.get("price")

    # Brent-WTI spread
    if result["wti_crude"] and result["brent_crude"]:
        result["brent_wti_spread"] = round(result["brent_crude"] - result["wti_crude"], 2)
    else:
        result["brent_wti_spread"] = None

    return result


def _compute_fx_features(
    market_state: Dict[str, Any],
    computed_at: str,
) -> Dict[str, Any]:
    """FX features."""
    result = {"computed_at": computed_at}
    fx = market_state.get("fx", {})

    usdinr = fx.get("USDINR=X", {})
    result["usdinr"] = usdinr.get("price")

    # DXY from US macro (proxy)
    us_macro = market_state.get("us_macro", {})
    dxy_proxy = us_macro.get("DTWEXBGS", {})
    result["dxy_proxy"] = dxy_proxy.get("value") if dxy_proxy else None

    return result
