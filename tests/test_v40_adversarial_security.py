"""
NEXUS V4.0 — Adversarial Security & Invariant Stress Test Suite
Tests 15 adversarial attack scenarios against the execution and risk infrastructure:
1. Replay attack / duplicate order intent
2. Stale tick injection
3. Extreme / negative price anomaly
4. Broker timeout during submission
5. Ghost position on broker
6. Causal timestamp inversion
7. Model hash mismatch / weight tampering
8. Unapproved model version
9. Circuit breaker band bypass attempt
10. Gap risk invalidation bypass attempt
11. Fake fill price outside bar range
12. Unauthorized live escalation
13. Inactive kill switch bypass attempt
14. Capital sizing manipulation
15. Auto-retrain attempt on live model drift
"""

import pytest
from datetime import datetime, timezone, timedelta

from event_agent.execution.trade_guard import (
    TradeGuard,
    TradeGuardVerdict,
)
from event_agent.execution.broker_state_machine import (
    V4Order,
    V4OrderStatus,
    OrderLineage,
    BlindRetryProhibitedError,
)
from event_agent.execution.idempotency import (
    IdempotencyManager,
)
from event_agent.risk.kill_switch import (
    IndependentKillSwitch,
    KillSwitchLevel,
    KillSwitchTrigger,
    EmergencyPolicy,
)
from event_agent.execution.environment import (
    TradingEnvironment,
    EnvironmentManager,
)
from event_agent.engine.model_immutability import (
    CausalDataSafetyEngine,
    ModelImmutabilityEnforcer,
    CausalViolationError,
)
from event_agent.reconciliation.broker_reconciler import (
    ContinuousBrokerReconciler,
    ReconciliationStatus,
)
from event_agent.monitoring.model_drift_monitor import (
    ModelDriftMonitor,
)


@pytest.fixture
def kill_switch(tmp_path):
    IndependentKillSwitch._instance = None
    db_file = str(tmp_path / "test_adv_ks.db")
    ks = IndependentKillSwitch(db_path=db_file)
    return ks


@pytest.fixture
def trade_guard(kill_switch):
    return TradeGuard(kill_switch=kill_switch)


@pytest.fixture
def idempotency(tmp_path):
    IdempotencyManager._instance = None
    db_file = str(tmp_path / "test_adv_idemp.db")
    return IdempotencyManager(db_path=db_file)


# -----------------------------------------------------------------------------
# 1. Replay Attack / Duplicate Order Intent
# -----------------------------------------------------------------------------
def test_attack_01_replay_duplicate_order(idempotency):
    """Attack 1: Attacker replays duplicate order payload."""
    sig_id, sym, side, win = "SIG-ADV-01", "RELIANCE.NS", "BUY", "2026-09-10"
    ok1, _, _ = idempotency.reserve(sig_id, sym, side, "INT-01-A", win)
    assert ok1 is True

    # Replay
    ok2, _, rec2 = idempotency.reserve(sig_id, sym, side, "INT-01-B", win)
    assert ok2 is False
    assert rec2.order_intent_id == "INT-01-A"


