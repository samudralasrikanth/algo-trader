"""
NEXUS V4.0 — Broker State Machine, 8-ID Lineage & Continuous Reconciliation Test Suite
Tests:
1. 12-state order machine with UNKNOWN != FAILED invariant.
2. Prohibition of blind retries when status is UNKNOWN.
3. Complete 8-ID lineage from prediction to P&L.
4. Broker-side native stop-loss protection (GTT / SL-M).
5. Durable SHA-256 idempotency key reservation and replay protection.
6. Continuous dual-state reconciliation and mismatch kill switch trigger.
"""

import pytest
from datetime import datetime, timezone

from event_agent.execution.broker_state_machine import (
    V4Order,
    V4OrderStatus,
    OrderLineage,
    ProtectionType,
    InvalidStateTransitionError,
    BlindRetryProhibitedError,
)
from event_agent.execution.idempotency import (
    IdempotencyManager,
    DuplicateOrderError,
)
from event_agent.reconciliation.broker_reconciler import (
    ContinuousBrokerReconciler,
    ReconciliationStatus,
    MismatchSeverity,
)
from event_agent.risk.kill_switch import (
    IndependentKillSwitch,
    KillSwitchLevel,
)


@pytest.fixture
def clean_kill_switch(tmp_path):
    IndependentKillSwitch._instance = None
    db_file = str(tmp_path / "test_reconciler_ks.db")
    ks = IndependentKillSwitch(db_path=db_file)
    return ks


@pytest.fixture
def clean_idempotency(tmp_path):
    IdempotencyManager._instance = None
    db_file = str(tmp_path / "test_idemp.db")
    mgr = IdempotencyManager(db_path=db_file)
    return mgr


def test_order_valid_lifecycle_transitions():
    """Verify normal order lifecycle from INTENT_CREATED to FILLED."""
    lineage = OrderLineage(
        signal_id="SIG-001",
        decision_id="DEC-001",
        order_intent_id="INT-001",
    )
    order = V4Order(
        order_intent_id="INT-001",
        symbol="RELIANCE.NS",
        side="BUY",
        quantity=10,
        price=2500.0,
        status=V4OrderStatus.INTENT_CREATED,
        lineage=lineage,
    )

    # Valid flow
    order.transition_to(V4OrderStatus.SUBMITTED, reason="Dispatched to broker")
    order.transition_to(V4OrderStatus.ACKNOWLEDGED, reason="Broker assigned order ID")
    order.transition_to(V4OrderStatus.PARTIALLY_FILLED, reason="5 of 10 filled")
    order.transition_to(V4OrderStatus.FILLED, reason="Remaining 5 filled")

    assert order.status == V4OrderStatus.FILLED
    assert len(order.status_history) == 5

    # Illegal transition from terminal FILLED state must raise InvalidStateTransitionError
    with pytest.raises(InvalidStateTransitionError):
        order.transition_to(V4OrderStatus.SUBMITTED, reason="Illegal retry after fill")


def test_unknown_is_not_failed_invariant():
    """
    CRITICAL INVARIANT: UNKNOWN != FAILED.
    A timeout during submission must transition to UNKNOWN -> RECONCILING -> RECOVERED.
    It must NEVER be marked as FAILED or blindly retried.
    """
    lineage = OrderLineage(
        signal_id="SIG-002",
        decision_id="DEC-002",
        order_intent_id="INT-002",
    )
    order = V4Order(
        order_intent_id="INT-002",
        symbol="TCS.NS",
        side="BUY",
        quantity=5,
        price=3800.0,
        status=V4OrderStatus.INTENT_CREATED,
        lineage=lineage,
    )

    order.transition_to(V4OrderStatus.SUBMITTED)

    # Simulate broker timeout
    order.handle_submission_timeout()
    assert order.status == V4OrderStatus.UNKNOWN

    # Blind retry MUST be blocked
    with pytest.raises(BlindRetryProhibitedError) as exc_info:
        order.verify_against_blind_retry()
    assert "BLIND RETRY PROHIBITED" in str(exc_info.value)

    # Order must transition through RECONCILING to RECOVERED
    order.transition_to(V4OrderStatus.RECONCILING, reason="Reconciling with broker orderbook")
    assert order.status == V4OrderStatus.RECONCILING

    order.transition_to(V4OrderStatus.RECOVERED, reason="Found executed fill on broker")
    assert order.status == V4OrderStatus.RECOVERED

    # Can now be safely marked FILLED
    order.transition_to(V4OrderStatus.FILLED, reason="Confirmed fill registered")
    assert order.status == V4OrderStatus.FILLED


def test_complete_8_id_lineage():
    """Verify complete 8-ID lineage is tracked and serialized."""
    lineage = OrderLineage(
        signal_id="SIG-20260910-001",
        decision_id="DEC-20260910-001",
        order_intent_id="INT-20260910-001",
        broker_order_id="BROKER-NSE-998811",
        fill_id="FILL-NSE-112233",
        position_id="POS-RELIANCE-01",
        exit_id="EXIT-20260910-001",
        pnl_id="PNL-REALIZED-5544",
    )
    d = lineage.to_dict()
    assert len(d) == 8
    assert all(v is not None for v in d.values())


