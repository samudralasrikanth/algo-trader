# =============================================================================
# event_agent/reporting/slippage_telemetry.py — Slippage & Implementation Shortfall
# =============================================================================
"""
NEXUS V4.0 Execution & Slippage Telemetry Engine:
- Records 11 price checkpoints per executed trade.
- Calculates EXPECTED P&L, ACTUAL P&L, and REALIZATION GAP.
- Computes distribution analytics: mean, median, p95, p99 slippage, implementation shortfall,
  fees, taxes, and submission-to-ack latency.
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class TradeExecutionTelemetry:
    trade_id: str
    symbol: str
    side: str  # BUY | SELL
    quantity: int
    predicted_price: float
    decision_price: float
    order_submission_price: float
    broker_ack_price: float
    fill_price: float
    exit_price: Optional[float] = None
    expected_slippage_bps: float = 5.0
    actual_slippage_bps: float = 0.0
    implementation_shortfall_bps: float = 0.0
    fees_inr: float = 0.0
    taxes_inr: float = 0.0
    expected_pnl: float = 0.0
    actual_pnl: float = 0.0
    realization_gap_inr: float = 0.0
    submission_to_ack_ms: float = 0.0
    ack_to_fill_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def calculate_metrics(self) -> None:
        """Computes slippage, implementation shortfall, and realization gap."""
        if self.decision_price > 0 and self.fill_price > 0:
            if self.side.upper() == "BUY":
                slip = ((self.fill_price - self.decision_price) / self.decision_price) * 10_000.0
                shortfall = ((self.fill_price - self.predicted_price) / self.predicted_price) * 10_000.0 if self.predicted_price > 0 else slip
            else:
                slip = ((self.decision_price - self.fill_price) / self.decision_price) * 10_000.0
                shortfall = ((self.predicted_price - self.fill_price) / self.predicted_price) * 10_000.0 if self.predicted_price > 0 else slip

            self.actual_slippage_bps = round(slip, 2)
            self.implementation_shortfall_bps = round(shortfall, 2)

        # Realization Gap
        if self.exit_price and self.exit_price > 0:
            if self.side.upper() == "BUY":
                self.expected_pnl = (self.exit_price - self.decision_price) * self.quantity
                gross_actual = (self.exit_price - self.fill_price) * self.quantity
            else:
                self.expected_pnl = (self.decision_price - self.exit_price) * self.quantity
                gross_actual = (self.fill_price - self.exit_price) * self.quantity

            self.actual_pnl = gross_actual - self.fees_inr - self.taxes_inr
            self.realization_gap_inr = round(self.expected_pnl - self.actual_pnl, 2)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionTelemetryAggregator:
    """
    Computes statistical percentiles and aggregates over execution records.
    """

    @classmethod
    def aggregate(cls, records: List[TradeExecutionTelemetry]) -> Dict[str, Any]:
        if not records:
            return {
                "total_trades": 0,
                "mean_slippage_bps": 0.0,
                "median_slippage_bps": 0.0,
                "p95_slippage_bps": 0.0,
                "p99_slippage_bps": 0.0,
                "mean_shortfall_bps": 0.0,
                "total_fees_inr": 0.0,
                "total_taxes_inr": 0.0,
                "total_expected_pnl": 0.0,
                "total_actual_pnl": 0.0,
                "total_realization_gap_inr": 0.0,
                "mean_latency_ms": 0.0,
            }

        slippages = sorted([r.actual_slippage_bps for r in records])
        shortfalls = [r.implementation_shortfall_bps for r in records]
        latencies = [r.submission_to_ack_ms for r in records if r.submission_to_ack_ms > 0]

        n = len(slippages)
        mean_slip = sum(slippages) / n
        median_slip = slippages[n // 2]
        p95_idx = min(n - 1, math.floor(0.95 * n))
        p99_idx = min(n - 1, math.floor(0.99 * n))

        total_fees = sum(r.fees_inr for r in records)
        total_taxes = sum(r.taxes_inr for r in records)
        total_exp_pnl = sum(r.expected_pnl for r in records)
        total_act_pnl = sum(r.actual_pnl for r in records)
        total_gap = sum(r.realization_gap_inr for r in records)

        return {
            "total_trades": n,
            "mean_slippage_bps": round(mean_slip, 2),
            "median_slippage_bps": round(median_slip, 2),
            "p95_slippage_bps": round(slippages[p95_idx], 2),
            "p99_slippage_bps": round(slippages[p99_idx], 2),
            "mean_shortfall_bps": round(sum(shortfalls) / n, 2),
            "total_fees_inr": round(total_fees, 2),
            "total_taxes_inr": round(total_taxes, 2),
            "total_expected_pnl": round(total_exp_pnl, 2),
            "total_actual_pnl": round(total_act_pnl, 2),
            "total_realization_gap_inr": round(total_gap, 2),
            "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        }