# -----------------------------------------------------------------------------
# 2. Stale Tick Injection
# -----------------------------------------------------------------------------
def test_attack_02_stale_tick_injection(trade_guard):
    """Attack 2: Attacker injects stale market data."""
    res = trade_guard.evaluate(
        signal={"signal_id": "S1", "symbol": "TCS.NS", "direction": "BUY"},
        order_intent={"symbol": "TCS.NS", "action": "BUY", "quantity": 10, "price": 3800.0},
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={"price": 3800.0, "quality": "STALE"},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code == "TRADE_BLOCKED_DATA_STALE"


# -----------------------------------------------------------------------------
# 3. Extreme / Negative Price Anomaly
# -----------------------------------------------------------------------------
def test_attack_03_negative_price_injection(trade_guard):
    """Attack 3: Attacker injects negative or zero price."""
    res = trade_guard.evaluate(
        signal={"signal_id": "S1", "symbol": "INFY.NS", "direction": "BUY"},
        order_intent={"symbol": "INFY.NS", "action": "BUY", "quantity": 10, "price": -50.0},
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={"price": -50.0, "quality": "HEALTHY"},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code in ("TRADE_BLOCKED_PRICE_INVALID", "TRADE_BLOCKED_INVALID_PRICE", "TRADE_BLOCKED_DATA_ANOMALY", "TRADE_BLOCKED_NO_PRICE")


# -----------------------------------------------------------------------------
# 4. Broker Timeout Blind Retry Attack
# -----------------------------------------------------------------------------
def test_attack_04_broker_timeout_blind_retry():
    """Attack 4: Broker timeout followed by blind retry attempt."""
    order = V4Order(
        order_intent_id="INT-ADV-04",
        symbol="SBIN.NS",
        side="BUY",
        quantity=50,
        price=800.0,
        status=V4OrderStatus.INTENT_CREATED,
        lineage=OrderLineage("S4", "D4", "INT-ADV-04"),
    )
    order.transition_to(V4OrderStatus.SUBMITTED)
    order.handle_submission_timeout()
    assert order.status == V4OrderStatus.UNKNOWN

    with pytest.raises(BlindRetryProhibitedError):
        order.verify_against_blind_retry()


# -----------------------------------------------------------------------------
# 5. Ghost Position on Broker
# -----------------------------------------------------------------------------
def test_attack_05_ghost_position_reconciliation(kill_switch):
    """Attack 5: Unexpected position found on broker statement."""
    reconciler = ContinuousBrokerReconciler(kill_switch=kill_switch)
    report = reconciler.reconcile(
        nexus_orders=[],
        broker_orders=[],
        nexus_positions=[],
        broker_positions=[{"symbol": "GHOST_CO.NS", "quantity": 500, "average_price": 100.0}],
    )
    assert report.status == ReconciliationStatus.RECONCILIATION_MISMATCH
    assert report.blocks_live_trading is True
    blocked, _ = kill_switch.is_order_blocked()
    assert blocked is True


# -----------------------------------------------------------------------------
# 6. Causal Monotonicity Inversion Attack
# -----------------------------------------------------------------------------
def test_attack_06_causal_monotonicity_inversion():
    """Attack 6: Decision timestamp precedes publication timestamp (future leak)."""
    t_pub = "2026-09-10T10:00:00Z"
    t_dec = "2026-09-10T09:59:00Z"  # Inverted! Decision made before news was published!

    audit = CausalDataSafetyEngine.verify_timestamps(
        published_at=t_pub,
        ingested_at="2026-09-10T10:00:01Z",
        validated_at="2026-09-10T10:00:02Z",
        decision_at=t_dec,
        execution_at="2026-09-10T10:00:05Z",
    )
    assert audit.is_valid is False
    assert audit.status == "CAUSAL_VIOLATION"


# -----------------------------------------------------------------------------
# 7. Model Hash Tampering Attack
# -----------------------------------------------------------------------------
def test_attack_07_model_hash_tampering(trade_guard):
    """Attack 7: Altered model weights with forged hash."""
    res = trade_guard.evaluate(
        signal={
            "signal_id": "S7",
            "symbol": "TCS.NS",
            "direction": "BUY",
            "model_version": "3.5.0-FROZEN",
            "model_hash": "TAMPERED_HASH_999",
        },
        order_intent={"symbol": "TCS.NS", "action": "BUY", "quantity": 5, "price": 3800.0},
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={"price": 3800.0, "quality": "HEALTHY"},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code == "TRADE_BLOCKED_MODEL_TAMPERED"


# -----------------------------------------------------------------------------
# 8. Unapproved Model Version Bypass Attempt
# -----------------------------------------------------------------------------
def test_attack_08_unapproved_model_version(trade_guard):
    """Attack 8: Submitting trade using an unauthorized model version."""
    res = trade_guard.evaluate(
        signal={
            "signal_id": "S8",
            "symbol": "INFY.NS",
            "direction": "BUY",
            "model_version": "experimental-v4-untrained",
        },
        order_intent={"symbol": "INFY.NS", "action": "BUY", "quantity": 10, "price": 1800.0},
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={"price": 1800.0, "quality": "HEALTHY"},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code == "TRADE_BLOCKED_MODEL_UNAPPROVED"


# -----------------------------------------------------------------------------
# 9. Circuit Breaker Bypass Attempt
# -----------------------------------------------------------------------------
def test_attack_09_circuit_breaker_bypass(trade_guard):
    """Attack 9: Attempting to trade while instrument is locked in circuit band."""
    res = trade_guard.evaluate(
        signal={"signal_id": "S9", "symbol": "RELIANCE.NS", "direction": "BUY"},
        order_intent={"symbol": "RELIANCE.NS", "action": "BUY", "quantity": 10, "price": 2750.0},
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={
            "price": 2750.0,
            "quality": "HEALTHY",
            "circuit_hit": True,
            "upper_circuit": 2750.0,
        },
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code == "TRADE_BLOCKED_CIRCUIT_LIMIT"


# -----------------------------------------------------------------------------
# 10. Gap Risk Invalidation Bypass Attempt
# -----------------------------------------------------------------------------
def test_attack_10_gap_risk_invalidation(trade_guard):
    """Attack 10: Attempting to trade after catastrophic overnight adverse gap."""
    res = trade_guard.evaluate(
        signal={"signal_id": "S10", "symbol": "HDFCBANK.NS", "direction": "BUY"},
        order_intent={"symbol": "HDFCBANK.NS", "action": "BUY", "quantity": 10, "price": 1600.0},
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={
            "price": 1600.0,
            "quality": "HEALTHY",
            "gap_pct": -3.5,  # -3.5% gap down against BUY thesis
        },
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code == "TRADE_BLOCKED_GAP_RISK"


# -----------------------------------------------------------------------------
# 11. Fake Fill Price Outside Bar Range
# -----------------------------------------------------------------------------
def test_attack_11_fake_fill_price_outside_bar(trade_guard):
    """Attack 11: Slippage and execution price validation."""
    res = trade_guard.evaluate(
        signal={"signal_id": "S11", "symbol": "TCS.NS", "direction": "BUY"},
        order_intent={
            "symbol": "TCS.NS",
            "action": "BUY",
            "quantity": 10,
            "price": 3800.0,
            "limit_price": 3950.0,  # Slippage tolerance exceeded
        },
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={
            "price": 3800.0,
            "quality": "HEALTHY",
            "ask": 3950.0,  # 3.9% spread!
        },
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code in ("TRADE_BLOCKED_SPREAD", "TRADE_BLOCKED_SPREAD_TOLERANCE", "TRADE_BLOCKED_SLIPPAGE_TOLERANCE")


# -----------------------------------------------------------------------------
# 12. Unauthorized Live Escalation Attempt
# -----------------------------------------------------------------------------
def test_attack_12_unauthorized_live_escalation():
    """Attack 12: Attempting to trade in MICRO_LIVE or PRODUCTION_LIVE without signed token."""
    is_valid, msg = EnvironmentManager.validate_live_authorization(
        env=TradingEnvironment.MICRO_LIVE,
        auth_token="FORGED-TOKEN-12345",
    )
    assert is_valid is False
    assert "LIVE_TRADING_BLOCKED" in msg or "AUTHORIZATION_REJECTED" in msg


# -----------------------------------------------------------------------------
# 13. Active Kill Switch Bypass Attempt
# -----------------------------------------------------------------------------
def test_attack_13_latched_kill_switch_bypass(trade_guard, kill_switch):
    """Attack 13: Submitting order while emergency kill switch is active."""
    kill_switch.activate(
        level=KillSwitchLevel.GLOBAL,
        target="ALL",
        trigger=KillSwitchTrigger.PROVENANCE_FAILURE,
        reason="Provenance hash breach",
        policy=EmergencyPolicy.STOP_NEW_ORDERS,
        activated_by="SECURITY_AUDITOR",
    )

    res = trade_guard.evaluate(
        signal={"signal_id": "S13", "symbol": "RELIANCE.NS", "direction": "BUY"},
        order_intent={"symbol": "RELIANCE.NS", "action": "BUY", "quantity": 10, "price": 2500.0},
        portfolio={"cash": 1000000.0, "margin_available": 1000000.0},
        market_data={"price": 2500.0, "quality": "HEALTHY"},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code == "TRADE_BLOCKED_KILL_SWITCH"


# -----------------------------------------------------------------------------
# 14. Capital Sizing Manipulation Attempt
# -----------------------------------------------------------------------------
def test_attack_14_capital_oversizing(trade_guard):
    """Attack 14: Sizing exceeds single instrument capital cap (10%)."""
    res = trade_guard.evaluate(
        signal={"signal_id": "S14", "symbol": "INFY.NS", "direction": "BUY"},
        order_intent={
            "symbol": "INFY.NS",
            "action": "BUY",
            "quantity": 2000,
            "price": 1800.0,  # 2000 * 1800 = ₹36,00,000 (exceeds 10% of 20L = 2L cap)
        },
        portfolio={
            "current_capital": 2000000.0,
            "cash": 2000000.0,
            "margin_available": 2000000.0,
            "total_exposure": 0.0,
        },
        market_data={"price": 1800.0, "quality": "HEALTHY"},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.rejection_code in ("TRADE_BLOCKED_INSTRUMENT_EXPOSURE", "TRADE_BLOCKED_PORTFOLIO_EXPOSURE")


# -----------------------------------------------------------------------------
# 15. Auto-Retrain Attempt on Live Drift
# -----------------------------------------------------------------------------
def test_attack_15_prohibition_of_live_auto_retraining():
    """Attack 15: Invariant check ensuring live drift never triggers automated retraining."""
    assert ModelDriftMonitor.auto_retraining_allowed is False
