#!/usr/bin/env python3
"""Run one guarded paper-trading decision cycle during NSE market hours.

This is the execution entry point used by the five-minute cloud trigger.  It
never uses ``force_execute``: outside 09:15–15:30 IST the market clock blocks
the cycle instead of creating an off-hours fill.
"""

import argparse
import copy
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from event_agent.arena.market_clock import MarketClock
from event_agent.arena.orchestrator import ArenaOrchestrator
from event_agent.engine.live_market_feed import fetch_live_quotes
from event_agent.storage.ledger import get_active_night_predictions, log_job_execution


def _target_date(now: datetime) -> str:
    return MarketClock.get_ist_time(now).strftime("%Y-%m-%d")


def _refresh_locked_predictions(predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Use current quotes for execution while retaining the locked forecast edge."""
    result = [copy.deepcopy(p) for p in predictions]
    symbols = [p.get("symbol") for p in result if p.get("symbol")]
    quotes = fetch_live_quotes(symbols)
    for pred in result:
        quote = quotes.get(pred.get("symbol"))
        if not quote or quote.get("price", 0) <= 0:
            continue
        price = float(quote["price"])
        expected = float(pred.get("expected_1d_pct", pred.get("predicted_1d_pct", 0.0)) or 0.0)
        direction = str(pred.get("direction", "NEUTRAL")).upper()
        move = abs(expected)
        pred["base_price"] = price
        if direction in ("BEARISH", "SELL") or expected < 0:
            pred["target_price"] = round(price * (1.0 - move / 100.0), 2)
            pred["stop_loss"] = round(price * (1.0 + max(move * 0.5, 0.5) / 100.0), 2)
        elif direction in ("BULLISH", "BUY") or expected > 0:
            pred["target_price"] = round(price * (1.0 + move / 100.0), 2)
            pred["stop_loss"] = round(price * (1.0 - max(move * 0.5, 0.5) / 100.0), 2)
    return result


def run_cycle(simulated_time: Optional[datetime] = None) -> Dict[str, Any]:
    now = simulated_time or datetime.now(timezone.utc)
    clock = MarketClock.get_status(now)
    if not MarketClock.is_market_open(now):
        return {
            "status": "SKIPPED_OUTSIDE_MARKET_HOURS",
            "market_clock": clock,
            "executed_trades_count": 0,
        }

    trade_date = _target_date(now)
    predictions = get_active_night_predictions(target_trade_date=trade_date)
    if not predictions:
        return {
            "status": "SKIPPED_NO_LOCKED_FORECAST",
            "market_date": trade_date,
            "market_clock": clock,
            "executed_trades_count": 0,
            "reason": f"No locked night predictions found for {trade_date}.",
        }

    orchestrator = ArenaOrchestrator()
    result = orchestrator.run_cycle(
        market_date=trade_date,
        predictions=_refresh_locked_predictions(predictions),
        simulated_time=now,
        force_execute=False,
        execute_trades=True,
    )
    result["status"] = "SUCCESS"
    result["triggered_at"] = now.isoformat()
    log_job_execution(
        job_type="INTRADAY_ARENA_CYCLE",
        started_at=now.isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        status="SUCCESS",
        target_date=trade_date,
        records_stored=int(result.get("executed_trades_count", 0)),
        log_summary=(
            f"Guarded intraday paper cycle: {result.get('executed_trades_count', 0)} fills; "
            f"{len(result.get('decisions', []))} decisions evaluated."
        ),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--at", dest="simulated_time", help="UTC ISO timestamp for deterministic tests")
    args = parser.parse_args()
    simulated = datetime.fromisoformat(args.simulated_time.replace("Z", "+00:00")) if args.simulated_time else None
    result = run_cycle(simulated)
    print(json.dumps({
        "status": result.get("status"),
        "market_date": result.get("market_date"),
        "market_clock": result.get("market_clock"),
        "executed_trades_count": result.get("executed_trades_count", 0),
        "executed_trades": result.get("executed_trades", []),
        "reason": result.get("reason"),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
