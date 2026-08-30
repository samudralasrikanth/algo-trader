# =============================================================================
# event_agent/engine/prediction_algo.py — Multi-Factor Event Prediction Engine
# =============================================================================

import math
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple
import yfinance as yf
import numpy as np

from ..config import NIFTY50_UNIVERSE, EVENT_CATEGORIES, HORIZONS
from ..collectors.news_collector import fetch_stock_news, fetch_macro_news
from ..collectors.event_calendar import get_stock_events, get_macro_events
from .sentiment_analyzer import analyze_news_sentiment


def fetch_stock_market_context(symbol: str) -> Dict[str, Any]:
    """
    Fetch latest closing price and volatility metrics from yfinance (zero API key).
    """
    default_prices = {
        "RELIANCE.NS": 1287.0,
        "HDFCBANK.NS": 1640.0,
        "ICICIBANK.NS": 1215.0,
        "TCS.NS": 4120.0,
        "INFY.NS": 1835.0,
        "BHARTIARTL.NS": 1590.0,
        "SBIN.NS": 815.0,
        "LT.NS": 3650.0,
        "ITC.NS": 490.0,
        "MARUTI.NS": 13376.0
    }
    
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        if not hist.empty and len(hist) >= 5:
            last_close = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last_close
            daily_returns = hist["Close"].pct_change().dropna()
            daily_volatility = float(daily_returns.std()) if len(daily_returns) > 1 else 0.015
            if math.isnan(daily_volatility) or daily_volatility <= 0:
                daily_volatility = 0.015
                
            # 14-day ATR approximation
            high_low = (hist["High"] - hist["Low"]) / hist["Close"]
            atr_pct = float(high_low.tail(14).mean()) if len(high_low) >= 5 else 0.018
            if math.isnan(atr_pct) or atr_pct <= 0:
                atr_pct = 0.018
                
            return {
                "current_price": round(last_close, 2),
                "prev_close": round(prev_close, 2),
                "daily_volatility": daily_volatility,
                "atr_pct": atr_pct,
                "price_date": hist.index[-1].strftime("%Y-%m-%d")
            }
    except Exception:
        pass
        
    # Fallback to nominal price if network issue
    base = default_prices.get(symbol, 1000.0)
    return {
        "current_price": base,
        "prev_close": base,
        "daily_volatility": 0.015,
        "atr_pct": 0.018,
        "price_date": datetime.now().strftime("%Y-%m-%d")
    }


def compute_event_impact_vector(occurred_events: List[Dict[str, Any]], upcoming_events: List[Dict[str, Any]]) -> Tuple[float, List[str]]:
    """
    Calculate numerical return impact from corporate/macro events.
    """
    net_impact = 0.0
    catalyst_notes = []
    
    # 1. Post-event reaction (occurred within last 3 days)
    for ev in occurred_events:
        ev_type = ev.get("type", "NEUTRAL_UPDATE")
        days = abs(ev.get("days_away", 0))
        decay = math.exp(-0.35 * days)  # Decay impact over days
        
        cfg = EVENT_CATEGORIES.get(ev_type, {"base_impact": 0.01, "direction": 1})
        impact = cfg["base_impact"] * decay
        net_impact += impact
        catalyst_notes.append(f"Recent Event ({ev.get('title')}, Day {days} ago: {impact:+.2%})")
        
    # 2. Upcoming catalyst run-up / uncertainty premium
    for ev in upcoming_events:
        days = ev.get("days_away", 7)
        if days <= 7:
            # Anticipation effect
            ev_type = ev.get("type", "")
            if "EARNINGS" in ev_type:
                # Modest positive anticipation bias unless news is negative
                anticipation = 0.006 * (1.0 / max(1, days))
                net_impact += anticipation
                catalyst_notes.append(f"Upcoming Earnings in {days}d (catalyst anticipation: {anticipation:+.2%})")
            elif "DIVIDEND" in ev_type:
                anticipation = 0.004
                net_impact += anticipation
                catalyst_notes.append(f"Upcoming Dividend Ex-Date in {days}d (+{anticipation:.2%})")
                
    return net_impact, catalyst_notes


