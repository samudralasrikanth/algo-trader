#!/usr/bin/env python3
# =============================================================================
# run_night_forecast.py — Pre-Market / Night Forecast Runner for Tomorrow (v3.0)
# =============================================================================

import os
import sys
from datetime import datetime, date, timedelta
from typing import Optional
from event_agent.config import NIFTY50_UNIVERSE
from event_agent.engine.prediction_algo import generate_all_predictions, MODEL_VERSION
from event_agent.storage.ledger import init_db, save_night_prediction, get_active_night_predictions, log_job_execution
from event_agent.research.model_versioning import get_current_version_record
from event_agent.arena.market_clock import MarketClock


def get_next_trading_day(ref_date: Optional[date] = None) -> str:
    """Calculate the next NSE trading date, including official holidays."""
    if ref_date is None:
        ref_date = datetime.now().date()
        
    next_day = ref_date + timedelta(days=1)
    while not MarketClock.is_trading_day(datetime.combine(next_day, datetime.min.time())):
        next_day += timedelta(days=1)
    return next_day.strftime("%Y-%m-%d")


def get_forecast_target_date(ref_dt: Optional[datetime] = None) -> str:
    """Resolve the session this forecast should feed.

    GitHub Actions schedules can be delayed past midnight. In that case,
    blindly forecasting tomorrow skips the current session and leaves the
    intraday cycle with no locked predictions. Before the NSE opens, a run
    should therefore target today's trading session; after the open it should
    target the next trading session.

    FORECAST_TARGET_DATE is an explicit recovery/operator override used by
    workflow_dispatch and is validated against the NSE trading calendar.
    """
    override = os.getenv("FORECAST_TARGET_DATE", "").strip()
    if override:
        try:
            requested = date.fromisoformat(override)
        except ValueError as exc:
            raise ValueError("FORECAST_TARGET_DATE must be YYYY-MM-DD") from exc
        if not MarketClock.is_trading_day(datetime.combine(requested, datetime.min.time())):
            raise ValueError(f"FORECAST_TARGET_DATE is not an NSE trading day: {override}")
        return override

    current = ref_dt or datetime.now()
    current_date = current.date()
    if MarketClock.is_trading_day(datetime.combine(current_date, datetime.min.time())):
        market_minutes = current.hour * 60 + current.minute
        if market_minutes < 9 * 60 + 15:
            return current_date.strftime("%Y-%m-%d")
    return get_next_trading_day(current_date)


def run_night_forecast_cycle():
    start_time = datetime.now().isoformat()
    init_db()
    today_str = datetime.now().strftime("%Y-%m-%d")
    target_trade_date = get_forecast_target_date()
    version_rec = get_current_version_record()
    
    print("""
╔═══════════════════════════════════════════════════════════════════════════════════╗
║       🌙 NIFTY 50 QUANTITATIVE PREDICTION AGENT (V3.0 EXPERIMENTAL DECK)         ║
║   Point-in-Time Conditioning, 8-Dim Regime, 5 Baselines, Risk-Based Sizing        ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
    """)
    print(f"[*] Forecast Generated On : {today_str} (Pre-Market / Evening Lock)")
    print(f"[*] Target Trading Session : {target_trade_date} (Next Market Open)")
    print(f"[*] Model Version          : {version_rec['model_version']} (Regime: {version_rec['regime_version']}, Weights: {version_rec['weights_version']})\n")
    
    print("[1/2] Processing news, macro catalysts, 8-dimension regime, and 5 benchmark baselines...")
    predictions = generate_all_predictions(target_trade_date=target_trade_date)
    
    print(f"[2/2] Freezing cryptographic prediction snapshots for {len(predictions)} stocks into immutable ledger...")
    for p in predictions:
        save_night_prediction(p, target_trade_date=target_trade_date)
        
    log_job_execution(
        job_type="PRE_MARKET_NIGHT_FORECAST",
        started_at=start_time,
        completed_at=datetime.now().isoformat(),
        status="SUCCESS",
        target_date=target_trade_date,
        records_stored=len(predictions),
        log_summary=f"Successfully generated and locked {len(predictions)} v3 stock prediction snapshots for session {target_trade_date}."
    )
        
    print("\n" + "=" * 115)
    print(f"{'SYMBOL':<14} | {'ACTION':<10} | {'ENTRY (₹)':<10} | {'TARGET (₹)':<16} | {'STOP (₹)':<10} | {'QTY':<5} | {'CONV %':<6} | {'BASELINES':<10}")
    print("=" * 115)
    
    for p in predictions:
        exp_pct = p.get('expected_1d_pct', 0.0)
        target_str = f"₹{p['target_price']:<7.1f} ({exp_pct:+.1f}%)"
        summary = p.get('baselines', {}).get('summary', {})
        base_summary = f"{summary.get('bullish_count', 0)}U / {summary.get('bearish_count', 0)}D"
        print(
            f"{p['short_name']:<14} | {p['action']:<10} | ₹{p['entry_price']:<9.1f} | {target_str:<16} | "
            f"₹{p['stop_loss']:<9.1f} | {p.get('suggested_quantity', 0):<5} | {p['conviction']:<6.1f} | {base_summary:<10}"
        )
        
    print("=" * 115)
    print(f"\n[✓] All {len(predictions)} prediction snapshots locked with SHA-256 provenance hashes.")
    print(f"[✓] Run 'python3 run_postmarket_audit.py' post-market (15:45 IST) to audit 5-min candle execution against all 5 baselines.\n")


if __name__ == "__main__":
    run_night_forecast_cycle()
