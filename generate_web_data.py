#!/usr/bin/env python3
# =============================================================================
# generate_web_data.py — Pre-renders V3.2 Arena DB & Analytics for Web UI
# =============================================================================

import os
import json
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
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
    get_recent_daily_trade_reports, get_all_orders, get_agent_positions,
    clean_stale_test_positions
)
from event_agent.engine.live_market_feed import revalue_all_positions_live
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
    clean_stale_test_positions()
    live_reval = revalue_all_positions_live()
    print(f"[*] Live Position Revaluation: {live_reval.get('status')} | Updated {live_reval.get('updated_positions_count', 0)} positions | Unrealized P&L: ₹{live_reval.get('total_unrealized_pnl', 0.0):+,.2f}")

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

    # Revalue all positions with live market rates immediately after cycle
    live_reval = revalue_all_positions_live()
    print(f"[*] Live Market Revaluation: {live_reval.get('status')} | Updated {live_reval.get('updated_positions_count', 0)} positions | Live P&L: ₹{live_reval.get('total_unrealized_pnl', 0.0):+,.2f}")

    if live_reval.get("status") == "SUCCESS":
        inv = live_reval["total_cost_basis"]
        mkt_val = live_reval["total_market_value"]
        pnl = live_reval["total_unrealized_pnl"]
        cash = arena_result["summary"]["total_arena_cash"]
        arena_result["summary"]["total_arena_invested"] = inv
        arena_result["summary"]["total_arena_pnl"] = pnl
        arena_result["summary"]["total_arena_value"] = round(cash + mkt_val, 2)
        arena_result["summary"]["total_active_positions"] = live_reval["active_positions_count"]
        arena_result["summary"]["total_arena_return_pct"] = round((arena_result["summary"]["total_arena_value"] - 10000000.0) / 10000000.0 * 100, 2)

        # Synchronize each agent's portfolio & leaderboard with live MTM rates
        from event_agent.storage.ledger import get_agent_positions
        import collections
        open_db_pos = [p for p in get_agent_positions() if p.get("status") == "OPEN"]
        agent_pos_map = collections.defaultdict(list)
        for p in open_db_pos:
            agent_pos_map[p["agent_id"]].append(p)

        for aid in ["ALPHA", "MOMENTUM", "MACRO", "DEFENSIVE", "CONTRARIAN"]:
            pos_list = agent_pos_map.get(aid, [])
            a_inv = round(sum(float(p.get("cost_basis") or 0.0) for p in pos_list), 2)
            a_pnl = round(sum(float(p.get("unrealized_pnl") or 0.0) for p in pos_list), 2)
            a_cash = round(max(0.0, 2000000.0 - a_inv), 2)
            a_nav = round(a_cash + a_inv + a_pnl, 2)
            a_ret = round(((a_nav - 2000000.0) / 2000000.0) * 100.0, 2)

            if "portfolios" in arena_result and aid in arena_result["portfolios"]:
                port = arena_result["portfolios"][aid]
                port["invested_capital"] = a_inv
                port["unrealized_pnl"] = a_pnl
                port["total_pnl"] = a_pnl
                port["current_cash"] = a_cash
                port["portfolio_value"] = a_nav
                port["return_pct"] = a_ret
                port["open_positions_count"] = len(pos_list)

                # Update live prices and PnL on holdings list
                if "holdings_by_instrument" in port and "all" in port["holdings_by_instrument"]:
                    for h in port["holdings_by_instrument"]["all"]:
                        match = next((p for p in pos_list if p.get("symbol") == h.get("symbol")), None)
                        if match:
                            h["current_price"] = match.get("current_price")
                            h["unrealized_pnl"] = match.get("unrealized_pnl")
                            h["pnl_pct"] = match.get("unrealized_pnl_pct")

            if "leaderboard" in arena_result:
                for lb_row in arena_result["leaderboard"]:
                    if lb_row.get("agent_id") == aid:
                        lb_row["portfolio_value"] = a_nav
                        lb_row["cash"] = a_cash
                        lb_row["invested"] = a_inv
                        lb_row["unrealized_pnl"] = a_pnl
                        lb_row["total_return_pct"] = a_ret
                        lb_row["day_return_pct"] = a_ret
                        lb_row["positions_count"] = len(pos_list)

        # Re-sort leaderboard by total_return_pct descending and update ranks & trophies
        if "leaderboard" in arena_result:
            arena_result["leaderboard"].sort(key=lambda x: x.get("total_return_pct", 0.0), reverse=True)
            for rank, r in enumerate(arena_result["leaderboard"], 1):
                r["rank"] = rank
                r["trophies"] = []
            if arena_result["leaderboard"]:
                arena_result["leaderboard"][0]["trophies"].append({
                    "code": "BEST_RETURN",
                    "icon": "🥇",
                    "title": "Best Return",
                    "desc": "Highest overall portfolio NAV return",
                })
                arena_result["summary"]["top_agent"] = arena_result["leaderboard"][0].get("name", "Agent Alpha")

    print(f"      Arena Value: ₹{arena_result['summary']['total_arena_value']:,.2f} | Capital Deployed: ₹{arena_result['summary']['total_arena_invested']:,.2f} | Live P&L: ₹{arena_result['summary']['total_arena_pnl']:+,.2f}")

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

    # V4.2 Real OpenRouter Telemetry & Forensic Failures
    try:
        from event_agent.engine.llm_provider import OpenRouterProvider
        from event_agent.storage.ledger import get_latest_ai_telemetry
        openrouter_status = OpenRouterProvider().check_runtime_connection()
        ai_telemetry_records = get_latest_ai_telemetry(limit=25)
        openrouter_status["recent_inferences"] = ai_telemetry_records
        payload["openrouter_telemetry"] = openrouter_status
    except Exception as ai_err:
        print(f"[!] Warning: OpenRouter telemetry check failed: {ai_err}")

    # V4.2.1 Event Sentinel & Continuous Intelligence Telemetry
    try:
        from event_agent.storage.ledger import (
            get_latest_sentinel_invocation,
            get_latest_event_coverage_metric,
            get_current_active_thesis,
            get_thesis_revisions,
            get_recent_sentinel_events,
        )
        from event_agent.storage.supabase_ledger import get_latest_sentinel_telemetry_supabase
        from event_agent.sentinel.economic_calendar import EconomicCalendar

        local_inv = get_latest_sentinel_invocation()
        cloud_inv = get_latest_sentinel_telemetry_supabase()
        
        # Authoritative telemetry preference: Cloud Supabase if available, fallback to local
        latest_inv = cloud_inv or local_inv or {}
        
        # Determine honest health status
        now_dt = datetime.now(timezone.utc)
        last_scan = latest_inv.get("completed_at") or latest_inv.get("started_at")
        sentinel_status = "HEALTHY"
        last_error = latest_inv.get("error")
        
        if not last_scan:
            sentinel_status = "OFFLINE"
            last_error = "No sentinel scan recorded yet"
        else:
            try:
                last_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
                elapsed_mins = (now_dt - last_dt).total_seconds() / 60.0
                if latest_inv.get("status") != "SUCCESS":
                    sentinel_status = "DEGRADED"
                    last_error = latest_inv.get("error") or f"Last execution returned {latest_inv.get('status')}"
                elif elapsed_mins > 10.0:
                    sentinel_status = "DEGRADED"
                    last_error = f"Heartbeat overdue: last scan {round(elapsed_mins)}m ago (schedule: 5m)"
            except Exception:
                pass

        # Calculate next expected invocation strictly from scheduler config (*/5 * * * *)
        cur_sec = now_dt.minute * 60 + now_dt.second
        next_5m_offset = 300 - (cur_sec % 300)
        next_expected_dt = now_dt + timedelta(seconds=next_5m_offset)
        next_expected_iso = next_expected_dt.strftime("%Y-%m-%d %H:%M:00 UTC")

        active_th = get_current_active_thesis() or {}
        th_revisions = get_thesis_revisions(active_th.get("thesis_id", "")) if active_th.get("thesis_id") else []
        cov_metrics = get_latest_event_coverage_metric() or {
            "scheduled_coverage_pct": 100.0,
            "scheduled_detected": 1,
            "scheduled_expected": 1,
            "source_coverage_pct": 100.0,
            "source_processed": 0,
            "source_available": 0,
            "material_processing_pct": 100.0,
            "material_processed": 0,
            "material_detected": 0,
        }
        calendar = EconomicCalendar()
        upcoming_cal = [e.to_dict() for e in calendar.get_upcoming_events(as_of=now_dt)]

        payload["event_sentinel"] = {
            "status": sentinel_status,
            "scheduler_cron": "*/5 * * * *",
            "cadence": "Every 5 minutes",
            "last_scan": last_scan,
            "next_expected_invocation": next_expected_iso,
            "last_error": last_error,
            "telemetry": latest_inv,
            "active_thesis": active_th,
            "thesis_revisions": th_revisions,
            "event_coverage": cov_metrics,
            "recent_events": get_recent_sentinel_events(limit=15),
            "economic_calendar": upcoming_cal,
            "cloud_persistence": "SUPABASE_AUTHORITATIVE",
            "lineage": latest_inv.get("lineage"),
        }
    except Exception as sentinel_err:
        print(f"[!] Warning: Event Sentinel telemetry export failed: {sentinel_err}")


    # Synchronize forensics failures in operations object
    failed_prominent = v3_payload.get("failed_trades_prominent", [])
    if "operations" not in payload:
        payload["operations"] = {}
    payload["operations"]["forensics"] = {
        "total_failures_audited": len(failed_prominent),
        "failures": failed_prominent,
    }

    print(f"[4/4] Writing output files to {DATA_JSON_PATH} and {DATA_JS_PATH}...")
    with open(DATA_JSON_PATH, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)

    with open(DATA_JS_PATH, "w", encoding="utf-8") as fp:
        fp.write(f"window.NEXUS_DATA = {json.dumps(payload)};\nwindow.INITIAL_DATA = window.NEXUS_DATA;\n")

    print(f"[✓] Successfully exported V3.2 Arena web payload to {DATA_JSON_PATH} and {DATA_JS_PATH}")


if __name__ == "__main__":
    export_web_dataset()
