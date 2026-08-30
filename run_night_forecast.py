#!/usr/bin/env python3
# =============================================================================
# run_night_forecast.py — Pre-Market / Night Forecast Runner for Tomorrow
# =============================================================================

import sys
from datetime import datetime, date, timedelta
from typing import Optional
from event_agent.config import NIFTY50_UNIVERSE
from event_agent.engine.prediction_algo import generate_all_predictions
from event_agent.storage.ledger import init_db, save_night_prediction, get_active_night_predictions, log_job_execution


def get_next_trading_day(ref_date: Optional[date] = None) -> str:
    """Calculate the next trading date (skipping weekends)."""
    if ref_date is None:
        ref_date = datetime.now().date()
        
    next_day = ref_date + timedelta(days=1)
    # If next_day is Saturday (5), shift to Monday (0)
    if next_day.weekday() == 5:
        next_day += timedelta(days=2)
    elif next_day.weekday() == 6:
        next_day += timedelta(days=1)
        
    return next_day.strftime("%Y-%m-%d")


def run_night_forecast_cycle():
    start_time = datetime.now().isoformat()
    init_db()
    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_trade_date = get_next_trading_day()
    
    print("""
╔═══════════════════════════════════════════════════════════════════════════════════╗
║       🌙 NIFTY 50 PRE-MARKET / NIGHT PREDICTION AGENT (TOMORROW'S DECK)          ║
║   Ingesting Tonight's Catalysts & Locking Forecasts for Next Trading Session     ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
    """)
    print(f"[*] Forecast Generated On : {today_str} (Evening / Pre-Market)")
    print(f"[*] Target Trading Session : {tomorrow_trade_date} (Next Market Open)\n")
    
    print("[1/2] Scraping tonight's news, corporate announcements & macroeconomic catalysts...")
    predictions = generate_all_predictions()
    
    print(f"[2/2] Locking predictions and active factor vectors for {len(predictions)} stocks into DB...")
    for p in predictions:
        save_night_prediction(p, target_trade_date=tomorrow_trade_date)
        
    log_job_execution(
        job_type="PRE_MARKET_NIGHT_FORECAST",
        started_at=start_time,
        completed_at=datetime.now().isoformat(),
        status="SUCCESS",
        target_date=tomorrow_trade_date,
        records_stored=len(predictions),
        log_summary=f"Successfully generated and locked {len(predictions)} stock predictions for session {tomorrow_trade_date}."
    )
        
    print("\n" + "=" * 94)
    print(f"{'SYMBOL':<14} | {'SECTOR':<22} | {'BASE (₹)':<9} | {'ACTION':<11} | {'TOMORROW TARGET':<16} | {'CONV %':<6}")
    print("=" * 94)
    
    for p in predictions:
        exp_pct = p.get('expected_1d_pct', 0.0)
        target_str = f"₹{p['target_1d']:<7.1f} ({exp_pct:+.1f}%)"
        print(f"{p['short_name']:<14} | {p['sector'][:20]:<22} | ₹{p['base_price']:<8.1f} | {p['action']:<11} | {target_str:<16} | {p['conviction']}%")
        
    print("=" * 94)
    print(f"\n[✓] All forecasts locked for {tomorrow_trade_date}. Run 'python3 run_postmarket_audit.py' tomorrow post-market (15:45 IST) to audit accuracy & diagnose factors.\n")


if __name__ == "__main__":
    from typing import Optional
    run_night_forecast_cycle()
