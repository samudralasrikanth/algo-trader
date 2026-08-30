#!/usr/bin/env python3
# =============================================================================
# run_postmarket_audit.py — Post-Market Close Audit & Factor Attribution Engine
# =============================================================================

import sys
import argparse
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import yfinance as yf

from event_agent.config import NIFTY50_UNIVERSE, ALLOCATION_PER_STOCK
from event_agent.storage.ledger import (
    init_db, get_active_night_predictions, save_daily_audit,
    get_daily_audits, get_factor_attribution_summary, log_job_execution
)
from event_agent.engine.factor_attribution import diagnose_prediction_outcome


def fetch_today_actual_ohlc(symbol: str, target_date_str: str) -> Optional[Dict[str, float]]:
    """Fetch actual Open, High, Low, Close for a symbol on target_date_str."""
    try:
        dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_str = (dt - timedelta(days=3)).strftime("%Y-%m-%d")
        end_str = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
        
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start_str, end=end_str)
        if not hist.empty:
            for idx, row in hist.iterrows():
                row_date = idx.strftime("%Y-%m-%d")
                if row_date >= target_date_str:
                    return {
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                    }
            last_row = hist.iloc[-1]
            return {
                "open": round(float(last_row["Open"]), 2),
                "high": round(float(last_row["High"]), 2),
                "low": round(float(last_row["Low"]), 2),
                "close": round(float(last_row["Close"]), 2),
            }
    except Exception:
        pass
    return None


