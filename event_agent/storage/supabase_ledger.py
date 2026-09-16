#!/usr/bin/env python3
# =============================================================================
# event_agent/storage/supabase_ledger.py — Supabase Cloud Database Client
# =============================================================================

import os
import json
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

# Load credentials strictly from environment variables or local .env file
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

if ENV_PATH.exists():
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_URL=") and not SUPABASE_URL:
                SUPABASE_URL = line.split("=", 1)[1].strip()
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY=") and not SUPABASE_SERVICE_KEY:
                SUPABASE_SERVICE_KEY = line.split("=", 1)[1].strip()
            elif line.startswith("SUPABASE_ANON_KEY=") and not SUPABASE_ANON_KEY:
                SUPABASE_ANON_KEY = line.split("=", 1)[1].strip()

# Reject unconfigured generic placeholders
if "your-project-ref" in SUPABASE_URL or "placeholder" in SUPABASE_URL.lower():
    SUPABASE_URL = ""
if "your-service-role-key" in SUPABASE_SERVICE_KEY:
    SUPABASE_SERVICE_KEY = ""


def get_headers(use_service_role: bool = True) -> Dict[str, str]:
    key = SUPABASE_SERVICE_KEY if use_service_role else SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates"
    }


def is_supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


# -----------------------------------------------------------------------------
# Pre-Market Night Predictions
# -----------------------------------------------------------------------------
def save_night_prediction_supabase(pred: Dict[str, Any], target_trade_date: str) -> bool:
    if not is_supabase_configured():
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/night_predictions"
        payload = {
            "prediction_id": pred.get("prediction_id"),
            "model_version": pred.get("model_version", "2.1.0"),
            "data_cutoff": pred.get("data_cutoff"),
            "snapshot_hash": pred.get("snapshot_hash"),
            "symbol": pred["symbol"],
            "short_name": pred.get("short_name"),
            "sector": pred.get("sector"),
            "target_trade_date": target_trade_date,
            "base_price": float(pred["base_price"]),
            "predicted_1d_target": float(pred.get("predicted_1d_target", pred.get("target_1d", 0))),
            "predicted_1d_pct": float(pred.get("predicted_1d_pct", pred.get("expected_1d_pct", 0))),
            "direction": pred.get("direction", "NEUTRAL"),
            "action": pred.get("action", "HOLD"),
            "conviction": int(pred.get("conviction", 50)),
            "active_catalysts_json": pred.get("active_catalysts", []),
            "factors_json": pred.get("factors_evaluated", {}),
            "provenance_json": pred.get("provenance", {})
        }
        res = requests.post(url, headers=get_headers(True), json=payload, timeout=10)
        return res.status_code in [200, 201]
    except Exception as e:
        print(f"[!] Supabase save_night_prediction error: {e}")
        return False


