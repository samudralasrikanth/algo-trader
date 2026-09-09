# =============================================================================
# event_agent/certification/reality_gap.py — Backtest to Paper Reality Gap
# =============================================================================
"""
V3.6 Backtest-to-Paper Reality Gap Tracker.
Continuously measures the execution degradation across 4 critical milestones:
  1. Backtest Expected Price (P_expected)
  2. Paper Order Arrival Price (P_arrival)
  3. Actual Fill Price (P_fill)
  4. Actual Realized Exit Outcome (P_exit)

Computes Implementation Shortfall, Realization Gap, and Slippage Drag to ensure
theoretical edges are not eroded by microstructure friction.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RealityGapRecord:
    trade_id: str
    symbol: str
    direction: str                     # "BUY" | "SELL"
    backtest_expected_price: float
    order_arrival_price: float
    actual_fill_price: float
    actual_exit_price: float
    backtest_expected_return_pct: float
    actual_realized_return_pct: float
    implementation_shortfall_bps: float
    realization_gap_pct: float
    slippage_drag_pct: float
    is_gap_acceptable: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RealityGapTracker:
    """
    Tracks and aggregates the gap between backtest models and simulated/live fills.
    """

    MAX_ACCEPTABLE_SHORTFALL_BPS = 25.0  # 0.25% max slippage tolerance
    MAX_ACCEPTABLE_REALIZATION_GAP_PCT = 1.0 # 1.0% max return divergence

    @classmethod
    def evaluate_trade_gap(
        cls,
        trade_id: str,
        symbol: str,
        direction: str,
        backtest_expected_price: float,
        order_arrival_price: float,
        actual_fill_price: float,
        actual_exit_price: float,
        backtest_expected_return_pct: float,
    ) -> RealityGapRecord:
        """
        Calculates execution shortfall and realization gap for an individual trade.
        """
        is_buy = (direction.upper() == "BUY")

        # Implementation Shortfall (bps): price change from arrival to fill
        if is_buy:
            shortfall_bps = ((actual_fill_price - order_arrival_price) / order_arrival_price) * 10000.0
            actual_return_pct = ((actual_exit_price - actual_fill_price) / actual_fill_price) * 100.0
        else:
            shortfall_bps = ((order_arrival_price - actual_fill_price) / order_arrival_price) * 10000.0
            actual_return_pct = ((actual_fill_price - actual_exit_price) / actual_fill_price) * 100.0

        # Realization Gap: Actual Realized Return - Backtest Expected Return
        realization_gap = actual_return_pct - backtest_expected_return_pct

        # Slippage Drag as fraction of gross expected edge
        gross_edge = abs(backtest_expected_return_pct)
        slippage_pct = abs(shortfall_bps) / 100.0
        slippage_drag = (slippage_pct / max(0.10, gross_edge)) * 100.0

        is_acceptable = (
            abs(shortfall_bps) <= cls.MAX_ACCEPTABLE_SHORTFALL_BPS
            and abs(realization_gap) <= cls.MAX_ACCEPTABLE_REALIZATION_GAP_PCT
        )

        return RealityGapRecord(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            backtest_expected_price=round(backtest_expected_price, 2),
            order_arrival_price=round(order_arrival_price, 2),
            actual_fill_price=round(actual_fill_price, 2),
            actual_exit_price=round(actual_exit_price, 2),
            backtest_expected_return_pct=round(backtest_expected_return_pct, 2),
            actual_realized_return_pct=round(actual_return_pct, 2),
            implementation_shortfall_bps=round(shortfall_bps, 1),
            realization_gap_pct=round(realization_gap, 2),
            slippage_drag_pct=round(slippage_drag, 1),
            is_gap_acceptable=is_acceptable,
        )

    @classmethod
    def aggregate_reality_gap(cls, records: List[RealityGapRecord]) -> Dict[str, Any]:
        """
        Summarizes portfolio-level realization gap across a batch of paper trades.
        """
        if not records:
            return {
                "total_trades": 0,
                "mean_shortfall_bps": 0.0,
                "mean_realization_gap_pct": 0.0,
                "mean_slippage_drag_pct": 0.0,
                "acceptable_gap_rate_pct": 100.0,
                "status": "NO_DATA",
            }

        shortfalls = [r.implementation_shortfall_bps for r in records]
        gaps = [r.realization_gap_pct for r in records]
        drags = [r.slippage_drag_pct for r in records]
        acceptable_count = sum(1 for r in records if r.is_gap_acceptable)

        mean_shortfall = float(np.mean(shortfalls))
        mean_gap = float(np.mean(gaps))
        mean_drag = float(np.mean(drags))
        pass_rate = (acceptable_count / len(records)) * 100.0

        status = "PASS" if pass_rate >= 85.0 and abs(mean_shortfall) <= 12.0 else "DEGRADED"

        return {
            "total_trades": len(records),
            "mean_shortfall_bps": round(mean_shortfall, 2),
            "mean_realization_gap_pct": round(mean_gap, 2),
            "mean_slippage_drag_pct": round(mean_drag, 2),
            "acceptable_gap_rate_pct": round(pass_rate, 1),
            "status": status,
        }
