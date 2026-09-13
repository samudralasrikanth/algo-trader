#!/usr/bin/env python3
# =============================================================================
# sync_all_to_supabase.py — Full SQLite to Supabase Migration & Verification
# =============================================================================

import os
import json
import sqlite3
import requests
from pathlib import Path
from datetime import datetime

ENV_PATH = Path(__file__).resolve().parent / ".env"
DB_PATH = Path(__file__).resolve().parent / "data" / "event_predictions.db"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

if ENV_PATH.exists():
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_URL="):
                SUPABASE_URL = line.split("=", 1)[1].strip()
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                SUPABASE_SERVICE_KEY = line.split("=", 1)[1].strip()


def get_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates"
    }


def check_table_exists(table_name: str) -> bool:
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table_name}?select=count&limit=1"
        res = requests.get(url, headers=get_headers(), timeout=5)
        return res.status_code in [200, 206]
    except Exception:
        return False


def migrate_all():
    print(f"[*] Checking Supabase tables at {SUPABASE_URL}...")
    
    tables = ["night_predictions", "daily_audits", "job_execution_logs", "news_archive"]
    status_map = {t: check_table_exists(t) for t in tables}
    
    for t, exists in status_map.items():
        print(f" - Table '{t}': {'✓ FOUND' if exists else '✗ NOT FOUND (Run SQL migration first)'}")
        
    if not any(status_map.values()):
        print("\n[!] IMPORTANT: The tables have not been created in Supabase yet.")
        print("[!] Please open your Supabase SQL Editor: https://supabase.com/dashboard/project/htcgeupzkxxxplqtvxue/sql/new")
        print("[!] Paste and run the contents of 'schema_supabase.sql' to create the tables.")
        return False
        
    if not DB_PATH.exists():
        print(f"[!] SQLite DB not found at {DB_PATH}")
        return False
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Migrate night_predictions
    if status_map["night_predictions"]:
        cursor.execute("SELECT * FROM night_predictions")
        rows = [dict(r) for r in cursor.fetchall()]
        print(f"\n[*] Migrating {len(rows)} night_predictions to Supabase...")
        payload = []
        for r in rows:
            try:
                active_cat = json.loads(r.get("active_catalysts_json") or "[]")
                prov = json.loads(r.get("provenance_json") or "{}")
            except Exception:
                active_cat = []
                prov = {}
            payload.append({
                "prediction_id": r.get("prediction_id"),
                "model_version": r.get("model_version", "2.1.0"),
                "data_cutoff": r.get("data_cutoff"),
                "snapshot_hash": r.get("snapshot_hash"),
                "symbol": r["symbol"],
                "short_name": r.get("short_name"),
                "sector": r.get("sector"),
                "target_trade_date": r["target_trade_date"],
                "base_price": float(r["base_price"]),
                "predicted_1d_target": float(r["predicted_1d_target"]),
                "predicted_1d_pct": float(r["predicted_1d_pct"]),
                "direction": r.get("direction", "NEUTRAL"),
                "action": r.get("action", "HOLD"),
                "conviction": int(r.get("conviction", 50)),
                "active_catalysts_json": active_cat,
                "provenance_json": prov
            })
        if payload:
            res = requests.post(f"{SUPABASE_URL}/rest/v1/night_predictions", headers=get_headers(), json=payload)
            print(f" -> Supabase night_predictions status: {res.status_code}")

    # 2. Migrate daily_audits
    if status_map["daily_audits"]:
        cursor.execute("SELECT * FROM daily_audits")
        rows = [dict(r) for r in cursor.fetchall()]
        print(f"\n[*] Migrating {len(rows)} daily_audits to Supabase...")
        payload = []
        for r in rows:
            try:
                factors_eval = json.loads(r.get("factors_evaluated_json") or "[]")
            except Exception:
                factors_eval = []
            payload.append({
                "night_pred_id": r.get("night_pred_id"),
                "trade_date": r["trade_date"],
                "symbol": r["symbol"],
                "short_name": r.get("short_name"),
                "sector": r.get("sector"),
                "base_price": float(r["base_price"]),
                "predicted_target": float(r["predicted_target"]),
                "predicted_change_pct": float(r["predicted_change_pct"]),
                "predicted_direction": r.get("predicted_direction", "NEUTRAL"),
                "actual_open": float(r["actual_open"]) if r.get("actual_open") else None,
                "actual_high": float(r["actual_high"]) if r.get("actual_high") else None,
                "actual_low": float(r["actual_low"]) if r.get("actual_low") else None,
                "actual_close": float(r["actual_close"]),
                "actual_change_pct": float(r["actual_change_pct"]),
                "actual_direction": r.get("actual_direction", "NEUTRAL"),
                "direction_correct": int(r.get("direction_correct", 0)),
                "hit_target_range": int(r.get("hit_target_range", 0)),
                "abs_error_pct": float(r.get("abs_error_pct", 0)),
                "simulated_pnl": float(r.get("simulated_pnl", 0)),
                "attribution_category": r.get("attribution_category", "MARKET_NOISE_DRIFT"),
                "diagnostic_explanation": r.get("diagnostic_explanation"),
                "refactoring_suggestion": r.get("refactoring_suggestion"),
                "factors_evaluated_json": factors_eval
            })
        if payload:
            res = requests.post(f"{SUPABASE_URL}/rest/v1/daily_audits", headers=get_headers(), json=payload)
            print(f" -> Supabase daily_audits status: {res.status_code}")

    # 3. Migrate job_execution_logs
    if status_map["job_execution_logs"]:
        cursor.execute("SELECT * FROM job_execution_logs")
        rows = [dict(r) for r in cursor.fetchall()]
        print(f"\n[*] Migrating {len(rows)} job_execution_logs to Supabase...")
        payload = []
        for r in rows:
            payload.append({
                "job_type": r["job_type"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "status": r["status"],
                "target_date": r["target_date"],
                "records_stored": int(r["records_stored"]),
                "log_summary": r.get("log_summary")
            })
        if payload:
            res = requests.post(f"{SUPABASE_URL}/rest/v1/job_execution_logs", headers=get_headers(), json=payload)
            print(f" -> Supabase job_execution_logs status: {res.status_code}")

    conn.close()
    print("\n[✓] Migration to Supabase finished!")
    return True


if __name__ == "__main__":
    migrate_all()
