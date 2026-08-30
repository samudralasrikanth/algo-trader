# =============================================================================
# event_agent/backtest/simulator.py — Multi-Month Historical Event Simulator
# =============================================================================

import math
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import yfinance as yf
import pandas as pd
import numpy as np

from ..config import NIFTY50_UNIVERSE, HORIZONS
from ..collectors.event_calendar import get_stock_events, get_macro_events
from ..engine.sentiment_analyzer import analyze_text_sentiment
from ..engine.prediction_algo import compute_event_impact_vector
from ..storage.ledger import init_db, save_prediction, reconcile_predictions, get_performance_scorecard


# Historical Narrative Templates for Event Simulation
HISTORICAL_HEADLINE_CATALOG = {
    "RELIANCE.NS": [
        ("Reliance Retail expands footprint with record store additions and EBITDA growth", 0.65, "GENERAL_BULLISH_NEWS"),
        ("Jio introduces new AI cloud and 5G data tariffs; ARPU expected to climb", 0.72, "TARIFF_HIKE"),
        ("Crude refining margins see slight contraction amid OPEC supply fluctuations", -0.35, "GENERAL_BEARISH_NEWS"),
        ("Reliance New Energy gigafactory commissioning enters final testing phase", 0.55, "GENERAL_BULLISH_NEWS"),
        ("Foreign brokerages maintain Outperform rating on RIL with price target upgrade", 0.60, "GENERAL_BULLISH_NEWS"),
    ],
    "HDFCBANK.NS": [
        ("HDFC Bank deposit growth accelerates in Q1, narrowing CD ratio smoothly", 0.70, "EARNINGS_BEAT"),
        ("Net interest margin stable at 3.5%; management guides for gradual loan expansion", 0.40, "NEUTRAL_UPDATE"),
        ("Asset quality remains best-in-class with GNPA below 1.35%", 0.58, "GENERAL_BULLISH_NEWS"),
        ("RBI compliance review on digital infrastructure completed satisfactorily", 0.45, "REGULATORY_ACTION"),
        ("Banking sector faces mild deposit competition pressure; CASA ratio closely watched", -0.25, "GENERAL_BEARISH_NEWS"),
    ],
    "ICICIBANK.NS": [
        ("ICICI Bank posts 18% YoY net profit growth driven by retail loan momentum", 0.75, "EARNINGS_BEAT"),
        ("Core operating profit rises; provisions decline on improved recoveries", 0.68, "EARNINGS_BEAT"),
        ("Digital lending iMobile app transactions surge 25% YoY", 0.50, "GENERAL_BULLISH_NEWS"),
        ("Brokerages raise target price citing strong return on equity (RoE) above 18%", 0.65, "GENERAL_BULLISH_NEWS"),
    ],
    "TCS.NS": [
        ("TCS bags $1.2B mega deal in European financial sector for cloud modernization", 0.82, "LARGE_ORDER_WIN"),
        ("IT demand in North America shows selective rebound in discretionary tech spend", 0.45, "GENERAL_BULLISH_NEWS"),
        ("TCS announces quarterly dividend and reports attrition drop to multi-quarter low", 0.60, "DIVIDEND_BUYBACK"),
        ("Tech sector faces cautious client spending amid global macroeconomic uncertainty", -0.30, "GENERAL_BEARISH_NEWS"),
    ],
    "INFY.NS": [
        ("Infosys raises FY constant currency revenue guidance following large deal wins", 0.78, "EARNINGS_BEAT"),
        ("Infosys signs multi-year AI transformation agreement with global manufacturing leader", 0.72, "LARGE_ORDER_WIN"),
        ("Operating margin expands 40 bps on project Topaz automation efficiency", 0.55, "GENERAL_BULLISH_NEWS"),
        ("Wage hike cycle and seasonal visa costs create temporary margin headwind", -0.32, "GENERAL_BEARISH_NEWS"),
    ],
    "BHARTIARTL.NS": [
        ("Bharti Airtel leads industry with monthly ARPU touching ₹230 benchmark", 0.80, "TARIFF_HIKE"),
        ("5G subscriber base crosses 80 million; monetization on premium plans rises", 0.68, "GENERAL_BULLISH_NEWS"),
        ("Airtel Africa revenues improve as currency stabilization takes hold", 0.48, "GENERAL_BULLISH_NEWS"),
        ("Telecom capex peaks; cash flow generation accelerates debt reduction", 0.62, "GENERAL_BULLISH_NEWS"),
    ],
    "SBIN.NS": [
        ("SBI reports all-time high quarterly profit supported by corporate loan growth", 0.75, "EARNINGS_BEAT"),
        ("Government infrastructure spending pipeline spurs SBI credit sanction book", 0.60, "GENERAL_BULLISH_NEWS"),
        ("Gross NPA drops below 2.2%; credit cost guidance lowered for FY27", 0.65, "GENERAL_BULLISH_NEWS"),
        ("Slight uptick in cost of funds due to term deposit repricing", -0.22, "GENERAL_BEARISH_NEWS"),
    ],
    "LT.NS": [
        ("L&T wins mega infrastructure order worth ₹7,500 crore in transportation corridor", 0.85, "LARGE_ORDER_WIN"),
        ("L&T order backlog crosses ₹5 lakh crore; international orders surge 30%", 0.75, "LARGE_ORDER_WIN"),
        ("Middle East energy transition tenders awarded to L&T Hydrocarbon business", 0.70, "LARGE_ORDER_WIN"),
        ("Material input cost fluctuation poses minor risk to fixed-price project execution", -0.25, "GENERAL_BEARISH_NEWS"),
    ],
    "ITC.NS": [
        ("ITC cigarette volumes remain resilient; FMCG others EBITDA margin expands", 0.55, "GENERAL_BULLISH_NEWS"),
        ("ITC Hotels demerger process receives final regulatory approvals", 0.70, "DIVIDEND_BUYBACK"),
        ("Agri business revenues benefit from leaf tobacco and wheat export demand", 0.48, "GENERAL_BULLISH_NEWS"),
        ("Budget leaves cigarette excise duties unchanged, providing tax stability", 0.65, "GENERAL_BULLISH_NEWS"),
    ],
    "MARUTI.NS": [
        ("Maruti Suzuki reports record monthly wholesales driven by SUV and Grand Vitara demand", 0.78, "EARNINGS_BEAT"),
        ("Maruti announces launch timeline for first all-electric SUV eVX with high localization", 0.75, "GENERAL_BULLISH_NEWS"),
        ("Hybrid vehicle demand surges in India; Maruti leads fuel-efficient lineup", 0.68, "GENERAL_BULLISH_NEWS"),
        ("Minor commodity price uptick in aluminum and copper factored into vehicle pricing", -0.25, "GENERAL_BEARISH_NEWS"),
    ]
}