def test_broker_side_native_protection_attachment():
    """
    MANDATORY ADDITION 2:
    Verify native broker stop-loss (GTT / SL-M) is registered directly with the broker.
    """
    lineage = OrderLineage(
        signal_id="SIG-003",
        decision_id="DEC-003",
        order_intent_id="INT-003",
    )
    order = V4Order(
        order_intent_id="INT-003",
        symbol="INFY.NS",
        side="BUY",
        quantity=20,
        price=1800.0,
        status=V4OrderStatus.INTENT_CREATED,
        lineage=lineage,
    )

    # Attach broker-side GTT stop-loss at 1780.0
    prot = order.attach_broker_side_protection(
        stop_price=1780.0,
        trigger_price=1782.0,
        protection_type=ProtectionType.GTT_TRIGGER,
    )

    assert prot.protection_type == ProtectionType.GTT_TRIGGER
    assert prot.stop_price == 1780.0
    assert prot.trigger_price == 1782.0
    assert prot.status == "ACTIVE_ON_BROKER"
    assert "GTT" in prot.broker_protection_id
    assert order.broker_protection is not None


def test_idempotency_key_deduplication(clean_idempotency):
    """Verify IdempotencyManager rejects identical order keys."""
    signal_id = "SIG-999"
    symbol = "HDFCBANK.NS"
    side = "BUY"
    window = "2026-09-10"

    key = clean_idempotency.generate_key(signal_id, symbol, side, window)
    assert len(key) == 64  # SHA-256 hex string

    # First reservation succeeds
    ok1, key1, rec1 = clean_idempotency.reserve(signal_id, symbol, side, "INT-999-A", window)
    assert ok1 is True
    assert len(key1) == 64
    assert rec1 is None  # No existing duplicate

    # Duplicate reservation fails and returns existing record
    ok2, key2, rec2 = clean_idempotency.reserve(signal_id, symbol, side, "INT-999-B", window)
    assert ok2 is False
    assert rec2 is not None
    assert rec2.order_intent_id == "INT-999-A"


def test_continuous_reconciler_detects_mismatch_and_fires_kill_switch(clean_kill_switch):
    """Verify ContinuousBrokerReconciler emits RECONCILIATION_MISMATCH on ghost positions."""
    reconciler = ContinuousBrokerReconciler(kill_switch=clean_kill_switch)

    nexus_orders = []
    broker_orders = []

    nexus_positions = [
        {"symbol": "RELIANCE.NS", "quantity": 10, "average_price": 2500.0}
    ]
    # Broker has divergent quantity and unexpected position
    broker_positions = [
        {"symbol": "RELIANCE.NS", "quantity": 15, "average_price": 2500.0},
        {"symbol": "UNKNOWN_GHOST.NS", "quantity": 100, "average_price": 50.0},
    ]

    report = reconciler.reconcile(
        nexus_orders=nexus_orders,
        broker_orders=broker_orders,
        nexus_positions=nexus_positions,
        broker_positions=broker_positions,
        nexus_realized_pnl=500.0,
        broker_realized_pnl=500.0,
    )

    assert report.status == ReconciliationStatus.RECONCILIATION_MISMATCH
    assert report.blocks_live_trading is True
    assert len(report.discrepancies) >= 2

    # Verify Kill Switch was automatically activated
    blocked, act = clean_kill_switch.is_order_blocked(strategy="ANY", symbol="RELIANCE.NS")
    assert blocked is True
    assert act.level == KillSwitchLevel.GLOBAL


def test_physical_broker_failure_9_step_protocol():
    """
    MANDATORY LIVE REQUIREMENT:
    Verify the 9-step physical broker failure protocol:
    NEXUS entry -> Broker confirm -> Native SL confirm -> Hard KILL NEXUS ->
    Sever Network -> Unmanaged position -> Broker trigger -> Verify execution -> Reconcile
    """
    from event_agent.certification.physical_broker_failure_harness import (
        PhysicalBrokerFailureHarness,
        ProtectionType,
    )

    harness = PhysicalBrokerFailureHarness()
    report = harness.execute_9_step_protocol(
        symbol="TCS.NS",
        quantity=25,
        entry_price=3800.0,
        stop_trigger_price=3720.0,
        protection_type=ProtectionType.EXCHANGE_SL_M,
    )

    assert report.passed is True
    assert len(report.steps) == 9
    assert all(s.passed for s in report.steps)
    assert report.verdict == "PASSED_PHYSICAL_FAILURE_CERTIFICATION"

    # Step 4 & 5: NEXUS process was killed and network severed
    assert report.steps[3].passed is True  # Kill
    assert report.steps[4].passed is True  # Disconnect

    # Step 6: Broker position remained alive during blackout
    assert report.broker_state_during_blackout["position"]["status"] == "OPEN"

    # Step 8: Broker independently executed fill without NEXUS
    assert report.steps[7].passed is True

    # Step 9: Reconciler synchronized on recovery with ZERO duplicate orders
    assert report.reconciliation_state_after_recovery["duplicate_orders_placed"] == 0
    assert report.reconciliation_state_after_recovery["reconciled"] is True

    # Disclosures check
    assert len(report.caveats_and_disclosures) >= 4

