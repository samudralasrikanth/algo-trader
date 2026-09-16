#!/usr/bin/env python3
# =============================================================================
# generate_web_data.py — Pre-renders V3.2 Arena DB & Analytics for Web UI
# =============================================================================

import os
import json
from pathlib import Path
from datetime import datetime, date, timedelta
import yfinance as yf
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from event_agent.config import NIFTY50_UNIVERSE, DB_PATH
from event_agent.collectors.event_calendar import get_stock_events, get_macro_events
from event_agent.storage.ledger import (
    init_db, get_latest_predictions, get_active_night_predictions,
    get_daily_audits, get_performance_scorecard, get_all_news,
    get_factor_attribution_summary, get_job_execution_logs, get_arena_data,
    get_recent_daily_trade_reports, get_all_orders, get_agent_positions
)
from event_agent.reporting.web_export import build_web_payload
from event_agent.arena.orchestrator import ArenaOrchestrator
from run_night_forecast import get_next_trading_day

# V4.0 Real-Money Readiness & Certification Engines
from event_agent.execution.environment import EnvironmentManager
from event_agent.risk.kill_switch import IndependentKillSwitch
from event_agent.certification.readiness_engine import RealMoneyReadinessEngine
from event_agent.certification.six_month_ledger import SixMonthCertificationLedger
from event_agent.certification.monte_carlo import MonteCarloPathSimulator
from event_agent.certification.stress_tester import AutomatedStressTester

WEB_DIR = Path(__file__).resolve().parent / "web_app"
WEB_DIR.mkdir(exist_ok=True, parents=True)
DATA_JSON_PATH = WEB_DIR / "data.json"
DATA_JS_PATH = WEB_DIR / "data.js"


def export_web_dataset():
    init_db()
    next_day_str = get_next_trading_day()
    scorecard = get_performance_scorecard()
    latest_preds = get_latest_predictions(limit=15)
    night_preds = get_active_night_predictions()
    daily_audits = get_daily_audits(limit=60)
    attribution_summary = get_factor_attribution_summary()
    all_news = get_all_news(limit=60)
    job_logs = get_job_execution_logs(limit=50)

    print("[1/4] Running V3.2 Arena Orchestration Cycle...")
    orch = ArenaOrchestrator()
    arena_result = orch.run_cycle(
        predictions=night_preds,
        force_execute=True,
    )
    print(f"      Arena Value: ₹{arena_result['summary']['total_arena_value']:,.2f} | Executed Trades: {arena_result['executed_trades_count']}")

    print("[2/4] Building full V3.2 Web Payload (Leaderboard, Consensus, Forensic Audits)...")
    v3_payload = build_web_payload(
        audit_records=daily_audits,
        predictions=night_preds,
        arena_cycle_result=arena_result,
    )

    # Fetch 3-month OHLC price series for major stocks for interactive chart
    print("[3/4] Fetching interactive price history for active stocks...")
    stock_charts = {}
    chart_symbols = list(NIFTY50_UNIVERSE.keys())[:10]
    for sym in chart_symbols:
        try:
            hist = yf.Ticker(sym).history(period="3mo")
            if not hist.empty:
                stock_charts[sym] = {
                    "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
                    "open": [round(float(v), 2) for v in hist["Open"]],
                    "high": [round(float(v), 2) for v in hist["High"]],
                    "low": [round(float(v), 2) for v in hist["Low"]],
                    "close": [round(float(v), 2) for v in hist["Close"]],
                    "volume": [int(v) for v in hist["Volume"]]
                }
        except Exception as e:
            print(f"[!] Warning: chart fetch failed for {sym}: {e}")

    # Stock Events
    stock_events_map = {}
    for sym in chart_symbols:
        stock_events_map[sym] = get_stock_events(sym, window_days=30)

    macro_events = get_macro_events(window_days=30)

    # Daily Automated Video Report & Social Broadcast
    recent_reports = get_recent_daily_trade_reports(limit=10)
    latest_report = recent_reports[0] if recent_reports else None

    # Merge existing data.json + V3 payload fields without wiping out scheduler/telemetry
    existing_data = {}
    if DATA_JSON_PATH.exists():
        try:
            with open(DATA_JSON_PATH, "r", encoding="utf-8") as existing_f:
                existing_data = json.load(existing_f)
        except Exception:
            existing_data = {}

    payload = dict(existing_data)
    payload.update(v3_payload)
    payload.update({
        "generated_at": datetime.now().isoformat(),
        "next_trading_day": next_day_str,
        "scorecard": scorecard,
        "latest_predictions": latest_preds,
        "night_predictions": night_preds,
        "daily_audits": daily_audits,
        "attribution_summary": attribution_summary,
        "job_logs": job_logs,
        "all_news": all_news,
        "orders": get_all_orders(limit=200),
        "agent_positions": get_agent_positions(),
        "universe": NIFTY50_UNIVERSE,
        "stock_charts": stock_charts,
        "stock_events": stock_events_map,
        "macro_events": macro_events,
        "daily_video_report": latest_report,
        "daily_video_report_history": recent_reports,
        # V4.0 Real-Money Readiness & Certification Payload
        "v4_readiness_audit": RealMoneyReadinessEngine.evaluate_readiness().to_dict(),
        "v4_six_month_calendar": SixMonthCertificationLedger().get_summary(),
        "v4_environment_metadata": EnvironmentManager.get_runtime_environment_metadata(),
        "v4_kill_switch_status": IndependentKillSwitch().get_status(),
        "v4_monte_carlo": MonteCarloPathSimulator.simulate().to_dict(),
        "v4_stress_test_summary": AutomatedStressTester.run_all_scenarios(),
    })

    print(f"[4/4] Writing output files to {DATA_JSON_PATH} and {DATA_JS_PATH}...")
    with open(DATA_JSON_PATH, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)

    with open(DATA_JS_PATH, "w", encoding="utf-8") as fp:
        fp.write(f"window.NEXUS_DATA = {json.dumps(payload)};\nwindow.INITIAL_DATA = window.NEXUS_DATA;\n")

    print(f"[✓] Successfully exported V3.2 Arena web payload to {DATA_JSON_PATH} and {DATA_JS_PATH}")


if __name__ == "__main__":
    export_web_dataset()
