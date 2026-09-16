# =============================================================================
# event_agent/engine/prediction_algo.py — Multi-Factor Event Prediction Engine v3.0
# =============================================================================
"""
V3.0 Quantitative Prediction Engine with Point-in-Time Guarantees, 8-Dimension
Regime Conditioning, Deterministic Math, 5 Baselines, Risk-Based Sizing,
and Immutable Prediction Snapshots.

Central Invariant:
    Every prediction must be reproducible from exactly the information that
    existed at the moment the prediction was locked.
"""

import hashlib
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yfinance as yf

from ..config import EVENT_CATEGORIES, HORIZONS, NIFTY50_UNIVERSE
from ..collectors.event_calendar import get_macro_events, get_stock_events
from ..collectors.news_collector import fetch_macro_news, fetch_stock_news
from ..research.baseline_models import BaselineSuite
from ..research.model_versioning import get_current_version_record, get_model_version
from .calibration import calibrate_confidence
from .factor_attribution import FACTOR_WEIGHTS_V1
from .sentiment_analyzer import analyze_news_sentiment

logger = logging.getLogger(__name__)

MODEL_VERSION = "3.0.0"

# ---------------------------------------------------------------------------
# Accurate Post-Corporate-Action Fallback Prices (NSE India)
# ---------------------------------------------------------------------------
DEFAULT_PRICES: Dict[str, float] = {
    "RELIANCE.NS": 1287.0,    # Post 1:1 bonus
    "HDFCBANK.NS": 1640.0,
    "ICICIBANK.NS": 1215.0,
    "TCS.NS": 4120.0,
    "INFY.NS": 1835.0,
    "BHARTIARTL.NS": 1590.0,
    "SBIN.NS": 815.0,
    "LT.NS": 3650.0,
    "ITC.NS": 490.0,
    "MARUTI.NS": 13376.0,
}