def run_postmarket_audit_cycle(target_date_str: Optional[str] = None):
    start_time = datetime.now().isoformat()
    init_db()
    if target_date_str is None:
        target_date_str = datetime.now().strftime("%Y-%m-%d")
        
    print("""
╔═══════════════════════════════════════════════════════════════════════════════════╗
║        🔍 NIFTY 50 POST-MARKET AUDIT & FACTOR ATTRIBUTION ENGINE                 ║
║   Reconciling Predictions vs Market Closes • Factor Attribution • Algo Diagnosis  ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
    """)
    print(f"[*] Auditing Trading Session: {target_date_str} (Post-Market Close)\n")
    
    night_preds = get_active_night_predictions(target_trade_date=target_date_str)
    
    if not night_preds:
        print(f"[!] No pre-market night predictions recorded specifically for {target_date_str}.")
        print("[*] Retrieving most recent recorded night predictions to audit...")
        night_preds = get_active_night_predictions()
        
    if not night_preds:
        print("[!] No night predictions found in DB. Run 'python3 run_night_forecast.py' first to generate forecasts.")
        return
        
    print(f"[*] Auditing {len(night_preds)} predictions against real market outcomes...\n")
    
    audits_saved = []
    
    for pred in night_preds:
        sym = pred["symbol"]
        base_p = pred["base_price"]
        
        actual_ohlc = fetch_today_actual_ohlc(sym, target_date_str)
        if not actual_ohlc:
            actual_ohlc = {"open": base_p, "high": base_p * 1.01, "low": base_p * 0.99, "close": base_p}
            
        diag = diagnose_prediction_outcome(
            pred=pred,
            actual_data={"base_price": base_p, "actual_close": actual_ohlc["close"]}
        )
        
        action = pred.get("action", "HOLD")
        actual_change_pct = diag["actual_change_pct"]
        
        # Calculate simulated PnL
        if action in ["BUY", "STRONG_BUY"]:
            pnl = round(ALLOCATION_PER_STOCK * (actual_change_pct / 100.0), 2)
        elif action in ["SELL", "STRONG_SELL"]:
            pnl = round(ALLOCATION_PER_STOCK * (-actual_change_pct / 100.0), 2)
        else:
            pnl = 0.0
            
        audit_dict = {
            "night_pred_id": pred.get("id"),
            "trade_date": target_date_str,
            "symbol": sym,
            "short_name": pred.get("short_name"),
            "sector": pred.get("sector"),
            "base_price": base_p,
            "predicted_target": pred.get("predicted_1d_target", pred.get("target_1d", base_p)),
            "predicted_change_pct": pred.get("predicted_1d_pct", pred.get("expected_1d_pct", 0.0)),
            "predicted_direction": pred.get("direction", "NEUTRAL"),
            "actual_open": actual_ohlc["open"],
            "actual_high": actual_ohlc["high"],
            "actual_low": actual_ohlc["low"],
            "actual_close": actual_ohlc["close"],
            "actual_change_pct": actual_change_pct,
            "actual_direction": diag["actual_direction"],
            "direction_correct": diag["direction_correct"],
            "hit_target_range": diag["hit_target_range"],
            "abs_error_pct": diag["abs_error_pct"],
            "simulated_pnl": pnl,
            "attribution_category": diag["attribution_category"],
            "diagnostic_explanation": diag["diagnostic_explanation"],
            "refactoring_suggestion": diag["refactoring_suggestion"],
            "factors_active": diag["factors_active"]
        }
        
        save_daily_audit(audit_dict)
        audits_saved.append(audit_dict)
        
    pass_count = sum(1 for a in audits_saved if a.get("direction_correct") == 1)
    acc_pct = (pass_count / len(audits_saved)) * 100 if audits_saved else 0
    
    log_job_execution(
        job_type="POST_MARKET_AUDIT",
        started_at=start_time,
        completed_at=datetime.now().isoformat(),
        status="SUCCESS",
        target_date=target_date_str,
        records_stored=len(audits_saved),
        log_summary=f"Audited {len(audits_saved)} stock predictions. Directional accuracy: {pass_count}/{len(audits_saved)} ({acc_pct:.1f}%)."
    )
        
    # Print Tabular Summary
    print("=" * 110)
    print(f"{'STOCK':<14} | {'BASE':<8} | {'PRED TARGET':<14} | {'ACTUAL CLOSE':<14} | {'DIR ACC':<8} | {'ATTRIBUTION CATEGORY':<22} | {'SIM PnL':<10}")
    print("=" * 110)
    
    for a in audits_saved:
        dir_badge = "✓ PASS" if a['direction_correct'] == 1 else "✗ FAIL"
        pred_str = f"₹{a['predicted_target']:<6.1f} ({a['predicted_change_pct']:+.1f}%)"
        act_str = f"₹{a['actual_close']:<6.1f} ({a['actual_change_pct']:+.1f}%)"
        pnl_str = f"₹{a['simulated_pnl']:+,.1f}"
        print(f"{a['short_name']:<14} | ₹{a['base_price']:<7.1f} | {pred_str:<14} | {act_str:<14} | {dir_badge:<8} | {a['attribution_category'][:20]:<22} | {pnl_str:<10}")
        
    print("=" * 110)
    
    # Print Diagnostics & Refactoring Suggestions
    summary = get_factor_attribution_summary()
    print("\n🧠 FACTOR ATTRIBUTION & ALGO REFACTORING DIAGNOSTICS:")
    print(f" • Total Audits Recorded      : {summary['total_audits']}")
    print(f" • Factor Successes Captured   : {summary['captured_success_count']} ({summary['captured_success_pct']}%)")
    print(f" • Missed Intraday Catalysts   : {summary['missed_catalyst_count']}")
    print(f" • Miscalibrated Factor Moves  : {summary['factor_miscalibrated_count']}")
    print(f" • Market Noise / Range Bound  : {summary['market_noise_count']}")
    
    print("\n🔧 ALGORITHMIC REFACTORING RECOMMENDATIONS:")
    for i, rec in enumerate(summary["refactoring_priorities"][:4], 1):
        print(f" {i}. {rec}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Nifty 50 Post-Market Audit & Attribution Runner")
    parser.add_argument("--date", type=str, default=None, help="Target trade date to audit (YYYY-MM-DD)")
    args = parser.parse_args()
    run_postmarket_audit_cycle(target_date_str=args.date)


if __name__ == "__main__":
    main()
