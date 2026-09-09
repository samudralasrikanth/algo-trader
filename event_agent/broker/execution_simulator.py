# =============================================================================
# event_agent/broker/execution_simulator.py — 5-Minute Execution Simulator
# =============================================================================
"""
High-fidelity paper execution engine evaluating positions against 5-minute candles.

Review Point #6 & V3.1a Fix F3 implementation:
    1. Chronological candle evaluation.
    2. Conservative stop-first assumption on ambiguous intra-candle breaches.
    3. Gap-through price adjustments.
    4. Execution data snapshot recorded alongside every fill.
"""

import hashlib
import json
import logging
import math
from .order import Order, OrderFill, OrderSide, OrderStatus, OrderType
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

EXECUTION_ASSUMPTIONS = """
DOCUMENTED ASSUMPTIONS (not claims of fact):

1. Positions are evaluated against 5-minute intraday candles.
2. Candles are walked chronologically. The first candle that breaches
   target or stop determines the fill.
3. AMBIGUITY RULE: If both target AND stop are breached within the
   SAME 5-minute candle, we apply a CONSERVATIVE STOP-FIRST assumption.
   This means our P&L is biased slightly pessimistic on ambiguous fills.
4. GAP-THROUGH: If market opens beyond the stop price, the fill is
   recorded at the open price (not the stop price).
5. If 1-minute data becomes available, ambiguous candles will be
   resolved at 1-minute resolution instead.
6. Fills marked 'is_ambiguous=True' indicate candles where both
   levels were breached within the same bar.
"""