def fetch_stock_market_context(
    symbol: str,
    cutoff_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Fetch closing price, daily volatility, ATR, and short price history.
    Enforces point-in-time cutoff if cutoff_dt is provided.
    """
    default_price = DEFAULT_PRICES.get(symbol, 1000.0)

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="3mo")
        if not hist.empty:
            hist = hist.dropna(subset=["Close", "High", "Low"])
        if not hist.empty and len(hist) >= 5:
            # Filter by point-in-time cutoff if specified
            if cutoff_dt:
                cutoff_date = cutoff_dt.date() if isinstance(cutoff_dt, datetime) else cutoff_dt
                hist = hist[hist.index.date <= cutoff_date]
                hist = hist.dropna(subset=["Close", "High", "Low"])

            if not hist.empty and len(hist) >= 5:
                last_close = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last_close
                if math.isnan(last_close) or last_close <= 0:
                    last_close = default_price
                if math.isnan(prev_close) or prev_close <= 0:
                    prev_close = last_close

                daily_returns = hist["Close"].pct_change().dropna()
                daily_volatility = float(daily_returns.std()) if len(daily_returns) > 1 else 0.015
                if math.isnan(daily_volatility) or daily_volatility <= 0:
                    daily_volatility = 0.015

                high_low = (hist["High"] - hist["Low"]) / hist["Close"]
                high_low = high_low.dropna()
                atr_pct = float(high_low.tail(14).mean()) if len(high_low) >= 5 else 0.018
                if math.isnan(atr_pct) or atr_pct <= 0:
                    atr_pct = 0.018

                close_history = [float(x) for x in hist["Close"].tail(20).tolist() if not math.isnan(x)]
                if not close_history:
                    close_history = [default_price] * 20

                return {
                    "current_price": round(last_close, 2),
                    "prev_close": round(prev_close, 2),
                    "daily_volatility": daily_volatility,
                    "atr_pct": atr_pct,
                    "price_history_20d": close_history,
                    "price_date": hist.index[-1].strftime("%Y-%m-%d"),
                }
    except Exception as e:
        logger.debug(f"Market context fetch fallback for {symbol}: {e}")

    # Deterministic fallback
    return {
        "current_price": default_price,
        "prev_close": default_price,
        "daily_volatility": 0.015,
        "atr_pct": 0.018,
        "price_history_20d": [default_price] * 20,
        "price_date": (cutoff_dt.strftime("%Y-%m-%d") if cutoff_dt else datetime.now().strftime("%Y-%m-%d")),
    }


def compute_event_impact_vector(
    occurred_events: List[Dict[str, Any]],
    upcoming_events: List[Dict[str, Any]],
) -> Tuple[float, List[str]]:
    """
    Calculate return impact from corporate/macro events using decay functions.
    """
    net_impact = 0.0
    catalyst_notes = []

    # 1. Post-event reaction (occurred within last 3 days)
    for ev in occurred_events:
        ev_type = ev.get("type", "NEUTRAL_UPDATE")
        days = abs(ev.get("days_away", 0))
        decay = math.exp(-0.35 * days)
        cfg = EVENT_CATEGORIES.get(ev_type, {"base_impact": 0.01, "direction": 1})
        impact = cfg["base_impact"] * cfg.get("direction", 1) * decay
        net_impact += impact
        catalyst_notes.append(f"Recent Event ({ev.get('title')}, Day {days} ago: {impact:+.2%})")

    # 2. Upcoming catalyst run-up
    for ev in upcoming_events:
        days = ev.get("days_away", 7)
        if days <= 7:
            ev_type = ev.get("type", "")
            if "EARNINGS" in ev_type:
                anticipation = 0.006 * (1.0 / max(1, days))
                net_impact += anticipation
                catalyst_notes.append(f"Upcoming Earnings in {days}d (anticipation: {anticipation:+.2%})")
            elif "DIVIDEND" in ev_type:
                anticipation = 0.004
                net_impact += anticipation
                catalyst_notes.append(f"Upcoming Dividend in {days}d (+{anticipation:.2%})")

    return net_impact, catalyst_notes


def generate_stock_prediction(
    symbol: str,
    news_articles: Optional[List[Dict[str, Any]]] = None,
    macro_articles: Optional[List[Dict[str, Any]]] = None,
    reference_date: Optional[date] = None,
    data_cutoff_dt: Optional[datetime] = None,
    target_trade_date: Optional[str] = None,
    market_state: Optional[Dict[str, Any]] = None,
    regime: Optional[Dict[str, Any]] = None,
    features: Optional[Dict[str, Any]] = None,
    surprises: Optional[List[Dict[str, Any]]] = None,
    portfolio_capital: float = 10_00_000.0,
    risk_per_trade_pct: float = 0.5,
) -> Dict[str, Any]:
    """
    Generate multi-horizon directional and level predictions for a single Nifty 50
    stock with frozen prediction snapshot and 5 baselines.

    All numerical calculations are strictly deterministic math.
    LLM is used only for text interpretation of news articles.
    """
    now_utc = datetime.now(timezone.utc)
    if data_cutoff_dt is None:
        data_cutoff_dt = now_utc

    if reference_date is None:
        reference_date = data_cutoff_dt.date()

    ref_date_str = reference_date.strftime("%Y-%m-%d")
    target_date_str = target_trade_date or ref_date_str

    stock_meta = NIFTY50_UNIVERSE.get(
        symbol,
        {"name": symbol, "short_name": symbol, "sector": "General", "beta": 1.0, "key_drivers": ["Market momentum", "Macro stability"]},
    )
    beta = stock_meta.get("beta", 1.0)

    # 1. News collection with strict point-in-time cutoff
    if news_articles is None:
        news_articles = fetch_stock_news(symbol, max_items=12, cutoff_dt=data_cutoff_dt)
    if macro_articles is None:
        macro_articles = fetch_macro_news(max_items=8, cutoff_dt=data_cutoff_dt)

    stock_sentiment = analyze_news_sentiment(news_articles)
    macro_sentiment = analyze_news_sentiment(macro_articles)

    # 2. Events calendar
    stock_events = get_stock_events(symbol, reference_date=reference_date, window_days=14)
    macro_events = get_macro_events(reference_date=reference_date, window_days=14)

    event_impact, event_notes = compute_event_impact_vector(
        stock_events.get("occurred", []) + macro_events.get("occurred", []),
        stock_events.get("upcoming", []) + macro_events.get("upcoming", []),
    )

    # 3. Market Context (Prices, Volatility, History)
    mkt = fetch_stock_market_context(symbol, cutoff_dt=data_cutoff_dt)
    base_price = mkt.get("current_price")
    if base_price is None or math.isnan(base_price) or base_price <= 0:
        base_price = DEFAULT_PRICES.get(symbol, 1000.0)
    daily_vol = mkt.get("daily_volatility", 0.015)
    if daily_vol is None or math.isnan(daily_vol) or daily_vol <= 0:
        daily_vol = 0.015
    price_history = mkt.get("price_history_20d", [base_price] * 20)

    # 4. Multi-Factor Algorithm Formulation (Deterministic Math)
    stock_pol = float(stock_sentiment.get("avg_polarity", 0.0))
    macro_pol = float(macro_sentiment.get("avg_polarity", 0.0))
    volume_factor = min(1.3, 0.8 + (stock_sentiment.get("total_articles", 0) * 0.05))

    sentiment_move = (
        (stock_pol * 0.016 * beta * volume_factor) +
        (macro_pol * 0.007 * beta)
    )

    event_move = event_impact * 0.55

    # Surprise component
    surprise_delta = 0.0
    if surprises:
        sigmas = [s.get("normalized_surprise_sigma", 0.0) for s in surprises if isinstance(s, dict)]
        if sigmas:
            surprise_delta = float(np.mean(sigmas)) * 0.003

    # Regime conditioning
    regime_score = 0.0
    regime_name = "NEUTRAL"
    if regime:
        regime_score = float(regime.get("composite_score", 0.0))
        regime_name = regime.get("composite_regime", "NEUTRAL")
    regime_tilt = regime_score * 0.004 * beta

    # Momentum feature tilt
    ret_5d = (price_history[-1] - price_history[-5]) / price_history[-5] if len(price_history) >= 5 and price_history[-5] > 0 else 0.0
    prev_ret = (price_history[-1] - price_history[-2]) / price_history[-2] if len(price_history) >= 2 and price_history[-2] > 0 else 0.0
    momentum_tilt = max(-0.006, min(0.006, ret_5d * 0.05))

    weighted_expected_move = sentiment_move + event_move + surprise_delta + regime_tilt + momentum_tilt

    # Guardrails on expected return
    expected_1d_pct = max(-0.035, min(0.035, weighted_expected_move))
    expected_3d_pct = max(-0.065, min(0.065, expected_1d_pct * 1.85))
    expected_7d_pct = max(-0.095, min(0.095, expected_1d_pct * 2.80))

    target_1d = round(base_price * (1.0 + expected_1d_pct), 2)
    target_3d = round(base_price * (1.0 + expected_3d_pct), 2)
    target_7d = round(base_price * (1.0 + expected_7d_pct), 2)

    # Bands
    band_1d = base_price * daily_vol * 1.2
    band_3d = base_price * daily_vol * math.sqrt(3) * 1.3
    band_7d = base_price * daily_vol * math.sqrt(7) * 1.4

    range_1d = {"low": round(target_1d - band_1d, 2), "expected": target_1d, "high": round(target_1d + band_1d, 2)}
    range_3d = {"low": round(target_3d - band_3d, 2), "expected": target_3d, "high": round(target_3d + band_3d, 2)}
    range_7d = {"low": round(target_7d - band_7d, 2), "expected": target_7d, "high": round(target_7d + band_7d, 2)}

    # 5. Directional Bias & Action Classification
    if expected_1d_pct >= 0.006:
        direction = "BULLISH"
        action = "STRONG_BUY" if (expected_1d_pct >= 0.014 and stock_sentiment.get("confidence", 50) >= 65) else "BUY"
    elif expected_1d_pct <= -0.006:
        direction = "BEARISH"
        action = "STRONG_SELL" if (expected_1d_pct <= -0.014 and stock_sentiment.get("confidence", 50) >= 65) else "SELL"
    else:
        direction = "NEUTRAL"
        action = "HOLD"

    # Raw conviction & calibrated conviction
    sentiment_agreement = 1.0 if (stock_pol * macro_pol >= 0) else 0.85
    raw_conviction = min(96.0, max(45.0, (stock_sentiment.get("confidence", 50) * 0.65 + (abs(stock_pol) * 35.0)) * sentiment_agreement))
    conviction = calibrate_confidence(raw_conviction, regime_state=regime_name)

    # 6. Entry, Target, Stop-Loss Levels
    entry_price = base_price
    target_price = target_1d

    # Risk-aware stop-loss: 1.5 * daily volatility (bounded between 1.2% and 3.5%)
    stop_distance_pct = max(0.012, min(0.035, daily_vol * 1.5))
    if direction == "BULLISH":
        stop_loss = round(base_price * (1.0 - stop_distance_pct), 2)
    elif direction == "BEARISH":
        stop_loss = round(base_price * (1.0 + stop_distance_pct), 2)
    else:
        stop_loss = round(base_price * (1.0 - stop_distance_pct), 2)

    stop_distance = abs(entry_price - stop_loss)

    # 7. Risk-Based Position Sizing (0.5% Portfolio Risk)
    risk_amount = portfolio_capital * (risk_per_trade_pct / 100.0)
    suggested_quantity = int(risk_amount / stop_distance) if stop_distance > 0 else 0
    # Guardrail: Maximum 10% portfolio capital allocation per stock
    max_position_capital = portfolio_capital * 0.10
    if suggested_quantity * entry_price > max_position_capital and entry_price > 0:
        suggested_quantity = int(max_position_capital / entry_price)

    suggested_position_value = round(suggested_quantity * entry_price, 2)

    # 8. 5 Benchmark Baselines
    baseline_suite = BaselineSuite()
    baselines = baseline_suite.evaluate_all(
        symbol=symbol,
        prediction_date=ref_date_str,
        price_history=price_history,
        prev_return=prev_ret,
        ret_5d=ret_5d,
    )

    # 9. Reasoning Synthesis
    catalysts = stock_sentiment.get("key_catalysts", [])
    risks = stock_sentiment.get("risk_factors", [])
    if not catalysts:
        catalysts = [f"Sector positioning in {stock_meta['sector']}", f"Core driver: {stock_meta['key_drivers'][0]}"]
    if not risks:
        risks = [f"Macro volatility / FII flow risk", f"Key monitoring trigger: {stock_meta['key_drivers'][-1]}"]

    upcoming_str = "None in next 14 days"
    if stock_events.get("upcoming"):
        next_ev = stock_events["upcoming"][0]
        upcoming_str = f"{next_ev.get('title')} on {next_ev.get('date')} ({next_ev.get('days_away')}d away)"

    if direction == "BULLISH":
        thesis = f"Bullish stance on {stock_meta['short_name']} driven by positive news sentiment ({stock_pol:+.2f}) and favorable regime ({regime_name})."
    elif direction == "BEARISH":
        thesis = f"Bearish stance on {stock_meta['short_name']} driven by negative sentiment/headwinds ({stock_pol:+.2f}) in regime ({regime_name})."
    else:
        thesis = f"Neutral consolidation expected for {stock_meta['short_name']}; sentiment ({stock_pol:+.2f}) balanced against regime ({regime_name})."

    reasoning = {
        "thesis": thesis,
        "catalysts": catalysts[:3],
        "risks": risks[:3],
        "upcoming_watch": upcoming_str,
        "event_notes": event_notes[:2],
        "regime_context": f"{regime_name} (score {regime_score:+.2f})",
    }

    # 10. Prediction ID & Provenance
    clean_sym = symbol.replace(".NS", "")
    target_clean = target_date_str.replace("-", "")
    prediction_id = f"PRED-{target_clean}-{clean_sym}-v{MODEL_VERSION}"

    news_provenance = [
        {
            "title": art.get("title"),
            "source": art.get("source"),
            "pub_date": art.get("pub_date"),
            "url": art.get("url"),
            "sentiment_score": art.get("sentiment_score", 0.0),
        }
        for art in stock_sentiment.get("annotated_articles", [])[:10]
    ]

    version_rec = get_current_version_record()

    # Canonical payload for SHA-256 snapshot hash
    hash_payload = {
        "prediction_id": prediction_id,
        "model_version": MODEL_VERSION,
        "symbol": symbol,
        "base_price": base_price,
        "data_cutoff": data_cutoff_dt.isoformat(),
        "direction": direction,
        "action": action,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "expected_1d_pct": round(expected_1d_pct * 100, 2),
        "conviction": conviction,
        "regime_name": regime_name,
        "regime_score": round(regime_score, 4),
        "baselines_summary": baselines.get("summary", {}),
        "version_record": version_rec,
    }

    snapshot_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode("utf-8")).hexdigest()

    # Immutable Prediction Snapshot (Schema ready for Supabase prediction_snapshots table)
    prediction_snapshot = {
        "prediction_id": prediction_id,
        "model_version": MODEL_VERSION,
        "feature_version": version_rec.get("feature_version", "F1"),
        "regime_version": version_rec.get("regime_version", "R1"),
        "calibration_version": version_rec.get("calibration_version", "C1"),
        "weights_version": version_rec.get("weights_version", "W1.0"),
        "data_snapshot_id": version_rec.get("data_snapshot_id", "SNAP-INITIAL"),
        "market_state_json": market_state or {"base_price": base_price, "daily_volatility": daily_vol},
        "regime_json": regime or {"composite_regime": regime_name, "composite_score": regime_score},
        "features_json": features or {"momentum_5d": ret_5d, "prev_ret": prev_ret},
        "surprises_json": surprises or [],
        "news_articles_json": news_provenance,
        "events_json": stock_events.get("occurred", []) + stock_events.get("upcoming", []),
        "factor_weights_json": dict(FACTOR_WEIGHTS_V1),
        "prediction_json": {
            "direction": direction,
            "action": action,
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "stop_distance": round(stop_distance, 2),
            "expected_1d_pct": round(expected_1d_pct * 100, 2),
            "conviction": conviction,
            "suggested_quantity": suggested_quantity,
        },
        "baselines_json": baselines,
        "snapshot_hash": snapshot_hash,
        "locked_at": now_utc.isoformat(),
    }

    provenance = {
        "prediction_id": prediction_id,
        "model_version": MODEL_VERSION,
        "snapshot_hash": snapshot_hash,
        "generated_at": now_utc.isoformat(),
        "data_cutoff": data_cutoff_dt.isoformat(),
        "news_count": stock_sentiment.get("total_articles", 0),
        "news_sources_used": list(set([n.get("source", "Google News") for n in news_provenance])),
        "news_articles": news_provenance,
        "events_used": event_notes,
        "factor_breakdown": {
            "stock_sentiment_polarity": round(stock_pol, 4),
            "macro_sentiment_polarity": round(macro_pol, 4),
            "event_impact_vector": round(event_impact, 4),
            "surprise_delta": round(surprise_delta, 4),
            "regime_tilt": round(regime_tilt, 4),
            "momentum_tilt": round(momentum_tilt, 4),
            "market_beta": beta,
            "daily_volatility": round(daily_vol, 5),
        },
    }

    return {
        "prediction_id": prediction_id,
        "model_version": MODEL_VERSION,
        "version_record": version_rec,
        "snapshot_hash": snapshot_hash,
        "data_cutoff": data_cutoff_dt.isoformat(),
        "timestamp": now_utc.isoformat(),
        "date": ref_date_str,
        "target_trade_date": target_date_str,
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
        "raw_conviction": round(raw_conviction, 1),
        "stock_sentiment_score": stock_pol,
        "macro_sentiment_score": macro_pol,
        "news_count": stock_sentiment.get("total_articles", 0),
        "expected_1d_pct": round(expected_1d_pct * 100, 2),
        "expected_3d_pct": round(expected_3d_pct * 100, 2),
        "expected_7d_pct": round(expected_7d_pct * 100, 2),
        "target_1d": target_1d,
        "target_3d": target_3d,
        "target_7d": target_7d,
        "range_1d": range_1d,
        "range_3d": range_3d,
        "range_7d": range_7d,
        # Execution & sizing levels
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "stop_distance": round(stop_distance, 2),
        "stop_distance_pct": round(stop_distance_pct * 100, 2),
        "risk_per_trade_pct": risk_per_trade_pct,
        "portfolio_capital": portfolio_capital,
        "suggested_quantity": suggested_quantity,
        "suggested_position_value": suggested_position_value,
        # Diagnostics, baselines & snapshot
        "reasoning": reasoning,
        "provenance": provenance,
        "baselines": baselines,
        "prediction_snapshot": prediction_snapshot,
        "news_articles": news_provenance,
        "occurred_events": stock_events.get("occurred", []),
        "upcoming_events": stock_events.get("upcoming", []),
    }


def generate_all_predictions(
    reference_date: Optional[date] = None,
    data_cutoff_dt: Optional[datetime] = None,
    target_trade_date: Optional[str] = None,
    market_state: Optional[Dict[str, Any]] = None,
    regime: Optional[Dict[str, Any]] = None,
    features: Optional[Dict[str, Any]] = None,
    surprises: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Run prediction engine across all 10 Nifty 50 universe stocks concurrently.
    """
    now_utc = datetime.now(timezone.utc)
    if reference_date is None:
        reference_date = now_utc.date()
    if data_cutoff_dt is None:
        data_cutoff_dt = now_utc

    macro_articles = fetch_macro_news(max_items=8, cutoff_dt=data_cutoff_dt)
    symbols = list(NIFTY50_UNIVERSE.keys())

    def _predict(sym: str) -> Dict[str, Any]:
        return generate_stock_prediction(
            symbol=sym,
            macro_articles=macro_articles,
            reference_date=reference_date,
            data_cutoff_dt=data_cutoff_dt,
            target_trade_date=target_trade_date,
            market_state=market_state,
            regime=regime,
            features=features,
            surprises=surprises,
        )

    with ThreadPoolExecutor(max_workers=5) as executor:
        predictions = list(executor.map(_predict, symbols))

    return predictions