def get_night_predictions_supabase(target_date: Optional[str] = None) -> List[Dict[str, Any]]:
    if not is_supabase_configured():
        return []
    try:
        url = f"{SUPABASE_URL}/rest/v1/night_predictions?select=*"
        if target_date:
            url += f"&target_trade_date=eq.{target_date}"
        url += "&order=target_trade_date.desc,created_at.desc"
        res = requests.get(url, headers=get_headers(False), timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[!] Supabase get_night_predictions error: {e}")
    return []


# -----------------------------------------------------------------------------
# Post-Market Daily Audits
# -----------------------------------------------------------------------------
def save_daily_audit_supabase(audit: Dict[str, Any]) -> bool:
    if not is_supabase_configured():
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/daily_audits"
        payload = {
            "night_pred_id": audit.get("night_pred_id"),
            "trade_date": audit["trade_date"],
            "symbol": audit["symbol"],
            "short_name": audit.get("short_name"),
            "sector": audit.get("sector"),
            "base_price": float(audit["base_price"]),
            "predicted_target": float(audit["predicted_target"]),
            "predicted_change_pct": float(audit["predicted_change_pct"]),
            "predicted_direction": audit.get("predicted_direction", "NEUTRAL"),
            "actual_open": float(audit["actual_open"]) if audit.get("actual_open") else None,
            "actual_high": float(audit["actual_high"]) if audit.get("actual_high") else None,
            "actual_low": float(audit["actual_low"]) if audit.get("actual_low") else None,
            "actual_close": float(audit["actual_close"]),
            "actual_change_pct": float(audit["actual_change_pct"]),
            "actual_direction": audit.get("actual_direction", "NEUTRAL"),
            "direction_correct": int(audit.get("direction_correct", 0)),
            "hit_target_range": int(audit.get("hit_target_range", 0)),
            "abs_error_pct": float(audit.get("abs_error_pct", 0)),
            "simulated_pnl": float(audit.get("simulated_pnl", 0)),
            "attribution_category": audit.get("attribution_category", "MARKET_NOISE_DRIFT"),
            "diagnostic_explanation": audit.get("diagnostic_explanation"),
            "refactoring_suggestion": audit.get("refactoring_suggestion"),
            "factors_evaluated_json": audit.get("factors_active", [])
        }
        res = requests.post(url, headers=get_headers(True), json=payload, timeout=10)
        return res.status_code in [200, 201]
    except Exception as e:
        print(f"[!] Supabase save_daily_audit error: {e}")
        return False


def get_daily_audits_supabase(start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if not is_supabase_configured():
        return []
    try:
        url = f"{SUPABASE_URL}/rest/v1/daily_audits?select=*&order=trade_date.desc&limit={limit}"
        if start_date:
            url += f"&trade_date=gte.{start_date}"
        if end_date:
            url += f"&trade_date=lte.{end_date}"
        res = requests.get(url, headers=get_headers(False), timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[!] Supabase get_daily_audits error: {e}")
    return []


# -----------------------------------------------------------------------------
# Automated Job Execution Logs
# -----------------------------------------------------------------------------
def log_job_execution_supabase(
    job_type: str,
    started_at: str,
    completed_at: str,
    status: str,
    target_date: str,
    records_stored: int,
    log_summary: str
) -> bool:
    if not is_supabase_configured():
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/job_execution_logs"
        payload = {
            "job_type": job_type,
            "started_at": started_at,
            "completed_at": completed_at,
            "status": status,
            "target_date": target_date,
            "records_stored": records_stored,
            "log_summary": log_summary
        }
        res = requests.post(url, headers=get_headers(True), json=payload, timeout=10)
        return res.status_code in [200, 201]
    except Exception as e:
        print(f"[!] Supabase log_job_execution error: {e}")
        return False


def get_job_logs_supabase(limit: int = 50) -> List[Dict[str, Any]]:
    if not is_supabase_configured():
        return []
    try:
        url = f"{SUPABASE_URL}/rest/v1/job_execution_logs?select=*&order=started_at.desc&limit={limit}"
        res = requests.get(url, headers=get_headers(False), timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[!] Supabase get_job_logs error: {e}")
    return []


# -----------------------------------------------------------------------------
# Prediction Snapshots (Point-in-Time Frozen Inputs + Baselines)
# -----------------------------------------------------------------------------
def save_prediction_snapshot_supabase(snapshot: Dict[str, Any]) -> bool:
    if not is_supabase_configured():
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/prediction_snapshots"
        payload = {
            "prediction_id": snapshot.get("prediction_id"),
            "model_version": snapshot.get("model_version", "3.0.0"),
            "feature_version": snapshot.get("feature_version", "F1"),
            "regime_version": snapshot.get("regime_version", "R1"),
            "calibration_version": snapshot.get("calibration_version", "C1"),
            "weights_version": snapshot.get("weights_version", "W1.0"),
            "data_snapshot_id": snapshot.get("data_snapshot_id"),
            "market_state_json": snapshot.get("market_state_json", {}),
            "regime_json": snapshot.get("regime_json", {}),
            "features_json": snapshot.get("features_json", {}),
            "surprises_json": snapshot.get("surprises_json", []),
            "news_articles_json": snapshot.get("news_articles_json", []),
            "events_json": snapshot.get("events_json", []),
            "factor_weights_json": snapshot.get("factor_weights_json", {}),
            "prediction_json": snapshot.get("prediction_json", {}),
            "baselines_json": snapshot.get("baselines_json", {}),
            "snapshot_hash": snapshot.get("snapshot_hash"),
            "locked_at": snapshot.get("locked_at"),
        }
        res = requests.post(url, headers=get_headers(True), json=payload, timeout=10)
        return res.status_code in [200, 201]
    except Exception as e:
        return False