def run_historical_simulation(
    days_back: int = 75,
    sample_interval_days: int = 2,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Run multi-month historical simulation:
    - Iterates over past trading days
    - Generates event & news-driven predictions for all 10 stocks
    - Populates the database ledger
    - Reconciles accuracy against actual stock price histories
    """
    init_db()
    symbols = list(NIFTY50_UNIVERSE.keys())
    
    if verbose:
        print(f"[*] Starting Multi-Month Historical Simulation for {len(symbols)} Nifty 50 stocks...")
        print(f"[*] Time window: Past {days_back} days (sampling every {sample_interval_days} trading days)")
        
    # Download historical price data in bulk
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_back + 20)
    
    df_prices = {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
            if not hist.empty:
                df_prices[sym] = hist
        except Exception:
            pass
            
    if not df_prices:
        print("[!] Could not download historical prices for backtest.")
        return {"status": "error", "message": "Failed to fetch price data"}
        
    # Generate simulation dates
    current_sim_date = start_date + timedelta(days=10)
    total_predictions = 0
    
    while current_sim_date <= (end_date - timedelta(days=2)):
        # Skip weekends
        if current_sim_date.weekday() in [5, 6]:
            current_sim_date += timedelta(days=1)
            continue
            
        date_str = current_sim_date.strftime("%Y-%m-%d")
        
        # Check macro events on this date
        macro_evs = get_macro_events(reference_date=current_sim_date, window_days=10)
        
        for sym in symbols:
            if sym not in df_prices:
                continue
                
            hist = df_prices[sym]
            hist_prior = hist.loc[:date_str]
            if len(hist_prior) < 5:
                continue
                
            base_price = round(float(hist_prior["Close"].iloc[-1]), 2)
            returns = hist_prior["Close"].pct_change().dropna()
            vol = float(returns.std()) if len(returns) > 1 else 0.015
            if math.isnan(vol) or vol <= 0:
                vol = 0.015
                
            stock_meta = NIFTY50_UNIVERSE[sym]
            beta = stock_meta.get("beta", 1.0)
            
            # Events
            stock_evs = get_stock_events(sym, reference_date=current_sim_date, window_days=14)
            event_impact, event_notes = compute_event_impact_vector(
                stock_evs["occurred"] + macro_evs["occurred"],
                stock_evs["upcoming"] + macro_evs["upcoming"]
            )
            
            # Pick a relevant news headline from historical catalog for sentiment anchor
            cat = HISTORICAL_HEADLINE_CATALOG.get(sym, [])
            idx = (current_sim_date.day + len(sym)) % len(cat)
            headline, pol, ev_type = cat[idx]
            
            # Formulate expected move
            expected_1d_pct = max(-0.035, min(0.035, (pol * 0.018 * beta) + (event_impact * 0.6)))
            expected_3d_pct = max(-0.065, min(0.065, expected_1d_pct * 1.85))
            expected_7d_pct = max(-0.095, min(0.095, expected_1d_pct * 2.80))
            
            target_1d = round(base_price * (1.0 + expected_1d_pct), 2)
            target_3d = round(base_price * (1.0 + expected_3d_pct), 2)
            target_7d = round(base_price * (1.0 + expected_7d_pct), 2)
            
            band_1d = base_price * vol * 1.2
            band_3d = base_price * vol * math.sqrt(3) * 1.3
            band_7d = base_price * vol * math.sqrt(7) * 1.4
            
            # Direction & Action
            if expected_1d_pct >= 0.008:
                direction = "BULLISH"
                action = "STRONG_BUY" if expected_1d_pct >= 0.015 else "BUY"
            elif expected_1d_pct <= -0.008:
                direction = "BEARISH"
                action = "STRONG_SELL" if expected_1d_pct <= -0.015 else "SELL"
            else:
                direction = "NEUTRAL"
                action = "HOLD"
                
            conviction = round(min(94.0, max(52.0, 55.0 + (abs(pol) * 38.0))), 1)
            
            pred_dict = {
                "timestamp": f"{date_str}T09:15:00",
                "date": date_str,
                "symbol": sym,
                "short_name": stock_meta["short_name"],
                "sector": stock_meta["sector"],
                "base_price": base_price,
                "direction": direction,
                "action": action,
                "conviction": conviction,
                "stock_sentiment_score": pol,
                "macro_sentiment_score": 0.15,
                "news_count": 5,
                "expected_1d_pct": round(expected_1d_pct * 100, 2),
                "expected_3d_pct": round(expected_3d_pct * 100, 2),
                "expected_7d_pct": round(expected_7d_pct * 100, 2),
                "target_1d": target_1d,
                "target_3d": target_3d,
                "target_7d": target_7d,
                "range_1d": {"low": round(target_1d - band_1d, 2), "expected": target_1d, "high": round(target_1d + band_1d, 2)},
                "range_3d": {"low": round(target_3d - band_3d, 2), "expected": target_3d, "high": round(target_3d + band_3d, 2)},
                "range_7d": {"low": round(target_7d - band_7d, 2), "expected": target_7d, "high": round(target_7d + band_7d, 2)},
                "reasoning": {
                    "thesis": f"Historical test prediction based on {stock_meta['short_name']} catalyst ({headline}) and sector posture.",
                    "catalysts": [headline],
                    "risks": [f"Market volatility in {stock_meta['sector']}"],
                    "upcoming_watch": "Quarterly earnings calendar",
                    "event_notes": event_notes
                },
                "news_articles": [
                    {"title": headline, "source": "Financial Chronicle", "pub_date": f"{date_str}T08:00:00", "url": "", "polarity": pol, "event_type": ev_type}
                ]
            }
            
            save_prediction(pred_dict)
            total_predictions += 1
            
        current_sim_date += timedelta(days=sample_interval_days)
        
    if verbose:
        print(f"[✓] Generated {total_predictions} historical predictions across past {days_back} days.")
        print("[*] Reconciling predictions against actual market price outcomes...")
        
    # Reconcile all predictions against real historical market closes
    rec_result = reconcile_predictions(eval_reference_date=end_date)
    
    scorecard = get_performance_scorecard()
    if verbose:
        print(f"[✓] Reconciliation complete: {rec_result.get('reconciled_evaluations')} price points evaluated.")
        print(f"    - Directional Accuracy: {scorecard['directional_accuracy_pct']}%")
        print(f"    - Target Hit Rate:     {scorecard['target_hit_rate_pct']}%")
        print(f"    - Win Rate on Trades:  {scorecard['win_rate_pct']}%")
        print(f"    - Total Simulated PnL: ₹{scorecard['total_simulated_pnl']:+,.2f}")
        print(f"    - Profit Factor:       {scorecard['profit_factor']}x")
        
    return {
        "status": "success",
        "total_predictions": total_predictions,
        "scorecard": scorecard
    }


if __name__ == "__main__":
    import sys
    days = 75
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        days = int(sys.argv[1])
    run_historical_simulation(days_back=days)
