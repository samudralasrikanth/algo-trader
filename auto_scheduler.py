#!/usr/bin/env python3
# =============================================================================
# auto_scheduler.py — Autonomous Daily Scheduler & Netlify Cloud Sync Engine
# =============================================================================

import os
import sys
import time
import subprocess
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from event_agent.storage.ledger import init_db, log_job_execution, get_job_execution_logs
from run_night_forecast import run_night_forecast_cycle, get_next_trading_day
from run_postmarket_audit import run_postmarket_audit_cycle
from generate_web_data import export_web_dataset

BASE_DIR = Path(__file__).resolve().parent

# IST Timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))


def get_current_ist() -> datetime:
    return datetime.now(IST)


def sync_to_netlify():
    """Regenerate static data and deploy to Netlify."""
    print("\n[*] Exporting database snapshot to web_app/data.json & data.js...")
    export_web_dataset()
    
    print("[*] Deploying updated data to Netlify...")
    try:
        cmd = ["npx", "-y", "netlify-cli", "deploy", "--dir=web_app", "--site-name", "nifty50-event-agent", "--prod", "--no-build"]
        res = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            print("[✓] Netlify deployment live! URL: https://nifty50-event-agent.netlify.app")
        else:
            print(f"[!] Netlify deploy warning: {res.stderr.strip()[:200]}")
    except Exception as e:
        print(f"[!] Netlify deployment error: {e}")


def execute_pre_market_job():
    print(f"\n[{get_current_ist().strftime('%Y-%m-%d %H:%M:%S IST')}] 🌙 EXECUTING AUTOMATED PRE-MARKET NIGHT FORECAST...")
    try:
        run_night_forecast_cycle()
        sync_to_netlify()
    except Exception as e:
        print(f"[!] Error in pre-market job: {e}")
        log_job_execution(
            job_type="PRE_MARKET_NIGHT_FORECAST",
            started_at=datetime.now().isoformat(),
            completed_at=datetime.now().isoformat(),
            status="FAILED",
            target_date=get_next_trading_day(),
            records_stored=0,
            log_summary=f"Job failed with error: {str(e)}"
        )


def execute_post_market_job():
    print(f"\n[{get_current_ist().strftime('%Y-%m-%d %H:%M:%S IST')}] 🔍 EXECUTING AUTOMATED POST-MARKET AUDIT...")
    try:
        run_postmarket_audit_cycle()
        sync_to_netlify()
    except Exception as e:
        print(f"[!] Error in post-market job: {e}")
        log_job_execution(
            job_type="POST_MARKET_AUDIT",
            started_at=datetime.now().isoformat(),
            completed_at=datetime.now().isoformat(),
            status="FAILED",
            target_date=datetime.now().strftime("%Y-%m-%d"),
            records_stored=0,
            log_summary=f"Job failed with error: {str(e)}"
        )


def start_scheduler_loop():
    print("""
╔═══════════════════════════════════════════════════════════════════════════════════╗
║          ⚡ AUTONOMOUS NIFTY 50 TRADING AGENT BACKGROUND SCHEDULER                ║
║    Pre-Market: 20:30 IST (Mon-Fri) • Post-Market: 15:45 IST (Mon-Fri)             ║
║    Auto-Database Storage & Automatic Netlify Cloud Sync Active                     ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
    """)
    init_db()
    
    last_pre_date = None
    last_post_date = None
    
    print("[*] Scheduler daemon initialized. Waiting for scheduled market triggers...")
    
    while True:
        now_ist = get_current_ist()
        today_str = now_ist.strftime("%Y-%m-%d")
        weekday = now_ist.weekday()  # 0 = Monday, 4 = Friday, 5 = Sat, 6 = Sun
        hour = now_ist.hour
        minute = now_ist.minute
        
        # Check weekdays only (Monday to Friday)
        if weekday < 5:
            # 1. Post-Market Close Audit trigger: 15:45 IST
            if (hour == 15 and minute >= 45) or (hour == 16 and minute < 30):
                if last_post_date != today_str:
                    execute_post_market_job()
                    last_post_date = today_str
                    
            # 2. Pre-Market Night Forecast trigger: 20:30 IST
            if (hour == 20 and minute >= 30) or (hour >= 21):
                if last_pre_date != today_str:
                    execute_pre_market_job()
                    last_pre_date = today_str
                    
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="Autonomous Nifty 50 Background Scheduler")
    parser.add_argument("--test-run", action="store_true", help="Execute both jobs immediately and sync to Netlify")
    args = parser.parse_args()
    
    if args.test_run:
        print("[*] Running immediate test sequence...")
        execute_pre_market_job()
        execute_post_market_job()
    else:
        start_scheduler_loop()


if __name__ == "__main__":
    main()
