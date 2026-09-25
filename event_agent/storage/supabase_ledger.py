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
    # This module is server-side only. Cloud workers must use the service-role
    # credential for both reads and writes: a stale or missing anon key on an
    # ephemeral GitHub runner must never make an authoritative forecast appear
    # absent. The service-role key is never returned to the browser.
    key = SUPABASE_SERVICE_KEY if use_service_role else (SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY)
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
        res = requests.get(url, headers=get_headers(True), timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[!] Supabase get_night_predictions error: {e}")
    return []


# -----------------------------------------------------------------------------
# Ephemeral worker state
# -----------------------------------------------------------------------------
def save_arena_state_supabase(state: Dict[str, Any]) -> bool:
    """Persist the paper arena snapshot in the existing job ledger.

    GitHub Actions runners are disposable and the SQLite file is deliberately
    ignored by git.  Keeping the latest arena snapshot in Supabase makes the
    next five-minute cycle idempotent and prevents every fresh runner from
    starting with a blank portfolio.
    """
    if not is_supabase_configured():
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/job_execution_logs"
        payload = {
            "job_type": "ARENA_STATE_SNAPSHOT",
            "started_at": state.get("as_of") or datetime.utcnow().isoformat() + "Z",
            "completed_at": state.get("as_of") or datetime.utcnow().isoformat() + "Z",
            "status": "SUCCESS",
            "target_date": state.get("market_date") or datetime.utcnow().strftime("%Y-%m-%d"),
            "records_stored": int(state.get("open_positions_count", 0)),
            "log_summary": json.dumps(state, separators=(",", ":")),
        }
        res = requests.post(url, headers=get_headers(True), json=payload, timeout=15)
        return res.status_code in [200, 201]
    except Exception as exc:
        print(f"[!] Supabase save_arena_state error: {exc}")
        return False


def get_latest_arena_state_supabase() -> Optional[Dict[str, Any]]:
    """Load the latest paper arena snapshot for an ephemeral worker."""
    if not is_supabase_configured():
        return None
    try:
        url = (
            f"{SUPABASE_URL}/rest/v1/job_execution_logs"
            "?job_type=eq.ARENA_STATE_SNAPSHOT&status=eq.SUCCESS"
            "&select=log_summary&order=completed_at.desc&limit=1"
        )
        res = requests.get(url, headers=get_headers(True), timeout=15)
        if res.status_code == 200 and res.json():
            raw = res.json()[0].get("log_summary")
            return json.loads(raw) if raw else None
    except Exception as exc:
        print(f"[!] Supabase get_arena_state error: {exc}")
    return None


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
        res = requests.get(url, headers=get_headers(True), timeout=10)
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
        res = requests.get(url, headers=get_headers(True), timeout=10)
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


# -----------------------------------------------------------------------------
# Event Sentinel Cloud Sync (Authoritative Production Ledger)
# -----------------------------------------------------------------------------

def save_sentinel_invocation_supabase(inv: Dict[str, Any]) -> bool:
    """
    Persist cloud sentinel invocation telemetry and full lineage to Supabase.
    Primary target: public.sentinel_invocations
    Authoritative fallback: public.scheduler_invocations (trigger_source='NETLIFY_SENTINEL')
    """
    if not is_supabase_configured():
        return False

    # 1. Attempt dedicated sentinel_invocations table
    try:
        url = f"{SUPABASE_URL}/rest/v1/sentinel_invocations"
        res = requests.post(url, headers=get_headers(True), json=inv, timeout=10)
        if res.status_code in [200, 201]:
            return True
    except Exception:
        pass

    # 2. Authoritative Fallback: persist to existing scheduler_invocations
    try:
        url_sched = f"{SUPABASE_URL}/rest/v1/scheduler_invocations"
        now_iso = datetime.utcnow().isoformat() + "Z"
        lineage_payload = {
            "scheduled_invocation_id": inv.get("scheduled_invocation_id"),
            "sentinel_invocation_id": inv.get("sentinel_invocation_id"),
            "sources_checked": inv.get("sources_checked", 8),
            "events_seen": inv.get("events_seen", 0),
            "events_new": inv.get("events_new", 0),
            "events_duplicate": inv.get("events_duplicate", 0),
            "events_material": inv.get("events_material", 0),
            "events_triggered": inv.get("events_triggered", 0),
            "lineage": inv.get("lineage", {}),
        }
        fallback_record = {
            "invocation_id": inv.get("sentinel_invocation_id") or f"SENT-{int(datetime.utcnow().timestamp())}",
            "scheduled_for": inv.get("started_at") or now_iso,
            "started_at": inv.get("started_at") or now_iso,
            "completed_at": inv.get("completed_at") or now_iso,
            "status": inv.get("status", "SUCCESS"),
            "trigger_source": "NETLIFY_SENTINEL",
            "environment": "PAPER",
            "workflow_run_id": inv.get("scheduled_invocation_id"),
            "job_run_id": json.dumps(lineage_payload),
            "error_message": inv.get("error"),
        }
        res_sched = requests.post(url_sched, headers=get_headers(True), json=fallback_record, timeout=10)
        return res_sched.status_code in [200, 201]
    except Exception as e:
        print(f"[!] Supabase save_sentinel_invocation error: {e}")
        return False


def save_sentinel_event_supabase(event: Dict[str, Any]) -> bool:
    """
    Persist classified event to Supabase authoritative event_ledger.
    Fallback: news_archive table.
    """
    if not is_supabase_configured():
        return False

    # 1. Attempt event_ledger
    try:
        url = f"{SUPABASE_URL}/rest/v1/event_ledger"
        res = requests.post(url, headers=get_headers(True), json=event, timeout=10)
        if res.status_code in [200, 201]:
            return True
    except Exception:
        pass

    # 2. Fallback: news_archive
    try:
        url_news = f"{SUPABASE_URL}/rest/v1/news_archive"
        pub_date = event.get("timestamp") or datetime.utcnow().isoformat() + "Z"
        evt_id = event.get("event_id", "EV-UNKNOWN")
        archive_payload = {
            "title": f"[{event.get('category', 'MACRO')}] {event.get('title', '')}"[:255],
            "source": f"SENTINEL_{event.get('source', 'FEED')}"[:50],
            "pub_date": pub_date,
            "symbol": "NIFTY",
            "score": float(event.get("importance_score", 50.0)),
            "polarity": "BEARISH" if "bear" in str(event.get("thesis_relation", "")).lower() else "NEUTRAL",
            "url": f"sentinel://event/{evt_id}",
        }
        res_news = requests.post(url_news, headers=get_headers(True), json=archive_payload, timeout=10)
        return res_news.status_code in [200, 201]
    except Exception as e:
        print(f"[!] Supabase save_sentinel_event error: {e}")
        return False


def save_active_thesis_supabase(thesis: Dict[str, Any]) -> bool:
    """
    Persist active NIFTY thesis state to Supabase.
    Fallback: job_execution_logs table.
    """
    if not is_supabase_configured():
        return False

    # 1. Attempt active_theses table
    try:
        url = f"{SUPABASE_URL}/rest/v1/active_theses"
        res = requests.post(url, headers=get_headers(True), json=thesis, timeout=10)
        if res.status_code in [200, 201]:
            return True
    except Exception:
        pass

    # 2. Fallback: job_execution_logs
    try:
        url_jobs = f"{SUPABASE_URL}/rest/v1/job_execution_logs"
        now_iso = datetime.utcnow().isoformat() + "Z"
        today_date = datetime.utcnow().strftime("%Y-%m-%d")
        job_record = {
            "job_type": "ACTIVE_THESIS_UPDATE",
            "started_at": thesis.get("created_at") or now_iso,
            "completed_at": now_iso,
            "status": thesis.get("status", "ACTIVE"),
            "target_date": today_date,
            "records_stored": int(thesis.get("revision", 1)),
            "log_summary": json.dumps(thesis),
        }
        res_jobs = requests.post(url_jobs, headers=get_headers(True), json=job_record, timeout=10)
        return res_jobs.status_code in [200, 201]
    except Exception as e:
        print(f"[!] Supabase save_active_thesis error: {e}")
        return False


def save_thesis_revision_supabase(rev: Dict[str, Any]) -> bool:
    """
    Persist deterministic thesis revision to Supabase.
    Fallback: job_execution_logs table.
    """
    if not is_supabase_configured():
        return False

    # 1. Attempt thesis_revisions table
    try:
        url = f"{SUPABASE_URL}/rest/v1/thesis_revisions"
        res = requests.post(url, headers=get_headers(True), json=rev, timeout=10)
        if res.status_code in [200, 201]:
            return True
    except Exception:
        pass

    # 2. Fallback: job_execution_logs
    try:
        url_jobs = f"{SUPABASE_URL}/rest/v1/job_execution_logs"
        now_iso = datetime.utcnow().isoformat() + "Z"
        today_date = datetime.utcnow().strftime("%Y-%m-%d")
        job_record = {
            "job_type": "THESIS_REVISION",
            "started_at": rev.get("created_at") or now_iso,
            "completed_at": now_iso,
            "status": "APPLIED",
            "target_date": today_date,
            "records_stored": int(rev.get("revision", 1)),
            "log_summary": json.dumps(rev),
        }
        res_jobs = requests.post(url_jobs, headers=get_headers(True), json=job_record, timeout=10)
        return res_jobs.status_code in [200, 201]
    except Exception as e:
        print(f"[!] Supabase save_thesis_revision error: {e}")
        return False


def get_latest_sentinel_telemetry_supabase() -> Optional[Dict[str, Any]]:
    """
    Retrieve the latest sentinel invocation telemetry from Supabase.
    Checks sentinel_invocations first, falls back to scheduler_invocations.
    """
    if not is_supabase_configured():
        return None

    # 1. Try dedicated table
    try:
        url = f"{SUPABASE_URL}/rest/v1/sentinel_invocations?select=*&order=completed_at.desc&limit=1"
        res = requests.get(url, headers=get_headers(True), timeout=10)
        if res.status_code == 200 and res.json():
            return res.json()[0]
    except Exception:
        pass

    # 2. Try scheduler_invocations with trigger_source = NETLIFY_SENTINEL
    try:
        url_sched = f"{SUPABASE_URL}/rest/v1/scheduler_invocations?trigger_source=eq.NETLIFY_SENTINEL&order=started_at.desc&limit=1"
        res_sched = requests.get(url_sched, headers=get_headers(True), timeout=10)
        if res_sched.status_code == 200 and res_sched.json():
            row = res_sched.json()[0]
            # Parse payload from job_run_id if present
            payload = {}
            if row.get("job_run_id"):
                try:
                    payload = json.loads(row["job_run_id"])
                except Exception:
                    pass

            return {
                "scheduled_invocation_id": row.get("workflow_run_id") or payload.get("scheduled_invocation_id"),
                "sentinel_invocation_id": row.get("invocation_id"),
                "started_at": row.get("started_at"),
                "completed_at": row.get("completed_at"),
                "sources_checked": payload.get("sources_checked", 8),
                "events_seen": payload.get("events_seen", 0),
                "events_new": payload.get("events_new", 0),
                "events_duplicate": payload.get("events_duplicate", 0),
                "events_material": payload.get("events_material", 0),
                "events_triggered": payload.get("events_triggered", 0),
                "status": row.get("status", "SUCCESS"),
                "error": row.get("error_message"),
                "lineage": payload.get("lineage", {}),
            }
    except Exception as e:
        print(f"[!] Supabase get_latest_sentinel_telemetry error: {e}")

    return None
