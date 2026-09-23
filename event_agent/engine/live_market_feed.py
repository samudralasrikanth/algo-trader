# =============================================================================
# event_agent/engine/live_market_feed.py — Real-Time Market Feed & Revaluation
# =============================================================================
"""
Real-time market price fetcher and position revaluation engine.
Fetches live NSE quotes via yfinance fast_info and updates SQLite agent_positions
with up-to-the-second market rates, unrealized P&L, and market values for video streaming and UI.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import yfinance as yf

try:
    from ..storage.ledger import (
        get_agent_positions,
        update_agent_position_prices,
        get_connection,
    )
except (ImportError, ValueError):
    from event_agent.storage.ledger import (
        get_agent_positions,
        update_agent_position_prices,
        get_connection,
    )

logger = logging.getLogger(__name__)


def fetch_live_quotes(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch live market prices and previous close for a list of NSE ticker symbols.
    Returns: { symbol: { 'price': float, 'prev_close': float, 'change': float, 'change_pct': float } }
    """
    if not symbols:
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    clean_symbols = list({s.strip() for s in symbols if s.strip()})

    try:
        tickers = yf.Tickers(" ".join(clean_symbols))
        for sym in clean_symbols:
            try:
                t = tickers.tickers.get(sym)
                if not t:
                    continue
                fi = getattr(t, "fast_info", None)
                if fi:
                    price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
                    prev = getattr(fi, "previous_close", None) or price
                else:
                    info = getattr(t, "info", {})
                    price = info.get("regularMarketPrice") or info.get("currentPrice")
                    prev = info.get("previousClose") or price

                if price and float(price) > 0:
                    p = round(float(price), 2)
                    pr = round(float(prev), 2) if prev else p
                    chg = round(p - pr, 2)
                    chg_pct = round((chg / pr * 100.0), 2) if pr > 0 else 0.0
                    results[sym] = {
                        "price": p,
                        "previous_close": pr,
                        "change": chg,
                        "change_pct": chg_pct,
                        "is_positive": chg >= 0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
            except Exception as e:
                logger.debug(f"Failed to extract live quote for {sym}: {e}")
    except Exception as exc:
        logger.warning(f"Batch live quote fetch error: {exc}")

    return results


def revalue_all_positions_live() -> Dict[str, Any]:
    """
    Fetches live market rates for all open positions in SQLite and updates:
    - current_price
    - market_value
    - unrealized_pnl
    - unrealized_pnl_pct

    Returns a summary dictionary suitable for video streaming scripts, web exports, and reporting.
    """
    positions = get_agent_positions(status="OPEN")
    if not positions:
        return {
            "status": "NO_OPEN_POSITIONS",
            "active_positions_count": 0,
            "total_unrealized_pnl": 0.0,
            "total_market_value": 0.0,
            "quotes": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    symbols = list({p["symbol"] for p in positions if p.get("symbol")})
    quotes = fetch_live_quotes(symbols)

    price_map = {sym: data["price"] for sym, data in quotes.items()}
    updated_count = update_agent_position_prices(price_map)

    # Re-fetch updated positions to aggregate metrics
    refreshed_positions = get_agent_positions(status="OPEN")

    # Dedicated Dual Exit Engine evaluation with 9-level priority hierarchy
    exits_triggered = 0
    try:
        from event_agent.arena.exit_engine import ExitEngine
        from event_agent.storage.ledger import close_agent_position
        exit_signals = ExitEngine.evaluate_all(refreshed_positions, quotes)
        for sig in exit_signals:
            if sig.should_exit:
                pos_target = next((p for p in refreshed_positions if p.get("position_id") == sig.position_id), None)
                brokerage = 40.0 if pos_target and "OPTION" in str(pos_target.get("instrument_type", "")) else 20.0
                close_agent_position(
                    position_id=sig.position_id,
                    exit_price=sig.suggested_exit_price,
                    exit_reason=sig.exit_reason,
                    brokerage_costs=brokerage,
                )
                exits_triggered += 1
                logger.info(f"ExitEngine closed {sig.symbol} ({sig.position_id}): {sig.exit_reason} at ₹{sig.suggested_exit_price:.2f} (Priority {sig.priority_name})")

        if exits_triggered > 0:
            refreshed_positions = get_agent_positions(status="OPEN")
    except Exception as exit_err:
        logger.warning(f"Exit evaluation warning: {exit_err}")

    total_unrealized_pnl = sum(float(p.get("unrealized_pnl", 0.0)) for p in refreshed_positions)
    total_market_value = sum(float(p.get("market_value", 0.0)) for p in refreshed_positions)
    total_cost_basis = sum(float(p.get("cost_basis", 0.0)) for p in refreshed_positions)
    overall_pnl_pct = (total_unrealized_pnl / total_cost_basis * 100.0) if total_cost_basis > 0 else 0.0

    return {
        "status": "SUCCESS",
        "updated_positions_count": updated_count,
        "active_positions_count": len(refreshed_positions),
        "exits_triggered": exits_triggered,
        "total_cost_basis": round(total_cost_basis, 2),
        "total_market_value": round(total_market_value, 2),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "overall_pnl_pct": round(overall_pnl_pct, 2),
        "quotes": quotes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing live market feed revaluation...")
    res = revalue_all_positions_live()
    print(f"Status: {res['status']}")
    print(f"Updated: {res['updated_positions_count']} positions")
    print(f"Cost Basis: ₹{res['total_cost_basis']:,.2f}")
    print(f"Market Value: ₹{res['total_market_value']:,.2f}")
    print(f"Unrealized P&L: ₹{res['total_unrealized_pnl']:+,.2f} ({res['overall_pnl_pct']:+.2f}%)")
    for sym, q in res["quotes"].items():
        print(f"  {sym}: ₹{q['price']} ({q['change_pct']:+.2f}%)")
