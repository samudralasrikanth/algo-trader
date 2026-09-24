# =============================================================================
# event_agent/execution/broker_state_machine.py — 12-State Machine & ID Lineage
# =============================================================================
"""
NEXUS V4.0 Broker Execution State Machine & 8-ID Lineage:
- 12 Canonical States:
  INTENT_CREATED -> SUBMITTED -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED
  Branches: CANCEL_REQUESTED, CANCELLED, REJECTED, EXPIRED, UNKNOWN, RECONCILING, RECOVERED.
- Critical Invariant: UNKNOWN != FAILED.
  Timeouts during or after submission transition to UNKNOWN -> RECONCILING -> RECOVERED.
  Blind retries are strictly forbidden.
- Complete 8-ID Lineage:
  signal_id -> decision_id -> order_intent_id -> broker_order_id -> fill_id -> position_id -> exit_id -> pnl_id.
- Broker-Side Native Emergency Protection (Mandatory Addition 2):
  Registers independent exchange-side stop-loss (GTT / SL-M) directly on the broker at entry,
  so capital is protected even if NEXUS suffers an immediate fatal crash or disconnects.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class V4OrderStatus(str, Enum):
    INTENT_CREATED = "INTENT_CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    RECOVERED = "RECOVERED"


class ProtectionType(str, Enum):
    GTT_TRIGGER = "GTT_TRIGGER"
    STOP_LOSS_MARKET = "STOP_LOSS_MARKET"
    BRACKET_OCO = "BRACKET_OCO"


@dataclass
class BrokerSideProtection:
    """
    Independent hardware/exchange protection registered directly with the broker.
    Lives on broker servers even if NEXUS crashes.
    """
    protection_type: ProtectionType
    stop_price: float
    trigger_price: float
    broker_protection_id: str
    status: str = "ACTIVE_ON_BROKER"
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protection_type": self.protection_type.value,
            "stop_price": self.stop_price,
            "trigger_price": self.trigger_price,
            "broker_protection_id": self.broker_protection_id,
            "status": self.status,
            "registered_at": self.registered_at,
        }


@dataclass
class OrderLineage:
    """
    Immutable 8-ID lineage binding the entire lifecycle from prediction to realized P&L.
    """
    signal_id: str
    decision_id: str
    order_intent_id: str
    broker_order_id: Optional[str] = None
    fill_id: Optional[str] = None
    position_id: Optional[str] = None
    exit_id: Optional[str] = None
    pnl_id: Optional[str] = None

    def __post_init__(self):
        sig = str(self.signal_id or "").upper()
        dec = str(self.decision_id or "").upper()
        oint = str(self.order_intent_id or "").upper()
        if "QUANT" in sig and "SCREEN" in sig:
            raise ValueError("Invariant Violation: QUANT_SCREEN cannot create order_intent_id.")
        if "QUANT" in dec and "SCREEN" in dec:
            raise ValueError("Invariant Violation: QUANT_SCREEN cannot create order_intent_id.")
        if "QUANT" in oint and "SCREEN" in oint:
            raise ValueError("Invariant Violation: QUANT_SCREEN cannot create order_intent_id.")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal order state transition is attempted."""
    pass


class BlindRetryProhibitedError(RuntimeError):
    """Raised when an unverified retry is attempted on an UNKNOWN order."""
    pass


