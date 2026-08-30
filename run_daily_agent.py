#!/usr/bin/env python3
# =============================================================================
# run_daily_agent.py — Daily Autonomous Workflow Runner for Nifty 50 Event Algo
# =============================================================================

import sys
import argparse
from datetime import datetime
from event_agent.config import NIFTY50_UNIVERSE
from event_agent.engine.prediction_algo import generate_all_predictions
from event_agent.storage.ledger import init_db, save_prediction, reconcile_predictions, get_performance_scorecard
from event_agent.backtest.simulator import run_historical_simulation


def print_banner():
    print("""
╔═══════════════════════════════════════════════════════════════════════════════════╗
║         🚀 NIFTY 50 EVENT & NEWS-DRIVEN PREDICTION AGENT WORKFLOW                ║
║    Zero-API Fundamental & Event-Driven Intelligence • 10 Core Nifty 50 Stocks    ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
    """)


def run_daily_workflow():
    print_banner()
    init_db()
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"[*] Execution Date: {today_str}")
    print(f"[*] Stock Universe: {len(NIFTY50_UNIVERSE)} Nifty 50 market leaders\n")
    
    print("[1/3] Fetching latest market news, corporate filings & macroeconomic events...")
    predictions = generate_all_predictions()
    
    print(f"[2/3] Analyzing event impact & generating price forecasts for {len(predictions)} stocks...")
    for pred in predictions:
        pred_id = save_prediction(pred)
        
    print("[3/3] Reconciling prior predictions against latest closing prices...")
    rec_result = reconcile_predictions()
    scorecard = get_performance_scorecard()
    
    print("\n" + "=" * 90)
    print(f"{'SYMBOL':<14} | {'SECTOR':<22} | {'BASE (₹)':<9} | {'ACTION':<11} | {'1D TARGET':<10} | {'3D TARGET':<10} | {'CONV %':<6}")
    print("=" * 90)
    
    for p in predictions:
        act_color = p['action']
        print(f"{p['short_name']:<14} | {p['sector'][:20]:<22} | ₹{p['base_price']:<8.1f} | {act_color:<11} | ₹{p['target_1d']:<9.1f} | ₹{p['target_3d']:<9.1f} | {p['conviction']}%")
        
    print("=" * 90)
    
    print("\n📊 AGENT PERFORMANCE & ACCURACY SCORECARD (Historical Multi-Month Tracking):")
    print(f" • Total Evaluated Predictions : {scorecard['total_evaluations']}")
    print(f" • Directional Accuracy Rate   : {scorecard['directional_accuracy_pct']}%")
    print(f" • Target Range Hit Rate       : {scorecard['target_hit_rate_pct']}%")
    print(f" • Win Rate on Signals (PnL)   : {scorecard['win_rate_pct']}% ({scorecard['win_count']} Wins / {scorecard['loss_count']} Losses)")
    print(f" • Total Simulated Portfolio PnL: ₹{scorecard['total_simulated_pnl']:+,.2f}")
    print(f" • Profit Factor               : {scorecard['profit_factor']}x")
    print("\n[✓] Daily agent cycle completed successfully. All records saved to SQLite ledger.\n")


def main():
    parser = argparse.ArgumentParser(description="Nifty 50 Event-Driven Daily Prediction Agent")
    parser.add_argument("--backtest", action="store_true", help="Run multi-month historical backtest simulation")
    parser.add_argument("--days", type=int, default=75, help="Number of past days for backtest simulation")
    args = parser.parse_args()
    
    if args.backtest:
        print_banner()
        run_historical_simulation(days_back=args.days)
    else:
        run_daily_workflow()


if __name__ == "__main__":
    main()