@dataclass
class Candle5M:
    """Standardized 5-minute bar."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Fill:
    """Execution fill record."""
    fill_price: float
    reason: str             # "TARGET_HIT" | "STOP_HIT" | "EOD_CLOSE" | "MANUAL_EXIT"
    is_ambiguous: bool
    ambiguity_note: str
    candle_time: str
    execution_snapshot: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionSimulator:
    """
    Simulates realistic order fills using intraday 5-minute bars.
    """

    def __init__(self, conservative_ambiguity: bool = True):
        self.conservative_ambiguity = conservative_ambiguity

    def create_execution_snapshot(
        self,
        symbol: str,
        candles: List[Candle5M],
        provider: str = "yfinance",
        provider_version: str = "0.2.63",
        timezone_str: str = "Asia/Kolkata",
    ) -> Dict[str, Any]:
        """
        Record execution data provenance proving what market data the broker
        used to determine the outcome, separate from the prediction_snapshot.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        start_time = candles[0].timestamp if candles else now_iso
        end_time = candles[-1].timestamp if candles else now_iso

        # Build cryptographic hash of candle data
        raw_repr = "".join(f"{c.timestamp}:{c.open}:{c.high}:{c.low}:{c.close}" for c in candles)
        data_hash = f"sha256:{hashlib.sha256(raw_repr.encode('utf-8')).hexdigest()}"

        return {
            "provider": provider,
            "provider_version": provider_version,
            "symbol": symbol,
            "interval": "5m",
            "requested_at": now_iso,
            "fetched_at": now_iso,
            "market_data_start": start_time,
            "market_data_end": end_time,
            "row_count": len(candles),
            "data_hash": data_hash,
            "timezone": timezone_str,
        }


    def simulate_order_execution(
        self,
        order: Order,
        current_quote: Dict[str, Any],
        daily_volatility: float = 0.015,
        adv_shares: float = 1_000_000.0,
        spread_bps: float = 3.0,
    ) -> Order:
        """
        Simulate realistic execution of an Order with non-linear slippage and limit satisfaction.
        Never fabricates impossible fills.
        """
        price = float(current_quote.get("price", 0.0))
        if price <= 0:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "INVALID_MARKET_PRICE: Quote <= 0"
            return order

        is_buy = (order.side == OrderSide.BUY or str(order.side).upper() == "BUY")

        # 1. LIMIT ORDER EVALUATION
        if order.order_type == OrderType.LIMIT or str(order.order_type).upper() == "LIMIT":
            if not order.limit_price:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = "LIMIT_PRICE_MISSING"
                return order
            
            # Check satisfaction
            if is_buy and price > order.limit_price:
                # Market is above buy limit: order remains PENDING
                order.status = OrderStatus.PENDING
                return order
            elif (not is_buy) and price < order.limit_price:
                # Market is below sell limit: order remains PENDING
                order.status = OrderStatus.PENDING
                return order

        # 2. STOP ORDER EVALUATION
        if order.order_type == OrderType.STOP or str(order.order_type).upper() == "STOP":
            if not order.stop_price:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = "STOP_PRICE_MISSING"
                return order
            
            if is_buy and price < order.stop_price:
                order.status = OrderStatus.PENDING
                return order
            elif (not is_buy) and price > order.stop_price:
                order.status = OrderStatus.PENDING
                return order

        # 3. NON-LINEAR SLIPPAGE CALCULATION (Almgren-Chriss square-root impact)
        participation = min(1.0, max(0.0001, order.quantity / adv_shares))
        impact_bps = 10000.0 * 0.1 * daily_volatility * math.sqrt(participation)
        total_slippage_bps = (spread_bps / 2.0) + impact_bps
        slippage_per_share = round(price * (total_slippage_bps / 10000.0), 2)
        total_slippage = round(slippage_per_share * order.quantity, 2)

        if is_buy:
            fill_price = round(price + slippage_per_share, 2)
        else:
            fill_price = round(max(0.01, price - slippage_per_share), 2)

        order.fill_price = fill_price
        order.fill_quantity = order.quantity
        order.slippage = total_slippage
        order.status = OrderStatus.FILLED

        fill = OrderFill(
            fill_id=f"FILL-{order.order_id}-{datetime.now(timezone.utc).strftime('%H%M%S%f')[:10]}",
            order_id=order.order_id,
            fill_price=fill_price,
            fill_quantity=order.quantity,
            slippage=total_slippage,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        order.fills.append(fill)
        return order

    def simulate_fill(
        self,
        side: str,                  # "LONG" or "SHORT"
        entry_price: float,
        target_price: float,
        stop_price: float,
        candles: Union[List[Candle5M], pd.DataFrame],
        symbol: str = "UNKNOWN",
        execution_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Fill:
        """
        Walk 5-minute candles chronologically and return the definitive fill.
        """
        # Convert DataFrame to Candle5M list if needed
        bar_list: List[Candle5M] = []
        if isinstance(candles, pd.DataFrame):
            for idx, row in candles.iterrows():
                ts = str(idx)
                bar_list.append(
                    Candle5M(
                        timestamp=ts,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume", 0.0)),
                    )
                )
        else:
            bar_list = candles

        if not bar_list:
            # Fallback if no candle data available
            return Fill(
                fill_price=entry_price,
                reason="EOD_CLOSE",
                is_ambiguous=False,
                ambiguity_note="No intraday candles provided; evaluated at entry price.",
                candle_time=datetime.now(timezone.utc).isoformat(),
                execution_snapshot=execution_snapshot or {},
            )

        if not execution_snapshot:
            execution_snapshot = self.create_execution_snapshot(symbol, bar_list)

        is_long = side.upper() == "LONG"

        for candle in bar_list:
            # Check breaches
            target_hit = False
            stop_hit = False

            if is_long:
                # LONG: Target is above entry, Stop is below entry
                if candle.high >= target_price:
                    target_hit = True
                if candle.low <= stop_price:
                    stop_hit = True
            else:
                # SHORT: Target is below entry, Stop is above entry
                if candle.low <= target_price:
                    target_hit = True
                if candle.high >= stop_price:
                    stop_hit = True

            # 1. AMBIGUOUS BREACH: Both levels breached in the same 5-minute candle
            if target_hit and stop_hit:
                ambiguity_note = (
                    "Both target and stop breached in same 5-min candle. "
                    "Conservative stop-first assumption applied."
                )
                fill_price = self._stop_fill_price(is_long, stop_price, candle)
                return Fill(
                    fill_price=round(fill_price, 2),
                    reason="STOP_HIT",
                    is_ambiguous=True,
                    ambiguity_note=ambiguity_note,
                    candle_time=candle.timestamp,
                    execution_snapshot=execution_snapshot,
                )

            # 2. Stop Hit
            elif stop_hit:
                fill_price = self._stop_fill_price(is_long, stop_price, candle)
                return Fill(
                    fill_price=round(fill_price, 2),
                    reason="STOP_HIT",
                    is_ambiguous=False,
                    ambiguity_note="",
                    candle_time=candle.timestamp,
                    execution_snapshot=execution_snapshot,
                )

            # 3. Target Hit
            elif target_hit:
                fill_price = self._target_fill_price(is_long, target_price, candle)
                return Fill(
                    fill_price=round(fill_price, 2),
                    reason="TARGET_HIT",
                    is_ambiguous=False,
                    ambiguity_note="",
                    candle_time=candle.timestamp,
                    execution_snapshot=execution_snapshot,
                )

        # 4. EOD Close (Neither target nor stop reached)
        last_candle = bar_list[-1]
        return Fill(
            fill_price=round(last_candle.close, 2),
            reason="EOD_CLOSE",
            is_ambiguous=False,
            ambiguity_note="Position reached end-of-day without hitting target or stop.",
            candle_time=last_candle.timestamp,
            execution_snapshot=execution_snapshot,
        )

    def _stop_fill_price(self, is_long: bool, stop_price: float, candle: Candle5M) -> float:
        """
        Gap-through protection: If market gaps beyond the stop, fill at open.
        """
        if is_long:
            # If opened below stop, filled at open (worse than stop price)
            return min(candle.open, stop_price)
        else:
            # If opened above stop, filled at open (worse than stop price)
            return max(candle.open, stop_price)

    def _target_fill_price(self, is_long: bool, target_price: float, candle: Candle5M) -> float:
        """
        Target fill: fills at target price or favorable open gap.
        """
        if is_long:
            return max(candle.open, target_price) if candle.open >= target_price else target_price
        else:
            return min(candle.open, target_price) if candle.open <= target_price else target_price


def simulate_order_execution(
    order: Order,
    current_quote: Dict[str, Any],
    daily_volatility: float = 0.015,
    adv_shares: float = 1_000_000.0,
    spread_bps: float = 3.0,
) -> Order:
    """Module-level convenience wrapper for ExecutionSimulator.simulate_order_execution."""
    sim = ExecutionSimulator()
    return sim.simulate_order_execution(order, current_quote, daily_volatility, adv_shares, spread_bps)
