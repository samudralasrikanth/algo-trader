#!/usr/bin/env python3
# =============================================================================
# event_agent/sentinel/runner.py — Event Sentinel CLI & Operational Harness
# =============================================================================
"""
V4.2.1 Event Sentinel CLI Runner:
Provides CLI command handlers for:
  --tick        : Executes a single sentinel monitoring pass
  --status      : Displays current operational health, active thesis, and coverage
  --fomc-sim    : Executes end-to-end golden FOMC simulation
  --shock-sim   : Executes news-independent flash market shock simulation
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from event_agent.sentinel.event_sentinel import EventSentinel
from event_agent.sentinel.models import TriggerVerdict
from event_agent.sentinel.thesis_state_manager import ThesisStateManager
from event_agent.storage.ledger import (
    get_latest_sentinel_invocation,
    get_latest_event_coverage_metric,
    get_current_active_thesis,
    get_thesis_revisions,
    get_recent_sentinel_events,
)
from event_agent.storage.supabase_ledger import get_latest_sentinel_telemetry_supabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel_runner")


def run_tick() -> None:
    """Executes a single continuous monitoring scan."""
    print("🚀 [Sentinel] Initiating Sentinel Tick...")
    sentinel = EventSentinel()
    record = sentinel.run_scan()
    print(f"✅ [Sentinel] Tick Completed.")
    print(f"   Scheduled ID: {record.scheduled_invocation_id}")
    print(f"   Sentinel ID:  {record.sentinel_invocation_id}")
    print(f"   Status:       {record.status}")
    print(f"   Events Seen:  {record.events_seen}")
    print(f"   Events New:   {record.events_new}")
    print(f"   Material:     {record.events_material}")
    print(f"   Triggered:    {record.events_triggered}")


def show_status() -> None:
    """Displays current system status, active thesis, and coverage metrics."""
    print("\n" + "=" * 60)
    print("🛡️  NEXUS V4.2.1 CONTINUOUS EVENT SENTINEL STATUS")
    print("=" * 60)

    # 1. Latest Invocation Telemetry (Local SQLite + Cloud Supabase)
    local_inv = get_latest_sentinel_invocation()
    cloud_inv = get_latest_sentinel_telemetry_supabase()

    print("\n[OPERATIONAL TELEMETRY]")
    if local_inv:
        print(f"  Local Last Scan:    {local_inv.get('completed_at', 'N/A')}")
        print(f"  Local Status:       {local_inv.get('status', 'UNKNOWN')}")
        print(f"  Scheduled Inv ID:   {local_inv.get('scheduled_invocation_id', 'N/A')}")
        print(f"  Sentinel Inv ID:    {local_inv.get('sentinel_invocation_id', 'N/A')}")
    else:
        print("  Local Last Scan:    No runs recorded")

    if cloud_inv:
        print(f"  Cloud Last Scan:    {cloud_inv.get('completed_at') or cloud_inv.get('started_at', 'N/A')}")
        print(f"  Cloud Status:       {cloud_inv.get('status', 'UNKNOWN')}")
        print(f"  Cloud Inv ID:       {cloud_inv.get('sentinel_invocation_id') or cloud_inv.get('invocation_id', 'N/A')}")
    else:
        print("  Cloud Persistence:  Connected (No remote invocation rows yet)")

    # 2. Active Thesis
    thesis = get_current_active_thesis()
    print("\n[ACTIVE NIFTY THESIS]")
    if thesis:
        print(f"  Thesis ID:          {thesis.get('thesis_id')}")
        print(f"  Revision:           v{thesis.get('revision')}")
        print(f"  Bias:               {thesis.get('bias')}")
        print(f"  Confidence:         {thesis.get('confidence')}%")
        print(f"  Expected Move:      {thesis.get('expected_move')}%")
        print(f"  Regime:             {thesis.get('volatility_regime')}")
        print(f"  Status:             {thesis.get('status')}")
        print(f"  Valid Until:        {thesis.get('valid_until')}")
        revs = get_thesis_revisions(thesis.get('thesis_id'))
        print(f"  Total Revisions:    {len(revs)}")
    else:
        print("  Active Thesis:      None initialized")

    # 3. Event Coverage Metrics (3 Distinct Denominators)
    cov = get_latest_event_coverage_metric()
    print("\n[EVENT COVERAGE METRICS (RIGOROUS DENOMINATORS)]")
    if cov:
        print(f"  Scheduled Event Coverage:   {cov.get('scheduled_coverage_pct', 0):.1f}% ({cov.get('scheduled_detected', 0)}/{cov.get('scheduled_expected', 0)})")
        print(f"  Source Ingestion Coverage:  {cov.get('source_coverage_pct', 0):.1f}% ({cov.get('source_processed', 0)}/{cov.get('source_available', 0)})")
        print(f"  Material Event Processing:  {cov.get('material_processing_pct', 0):.1f}% ({cov.get('material_processed', 0)}/{cov.get('material_detected', 0)})")
    else:
        print("  Coverage Metrics:   No data recorded")

    print("=" * 60 + "\n")


def simulate_fomc() -> None:
    """Simulates the September 16, 2026 FOMC +25 bps event end-to-end."""
    print("🧪 [Simulation] Executing Golden FOMC Test (September 16, 2026 Fed +25 bps)...")
    sentinel = EventSentinel()

    sim_time = datetime(2026, 9, 16, 18, 5, 0, tzinfo=timezone.utc)
    market_quotes = {
        "NIFTY_PRICE": 25150.0,
        "INDIA_VIX": 13.80,
        "india_vix_change_pct": 14.5,
        "us_10y_yield": 4.15,
        "dxy_index": 103.85,
        "us_futures_change_pct": -0.85,
        "gold_price": 2580.0,
        "usdinr_price": 84.10,
    }

    raw_news = [
        {
            "title": "Federal Reserve raises interest rates by 25 bps to 4.00%",
            "description": "FOMC voted to increase benchmark interest rate by 25 bps following persistent inflation pressures.",
            "source": "REUTERS_MACRO",
            "timestamp": sim_time.isoformat(),
        }
    ]

    record = sentinel.run_scan(
        scheduled_invocation_id="GOLDEN_FOMC_SIM_20260916",
        market_quotes=market_quotes,
        incoming_news=raw_news,
        current_time=sim_time,
    )

    print(f"✅ Simulation finished with status: {record.status}")
    print(f"   Events processed: {record.events_seen}, Material: {record.events_material}, Triggered: {record.events_triggered}")


def simulate_shock() -> None:
    """Simulates a fast market shock with NEWS = NONE."""
    print("🧪 [Simulation] Executing Flash Market Shock with NEWS = NONE...")
    sentinel = EventSentinel()

    shock_quotes = {
        "NIFTY_PRICE": 24400.0,
        "nifty_10m_change_pct": -2.85,
        "INDIA_VIX": 18.50,
        "india_vix_change_pct": 38.0,
        "us_futures_change_pct": -2.40,
        "usdinr_price": 85.20,
    }

    record = sentinel.run_scan(
        scheduled_invocation_id="FLASH_SHOCK_SIM",
        market_quotes=shock_quotes,
        incoming_news=[],  # Zero news
    )
    print(f"✅ Flash shock simulation finished: Triggered={record.events_triggered}, Material={record.events_material}")


def main():
    parser = argparse.ArgumentParser(description="NEXUS V4.2.1 Event Sentinel Harness")
    parser.add_argument("--tick", action="store_true", help="Execute single continuous scan pass")
    parser.add_argument("--status", action="store_true", help="Print operational status and active thesis")
    parser.add_argument("--fomc-sim", action="store_true", help="Run September 16, 2026 FOMC test")
    parser.add_argument("--shock-sim", action="store_true", help="Run independent flash market shock test")

    args = parser.parse_args()

    if args.tick:
        run_tick()
    elif args.status:
        show_status()
    elif getattr(args, "fomc_sim", False):
        simulate_fomc()
    elif getattr(args, "shock_sim", False):
        simulate_shock()
    else:
        show_status()


if __name__ == "__main__":
    main()