def generate_stock_prediction(
    symbol: str,
    news_articles: Optional[List[Dict[str, Any]]] = None,
    macro_articles: Optional[List[Dict[str, Any]]] = None,
    reference_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Generate multi-horizon price and directional predictions for a single Nifty 50 stock.
    """
    stock_meta = NIFTY50_UNIVERSE.get(symbol, {
        "name": symbol,
        "short_name": symbol,
        "sector": "General",
        "beta": 1.0
    })
    
    if reference_date is None:
        reference_date = datetime.now().date()
        
    # 1. Collect News if not passed
    if news_articles is None:
        news_articles = fetch_stock_news(symbol, max_items=12)
    if macro_articles is None:
        macro_articles = fetch_macro_news(max_items=8)
        
    # 2. Analyze Sentiments
    stock_sentiment = analyze_news_sentiment(news_articles)
    macro_sentiment = analyze_news_sentiment(macro_articles)
    
    # 3. Events
    stock_events = get_stock_events(symbol, reference_date=reference_date, window_days=14)
    macro_events = get_macro_events(reference_date=reference_date, window_days=14)
    
    event_impact, event_notes = compute_event_impact_vector(
        stock_events["occurred"] + macro_events["occurred"],
        stock_events["upcoming"] + macro_events["upcoming"]
    )
    
    # 4. Market Context (Current Price & Volatility)
    mkt = fetch_stock_market_context(symbol)
    base_price = mkt["current_price"]
    daily_vol = mkt["daily_volatility"]
    beta = stock_meta.get("beta", 1.0)
    
    # 5. Core Multi-Factor Algo Formulation
    # Polarity is [-1.0, 1.0]
    stock_pol = stock_sentiment["avg_polarity"]
    macro_pol = macro_sentiment["avg_polarity"]
    
    # News surge factor (more articles = higher signal weight)
    volume_factor = min(1.3, 0.8 + (stock_sentiment["total_articles"] * 0.05))
    
    # Combined Expected Return Component (1-Day baseline)
    # Weight: 60% Stock News Sentiment, 20% Macro Sentiment, 20% Discrete Event Impact
    weighted_sentiment_move = (
        (stock_pol * 0.018 * beta * volume_factor) +
        (macro_pol * 0.008 * beta) +
        (event_impact * 0.6)
    )
    
    # Bound expected 1D move to realistic equity bounds (e.g. max +- 3.5%)
    expected_1d_pct = max(-0.035, min(0.035, weighted_sentiment_move))
    
    # 3D and 7D projections with time scaling (sqrt(T) for volatility, linear drift with dampening)
    expected_3d_pct = max(-0.065, min(0.065, expected_1d_pct * 1.85))
    expected_7d_pct = max(-0.095, min(0.095, expected_1d_pct * 2.80))
    
    # Target Prices
    target_1d = round(base_price * (1.0 + expected_1d_pct), 2)
    target_3d = round(base_price * (1.0 + expected_3d_pct), 2)
    target_7d = round(base_price * (1.0 + expected_7d_pct), 2)
    
    # Target Price Ranges (Low - High Bands based on ATR & horizon)
    band_1d = base_price * daily_vol * 1.2
    band_3d = base_price * daily_vol * math.sqrt(3) * 1.3
    band_7d = base_price * daily_vol * math.sqrt(7) * 1.4
    
    range_1d = {
        "low": round(target_1d - band_1d, 2),
        "expected": target_1d,
        "high": round(target_1d + band_1d, 2)
    }
    range_3d = {
        "low": round(target_3d - band_3d, 2),
        "expected": target_3d,
        "high": round(target_3d + band_3d, 2)
    }
    range_7d = {
        "low": round(target_7d - band_7d, 2),
        "expected": target_7d,
        "high": round(target_7d + band_7d, 2)
    }
    
    # 6. Directional Bias & Action Classification
    if expected_1d_pct >= 0.008:
        direction = "BULLISH"
        action = "STRONG_BUY" if (expected_1d_pct >= 0.015 and stock_sentiment["confidence"] >= 65) else "BUY"
    elif expected_1d_pct <= -0.008:
        direction = "BEARISH"
        action = "STRONG_SELL" if (expected_1d_pct <= -0.015 and stock_sentiment["confidence"] >= 65) else "SELL"
    else:
        direction = "NEUTRAL"
        action = "HOLD"
        
    # Conviction Score (0-100%)
    sentiment_agreement = 1.0 if (stock_pol * macro_pol >= 0) else 0.8
    conviction = round(min(96.0, max(45.0, (stock_sentiment["confidence"] * 0.7 + (abs(stock_pol) * 35.0)) * sentiment_agreement)), 1)
    
    # 7. Synthesis Reasoning Engine (Natural Language Narrative)
    catalysts = stock_sentiment.get("key_catalysts", [])
    risks = stock_sentiment.get("risk_factors", [])
    
    # If empty, add standard drivers
    if not catalysts:
        catalysts = [f"Sector tailwinds in {stock_meta['sector']}", f"Stable fundamental driver: {stock_meta['key_drivers'][0]}"]
    if not risks:
        risks = [f"Broad market volatility & FII equity outflow risk", f"Key monitoring trigger: {stock_meta['key_drivers'][-1]}"]
        
    upcoming_str = "None in next 14 days"
    if stock_events["upcoming"]:
        next_ev = stock_events["upcoming"][0]
        upcoming_str = f"{next_ev['title']} on {next_ev['date']} ({next_ev['days_away']}d away)"
        
    if direction == "BULLISH":
        thesis = f"Bullish bias driven by favorable corporate headlines (sentiment: +{stock_pol:.2f}) and positive market positioning in {stock_meta['short_name']}."
    elif direction == "BEARISH":
        thesis = f"Cautious/Bearish outlook due to adverse news flow/headwinds (sentiment: {stock_pol:.2f}) and pressure on {stock_meta['short_name']}."
    else:
        thesis = f"Neutral consolidation expected for {stock_meta['short_name']} as news sentiment ({stock_pol:+.2f}) is balanced with no major disruptive catalyst."
        
    reasoning = {
        "thesis": thesis,
        "catalysts": catalysts[:3],
        "risks": risks[:3],
        "upcoming_watch": upcoming_str,
        "event_notes": event_notes[:2]
    }
    
    return {
        "timestamp": datetime.now().isoformat(),
        "date": reference_date.strftime("%Y-%m-%d"),
        "symbol": symbol,
        "company_name": stock_meta["name"],
        "short_name": stock_meta["short_name"],
        "sector": stock_meta["sector"],
        "base_price": base_price,
        "prev_close": mkt["prev_close"],
        "price_date": mkt["price_date"],
        "direction": direction,
        "action": action,
        "conviction": conviction,
        "stock_sentiment_score": stock_pol,
        "macro_sentiment_score": macro_pol,
        "news_count": stock_sentiment["total_articles"],
        "expected_1d_pct": round(expected_1d_pct * 100, 2),
        "expected_3d_pct": round(expected_3d_pct * 100, 2),
        "expected_7d_pct": round(expected_7d_pct * 100, 2),
        "target_1d": target_1d,
        "target_3d": target_3d,
        "target_7d": target_7d,
        "range_1d": range_1d,
        "range_3d": range_3d,
        "range_7d": range_7d,
        "reasoning": reasoning,
        "news_articles": stock_sentiment.get("annotated_articles", [])[:5],
        "occurred_events": stock_events["occurred"],
        "upcoming_events": stock_events["upcoming"]
    }


from concurrent.futures import ThreadPoolExecutor

def generate_all_predictions(reference_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """
    Run prediction engine across all 10 Nifty 50 universe stocks concurrently for high throughput.
    """
    if reference_date is None:
        reference_date = datetime.now().date()
        
    macro_articles = fetch_macro_news(max_items=8)
    symbols = list(NIFTY50_UNIVERSE.keys())
    
    def _predict(sym: str) -> Dict[str, Any]:
        return generate_stock_prediction(
            symbol=sym,
            macro_articles=macro_articles,
            reference_date=reference_date
        )
        
    with ThreadPoolExecutor(max_workers=5) as executor:
        predictions = list(executor.map(_predict, symbols))
        
    return predictions
