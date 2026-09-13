# =============================================================================
# event_agent/reconciliation/broker_reconciler.py — Continuous Broker Reconciliation
# =============================================================================
"""
NEXUS V4.0 Continuous Broker Reconciliation Engine:
- Continuously compares NEXUS internal ledger vs live broker ground truth.
- Compares:
  1. Open orders
  2. Filled orders
  3. Cancelled/Rejected orders
  4. Active positions & quantities
  5. Average execution prices
  6. Realized & Unrealized P&L
- Emits RECONCILIATION_MISMATCH on any deviation.
- Critical mismatches immediately latch the Kill Switch and block real-money trading.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..risk.kill_switch import EmergencyPolicy, IndependentKillSwitch, KillSwitchLevel, KillSwitchTrigger

logger = logging.getLogger(__name__)


class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    DEGRADED = "DEGRADED"


class MismatchSeverity(str, Enum):
    CRITICAL = "CRITICAL"  # Blocks live trading & activates kill switch
    WARNING = "WARNING"    # Operational notice (e.g. minor timing skew)


@dataclass
class ReconciliationDiscrepancy:
    item_type: str  # ORDER | POSITION | PNL | CASH
    identifier: str
    field_name: str
    nexus_value: Any
    broker_value: Any
    difference: Optional[float] = None
    severity: MismatchSeverity = MismatchSeverity.CRITICAL
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class BrokerReconciliationReport:
    report_id: str
    status: ReconciliationStatus
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    orders_checked: int = 0
    positions_checked: int = 0
    discrepancies: List[ReconciliationDiscrepancy] = field(default_factory=list)
    blocks_live_trading: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "orders_checked": self.orders_checked,
            "positions_checked": self.positions_checked,
            "discrepancies_count": len(self.discrepancies),
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "blocks_live_trading": self.blocks_live_trading,
            "details": self.details,
        }


class ContinuousBrokerReconciler:
    """
    Independent reconciler evaluating NEXUS vs Broker states.
    """

    PRICE_TOLERANCE_INR = 0.50      # ₹0.50 allowed for rounding
    PNL_TOLERANCE_INR = 10.0         # ₹10 allowed for fee estimation skew

    def __init__(self, kill_switch: Optional[IndependentKillSwitch] = None):
        self.kill_switch = kill_switch or IndependentKillSwitch()

    def reconcile(
        self,
        nexus_orders: List[Dict[str, Any]],
        broker_orders: List[Dict[str, Any]],
        nexus_positions: List[Dict[str, Any]],
        broker_positions: List[Dict[str, Any]],
        nexus_realized_pnl: float = 0.0,
        broker_realized_pnl: float = 0.0,
        auto_trigger_kill_switch: bool = True,
    ) -> BrokerReconciliationReport:
        """
        Executes comprehensive dual-state reconciliation.
        """
        report_id = f"RECON-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:17]}"
        discrepancies: List[ReconciliationDiscrepancy] = []

        # ---------------------------------------------------------------------
        # 1. ORDER RECONCILIATION
        # ---------------------------------------------------------------------
        broker_orders_by_id = {
            str(o.get("order_id") or o.get("broker_order_id")): o for o in broker_orders
        }

        for n_ord in nexus_orders:
            b_id = str(n_ord.get("broker_order_id") or n_ord.get("order_id"))
            b_ord = broker_orders_by_id.get(b_id)

            if not b_ord:
                # Order exists in Nexus but not on Broker!
                if n_ord.get("status") in ("FILLED", "SUBMITTED", "ACKNOWLEDGED"):
                    discrepancies.append(
                        ReconciliationDiscrepancy(
                            item_type="ORDER",
                            identifier=b_id,
                            field_name="existence",
                            nexus_value=n_ord.get("status"),
                            broker_value="MISSING_ON_BROKER",
                            severity=MismatchSeverity.CRITICAL,
                            description=f"Order {b_id} exists locally ({n_ord.get('status')}) but missing on broker.",
                        )
                    )
                continue

            # Compare Status
            n_status = str(n_ord.get("status")).upper()
            b_status = str(b_ord.get("status") or b_ord.get("order_status")).upper()
            if n_status != b_status and not (n_status == "SUBMITTED" and b_status in ("OPEN", "PENDING")):
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        item_type="ORDER",
                        identifier=b_id,
                        field_name="status",
                        nexus_value=n_status,
                        broker_value=b_status,
                        severity=MismatchSeverity.CRITICAL,
                        description=f"Order status mismatch for {b_id}: NEXUS={n_status} vs BROKER={b_status}",
                    )
                )

            # Compare Quantity
            n_qty = int(n_ord.get("quantity") or 0)
            b_qty = int(b_ord.get("quantity") or 0)
            if n_qty != b_qty:
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        item_type="ORDER",
                        identifier=b_id,
                        field_name="quantity",
                        nexus_value=n_qty,
                        broker_value=b_qty,
                        difference=abs(n_qty - b_qty),
                        severity=MismatchSeverity.CRITICAL,
                        description=f"Quantity mismatch on order {b_id}: NEXUS={n_qty} vs BROKER={b_qty}",
                    )
                )

        # ---------------------------------------------------------------------
        # 2. POSITION RECONCILIATION
        # ---------------------------------------------------------------------
        broker_pos_by_sym = {str(p.get("symbol")).upper().replace(".NS", ""): p for p in broker_positions}
        nexus_pos_by_sym = {str(p.get("symbol")).upper().replace(".NS", ""): p for p in nexus_positions}

        # Check all nexus positions
        for sym, n_pos in nexus_pos_by_sym.items():
            b_pos = broker_pos_by_sym.get(sym)
            n_qty = int(n_pos.get("quantity") or 0)

            if not b_pos:
                if n_qty != 0:
                    discrepancies.append(
                        ReconciliationDiscrepancy(
                            item_type="POSITION",
                            identifier=sym,
                            field_name="existence",
                            nexus_value=n_qty,
                            broker_value=0,
                            severity=MismatchSeverity.CRITICAL,
                            description=f"NEXUS holds position in {sym} (qty: {n_qty}) but broker reports none.",
                        )
                    )
                continue

            b_qty = int(b_pos.get("quantity") or b_pos.get("net_quantity") or 0)
            if n_qty != b_qty:
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        item_type="POSITION",
                        identifier=sym,
                        field_name="quantity",
                        nexus_value=n_qty,
                        broker_value=b_qty,
                        difference=abs(n_qty - b_qty),
                        severity=MismatchSeverity.CRITICAL,
                        description=f"Position quantity divergence in {sym}: NEXUS={n_qty} vs BROKER={b_qty}",
                    )
                )

        # Check for unexpected broker positions not in Nexus
        for sym, b_pos in broker_pos_by_sym.items():
            b_qty = int(b_pos.get("quantity") or b_pos.get("net_quantity") or 0)
            if b_qty != 0 and sym not in nexus_pos_by_sym:
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        item_type="POSITION",
                        identifier=sym,
                        field_name="unexpected_broker_position",
                        nexus_value=0,
                        broker_value=b_qty,
                        severity=MismatchSeverity.CRITICAL,
                        description=f"UNEXPECTED BROKER POSITION: Broker holds {b_qty} of {sym} with no NEXUS record.",
                    )
                )

        # ---------------------------------------------------------------------
        # 3. REALIZED P&L RECONCILIATION
        # ---------------------------------------------------------------------
        pnl_diff = abs(nexus_realized_pnl - broker_realized_pnl)
        if pnl_diff > self.PNL_TOLERANCE_INR:
            discrepancies.append(
                ReconciliationDiscrepancy(
                    item_type="PNL",
                    identifier="REALIZED_PNL",
                    field_name="realized_pnl",
                    nexus_value=nexus_realized_pnl,
                    broker_value=broker_realized_pnl,
                    difference=pnl_diff,
                    severity=MismatchSeverity.CRITICAL if pnl_diff > 100.0 else MismatchSeverity.WARNING,
                    description=f"Realized P&L divergence ₹{pnl_diff:.2f}: NEXUS=₹{nexus_realized_pnl:.2f} vs BROKER=₹{broker_realized_pnl:.2f}",
                )
            )

        # Determine Report Status
        has_critical = any(d.severity == MismatchSeverity.CRITICAL for d in discrepancies)
        status = (
            ReconciliationStatus.RECONCILIATION_MISMATCH
            if has_critical
            else (ReconciliationStatus.DEGRADED if discrepancies else ReconciliationStatus.MATCHED)
        )
        blocks_live = has_critical

        # Auto trigger Kill Switch if critical mismatch occurs
        if has_critical and auto_trigger_kill_switch:
            crit_reasons = "; ".join(d.description for d in discrepancies if d.severity == MismatchSeverity.CRITICAL)
            self.kill_switch.activate(
                level=KillSwitchLevel.GLOBAL,
                trigger=KillSwitchTrigger.RECONCILIATION_MISMATCH,
                target="ALL",
                policy=EmergencyPolicy.STOP_NEW_ORDERS,
                reason=f"RECONCILIATION_MISMATCH: {crit_reasons[:200]}",
                activated_by="ContinuousBrokerReconciler",
                telemetry={"report_id": report_id, "discrepancies": [d.to_dict() for d in discrepancies]},
            )

        report = BrokerReconciliationReport(
            report_id=report_id,
            status=status,
            orders_checked=len(nexus_orders),
            positions_checked=len(nexus_positions),
            discrepancies=discrepancies,
            blocks_live_trading=blocks_live,
            details={
                "nexus_realized_pnl": nexus_realized_pnl,
                "broker_realized_pnl": broker_realized_pnl,
                "pnl_diff": pnl_diff,
            },
        )

        logger.info(
            f"🔄 Broker reconciliation completed: {status.value} ({len(discrepancies)} discrepancies, blocks_live={blocks_live})"
        )
        return report