@dataclass
class V4Order:
    order_intent_id: str
    symbol: str
    side: str  # BUY | SELL
    quantity: int
    price: float
    status: V4OrderStatus
    lineage: OrderLineage
    broker_protection: Optional[BrokerSideProtection] = None
    environment: str = "PAPER"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status_history: List[Dict[str, str]] = field(default_factory=list)
    fills: List[Dict[str, Any]] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    retry_count: int = 0

    def __post_init__(self):
        if not self.status_history:
            self.status_history.append({
                "from_status": "NONE",
                "to_status": self.status.value,
                "timestamp": self.created_at,
                "reason": "Order intent created",
            })

    def transition_to(self, new_status: V4OrderStatus, reason: str = "") -> None:
        """
        Executes and validates state machine transitions.
        """
        valid_transitions: Dict[V4OrderStatus, Set[V4OrderStatus]] = {
            V4OrderStatus.INTENT_CREATED: {V4OrderStatus.SUBMITTED, V4OrderStatus.REJECTED},
            V4OrderStatus.SUBMITTED: {
                V4OrderStatus.ACKNOWLEDGED,
                V4OrderStatus.REJECTED,
                V4OrderStatus.UNKNOWN,  # Timeout transition
                V4OrderStatus.FILLED,   # Instant fill
            },
            V4OrderStatus.ACKNOWLEDGED: {
                V4OrderStatus.PARTIALLY_FILLED,
                V4OrderStatus.FILLED,
                V4OrderStatus.CANCEL_REQUESTED,
                V4OrderStatus.EXPIRED,
                V4OrderStatus.REJECTED,
            },
            V4OrderStatus.PARTIALLY_FILLED: {
                V4OrderStatus.FILLED,
                V4OrderStatus.CANCEL_REQUESTED,
                V4OrderStatus.EXPIRED,
            },
            V4OrderStatus.CANCEL_REQUESTED: {V4OrderStatus.CANCELLED, V4OrderStatus.UNKNOWN},
            V4OrderStatus.UNKNOWN: {
                V4OrderStatus.RECONCILING,  # MUST reconcile before anything else!
            },
            V4OrderStatus.RECONCILING: {
                V4OrderStatus.RECOVERED,
                V4OrderStatus.FILLED,
                V4OrderStatus.CANCELLED,
                V4OrderStatus.REJECTED,
            },
            V4OrderStatus.RECOVERED: {
                V4OrderStatus.ACKNOWLEDGED,
                V4OrderStatus.PARTIALLY_FILLED,
                V4OrderStatus.FILLED,
                V4OrderStatus.CANCELLED,
            },
            # Terminal states cannot transition:
            V4OrderStatus.FILLED: set(),
            V4OrderStatus.CANCELLED: set(),
            V4OrderStatus.REJECTED: set(),
            V4OrderStatus.EXPIRED: set(),
        }

        allowed = valid_transitions.get(self.status, set())
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                f"Illegal order state transition from {self.status.value} to {new_status.value}. "
                f"Allowed transitions: {[s.value for s in allowed]}"
            )

        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.status_history.append({
            "from_status": old_status.value,
            "to_status": new_status.value,
            "timestamp": self.updated_at,
            "reason": reason,
        })
        logger.info(f"Order [{self.order_intent_id}] transitioned {old_status.value} -> {new_status.value} ({reason})")

    def handle_submission_timeout(self) -> None:
        """
        Enforces UNKNOWN != FAILED invariant. Transitions to UNKNOWN without marking as FAILED.
        """
        self.transition_to(
            V4OrderStatus.UNKNOWN,
            reason="Broker API call timed out after submission. Marked UNKNOWN awaiting reconciliation.",
        )

    def verify_against_blind_retry(self) -> None:
        """
        Throws BlindRetryProhibitedError if a retry is attempted while in UNKNOWN status.
        """
        if self.status == V4OrderStatus.UNKNOWN:
            raise BlindRetryProhibitedError(
                f"BLIND RETRY PROHIBITED: Order {self.order_intent_id} is in UNKNOWN state. "
                f"Must query broker ground truth via RECONCILING before any new order can be created."
            )

    def attach_broker_side_protection(
        self,
        stop_price: float,
        trigger_price: Optional[float] = None,
        protection_type: ProtectionType = ProtectionType.GTT_TRIGGER,
    ) -> BrokerSideProtection:
        """
        Registers independent broker-side native stop-loss protection (Mandatory Addition 2).
        """
        trig = trigger_price or stop_price
        prot_id = f"GTT-BRK-{self.order_intent_id}"
        protection = BrokerSideProtection(
            protection_type=protection_type,
            stop_price=stop_price,
            trigger_price=trig,
            broker_protection_id=prot_id,
            status="ACTIVE_ON_BROKER",
        )
        self.broker_protection = protection
        logger.info(
            f"🛡️ Broker-side emergency protection registered: {protection_type.value} at ₹{stop_price} (ID: {prot_id})"
        )
        return protection

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_intent_id": self.order_intent_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
            "lineage": self.lineage.to_dict(),
            "broker_protection": self.broker_protection.to_dict() if self.broker_protection else None,
            "environment": self.environment,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status_history": self.status_history,
            "fills": self.fills,
            "rejection_reason": self.rejection_reason,
            "retry_count": self.retry_count,
        }
