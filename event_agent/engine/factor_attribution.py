# =============================================================================
# event_agent/engine/factor_attribution.py — Factor Attribution & Algo Diagnostics
# =============================================================================

from typing import Dict, Any, List, Optional
from datetime import datetime


def diagnose_prediction_outcome(
    pred: Dict[str, Any],
    actual_data: Dict[str, Any],
    stock_news_today: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Perform deep attribution analysis comparing pre-market night prediction vs actual market results.
    
    Attribution Categories:
    1. CAPTURED_SUCCESS: Identified fundamental/sentiment factor worked as expected.
    2. MISSED_CATALYST: A new breaking intra-day event occurred that was untracked pre-market.
    3. FACTOR_MISCALIBRATED: Factor was identified pre-market, but price reacted inversely or with different sensitivity.
    4. MARKET_NOISE_DRIFT: Price traded in a narrow consolidation band without clear fundamental drift.
    """
    symbol = pred.get("symbol", "")
    pred_dir = pred.get("direction", "NEUTRAL")
    exp_pct = pred.get("expected_1d_pct", 0.0)
    conviction = pred.get("conviction", 50.0)
    sentiment_score = pred.get("stock_sentiment_score", 0.0)
    reasoning = pred.get("reasoning", {})
    
    base_price = actual_data.get("base_price", pred.get("base_price", 100.0))
    actual_close = actual_data.get("actual_close", base_price)
    actual_change_pct = round(((actual_close - base_price) / base_price) * 100, 2)
    
    actual_dir = "BULLISH" if actual_change_pct > 0.4 else ("BEARISH" if actual_change_pct < -0.4 else "NEUTRAL")
    
    direction_correct = False
    if pred_dir == "BULLISH" and actual_change_pct > 0:
        direction_correct = True
    elif pred_dir == "BEARISH" and actual_change_pct < 0:
        direction_correct = True
    elif pred_dir == "NEUTRAL" and abs(actual_change_pct) <= 0.8:
        direction_correct = True
        
    range_1d = pred.get("range_1d", {})
    r_low = range_1d.get("low", base_price * 0.98)
    r_high = range_1d.get("high", base_price * 1.02)
    hit_target = (r_low <= actual_close <= r_high)
    abs_error_pct = round(abs(actual_close - pred.get("target_1d", base_price)) / base_price * 100, 2)
    
    # -------------------------------------------------------------------------
    # Factor Attribution Logic
    # -------------------------------------------------------------------------
    primary_factors_identified = reasoning.get("catalysts", [])
    risks_identified = reasoning.get("risks", [])
    
    if direction_correct and abs(actual_change_pct) >= 0.5:
        category = "CAPTURED_SUCCESS"
        explanation = f"Algo successfully predicted {actual_change_pct:+.2f}% move in {symbol}. The pre-market identified catalysts ({', '.join(primary_factors_identified[:2])}) drove the expected market reaction."
        refactoring_suggestion = "Weights and sensitivity for this sector/event type are well-calibrated. Maintain current parameter matrix."
        
    elif not direction_correct and abs(actual_change_pct) >= 1.0:
        # Significant wrong-way move
        # Check if pre-market had strong sentiment in opposite direction
        if abs(sentiment_score) >= 0.3:
            category = "FACTOR_MISCALIBRATED"
            explanation = f"Factor was identified pre-market (Sentiment: {sentiment_score:+.2f}), but market reacted inversely ({actual_change_pct:+.2f}%). Classic 'sell-the-news' profit booking or prior price run-up discounting."
            refactoring_suggestion = "Implement 'Priced-In / Sell-The-News' dampener when stock has rallied >3% in preceding 5 sessions before a positive event."
        else:
            category = "MISSED_CATALYST"
            explanation = f"Unexpected {actual_change_pct:+.2f}% volatility in {symbol}. Pre-market news sentiment was neutral ({sentiment_score:+.2f}), indicating an intraday breaking headline or sudden institutional FII/DII block deal."
            refactoring_suggestion = "Incorporate intra-day live news polling and broaden sector peer contagion weights."
            
    elif abs(actual_change_pct) <= 0.5:
        category = "MARKET_NOISE_DRIFT"
        explanation = f"Stock traded in a tight consolidation range ({actual_change_pct:+.2f}%). Neutral drift with low volatility."
        refactoring_suggestion = "Tighten HOLD threshold bands to avoid false trigger entries on low conviction setups."
        
    else:
        # Moderate deviation
        if (exp_pct * actual_change_pct) > 0:
            category = "CAPTURED_SUCCESS"
            explanation = f"Direction was correct ({actual_change_pct:+.2f}%), but move magnitude differed slightly from predicted target ({exp_pct:+.2f}%)."
            refactoring_suggestion = "Fine-tune ATR volatility multiplier for 1-day target band expansion."
        else:
            category = "FACTOR_MISCALIBRATED"
            explanation = f"Moderate divergence: Expected {exp_pct:+.2f}%, actual {actual_change_pct:+.2f}%. Sector beta drift outweighed stock-specific news."
            refactoring_suggestion = "Increase macro/Nifty broader index weight relative to single-stock headline score."
            
    return {
        "symbol": symbol,
        "base_price": base_price,
        "actual_close": actual_close,
        "actual_change_pct": actual_change_pct,
        "actual_direction": actual_dir,
        "direction_correct": 1 if direction_correct else 0,
        "hit_target_range": 1 if hit_target else 0,
        "abs_error_pct": abs_error_pct,
        "attribution_category": category,
        "diagnostic_explanation": explanation,
        "refactoring_suggestion": refactoring_suggestion,
        "factors_active": primary_factors_identified,
        "timestamp": datetime.now().isoformat()
    }

# Frozen Factor Weights V1
FACTOR_WEIGHTS_V1: Dict[str, float] = {
    "stock_sentiment": 0.30,
    "macro_sentiment": 0.15,
    "events": 0.20,
    "macro_surprise": 0.15,
    "regime_tilt": 0.10,
    "momentum": 0.10,
}
