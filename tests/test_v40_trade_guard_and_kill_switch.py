"""
NEXUS V4.0 — TradeGuard 34 Gates & Independent Kill Switch Test Suite
Tests all 34 pre-execution risk gates, independent kill switch triggers, latching emergency states,
cryptographic reset tokens, and strict environment isolation.
"""

import pytest
import sqlite3
import os
from datetime import datetime, timezone

from event_agent.execution.trade_guard import (
    TradeGuard,
    TradeGuardResult,
    TradeGuardVerdict,
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


@pytest.fixture
def kill_switch(tmp_path):
    # Reset singleton instance for test isolation
    IndependentKillSwitch._instance = None
    db_file = str(tmp_path / "test_kill_switch.db")
    ks = IndependentKillSwitch(db_path=db_file)
    return ks


@pytest.fixture
def trade_guard(kill_switch):
    tg = TradeGuard(kill_switch=kill_switch)
    return tg


def test_trade_guard_passes_when_all_conditions_healthy(trade_guard):
    """Verify TradeGuard returns ALL_REQUIRED_GATES_PASS on clean payload."""
    now_iso = datetime.now(timezone.utc).isoformat()
    signal = {
        "signal_id": "SIG-TEST-001",
        "symbol": "RELIANCE.NS",
        "direction": "BUY",
        "strategy": "CHAKRA",
        "timestamp": now_iso,
        "max_age_minutes": 60.0,
        "model_version": "3.5.0-FROZEN",
        "model_hash": "c5f2b87e2f5b89a80e1c667a421fbc38",
        "allocation_amount": 25000.0,
        "confidence": 0.85,
    }
    order_intent = {
        "order_intent_id": "INT-TEST-001",
        "symbol": "RELIANCE.NS",
        "action": "BUY",
        "quantity": 10,
        "price": 2500.0,
        "order_type": "LIMIT",
        "limit_price": 2505.0,
        "strategy": "CHAKRA",
        "timestamp": now_iso,
    }
    portfolio = {
        "cash": 10000000.0,
        "margin_available": 10000000.0,
        "total_capital": 10000000.0,
    }
    market_data = {
        "price": 2500.0,
        "bid": 2499.0,
        "ask": 2501.0,
        "volume": 500000,
        "avg_volume": 400000,
        "lower_circuit": 2250.0,
        "upper_circuit": 2750.0,
        "circuit_hit": False,
        "market_open": True,
        "simulate_open_session": True,
        "vix": 14.5,
        "quality": "HEALTHY",
        "gap_pct": 0.2,
    }
    active_positions = []

    result = trade_guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio=portfolio,
        market_data=market_data,
        active_positions=active_positions,
        environment=TradingEnvironment.PAPER,
    )

    assert result.verdict == TradeGuardVerdict.ALL_REQUIRED_GATES_PASS
    assert result.is_approved is True
    assert result.rejection_code is None
    assert len(result.passed_gates) >= 34


def test_trade_guard_fails_closed_on_stale_data(trade_guard):
    """Verify Gate blocks trades when market data freshness is STALE or DATA_UNAVAILABLE."""
    now_iso = datetime.now(timezone.utc).isoformat()
    signal = {
        "signal_id": "SIG-TEST-002",
        "symbol": "TCS.NS",
        "direction": "BUY",
        "timestamp": now_iso,
    }
    order_intent = {
        "symbol": "TCS.NS",
        "action": "BUY",
        "quantity": 5,
        "price": 3800.0,
    }
    portfolio = {"cash": 1000000.0, "margin_available": 1000000.0}
    market_data = {
        "price": 3800.0,
        "quality": "DATA_UNAVAILABLE",
    }
    active_positions = []

    result = trade_guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio=portfolio,
        market_data=market_data,
        active_positions=active_positions,
        environment=TradingEnvironment.PAPER,
    )

    assert result.verdict == TradeGuardVerdict.NO_TRADE
    assert result.is_approved is False
    assert result.rejection_code == "TRADE_BLOCKED_DATA_STALE"


def test_trade_guard_fails_closed_on_unapproved_model(trade_guard):
    """Verify Gate blocks trades when model version is not frozen/approved."""
    now_iso = datetime.now(timezone.utc).isoformat()
    signal = {
        "signal_id": "SIG-TEST-003",
        "symbol": "INFY.NS",
        "direction": "BUY",
        "timestamp": now_iso,
        "model_version": "9.9.9-UNAPPROVED-LIVE",
    }
    order_intent = {
        "symbol": "INFY.NS",
        "action": "BUY",
        "quantity": 10,
        "price": 1800.0,
    }
    portfolio = {"cash": 1000000.0, "margin_available": 1000000.0}
    market_data = {"price": 1800.0, "quality": "HEALTHY"}

    result = trade_guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio=portfolio,
        market_data=market_data,
        active_positions=[],
        environment=TradingEnvironment.PAPER,
    )

    assert result.verdict == TradeGuardVerdict.NO_TRADE
    assert result.is_approved is False
    assert result.rejection_code == "TRADE_BLOCKED_MODEL_UNAPPROVED"


def test_trade_guard_blocks_when_kill_switch_active(trade_guard, kill_switch):
    """Verify Gate blocks trades immediately when Kill Switch is latched."""
    kill_switch.activate(
        level=KillSwitchLevel.GLOBAL,
        trigger=KillSwitchTrigger.PROVENANCE_FAILURE,
        reason="Model hash mismatch detected",
        target="ALL",
        policy=EmergencyPolicy.STOP_NEW_ORDERS,
        activated_by="AUTOMATED_AUDITOR",
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    signal = {
        "signal_id": "SIG-TEST-004",
        "symbol": "RELIANCE.NS",
        "direction": "BUY",
        "timestamp": now_iso,
    }
    order_intent = {
        "symbol": "RELIANCE.NS",
        "action": "BUY",
        "quantity": 10,
        "price": 2500.0,
    }
    portfolio = {"cash": 1000000.0, "margin_available": 1000000.0}
    market_data = {"price": 2500.0, "quality": "HEALTHY"}

    result = trade_guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio=portfolio,
        market_data=market_data,
        active_positions=[],
        environment=TradingEnvironment.PAPER,
    )

    assert result.verdict == TradeGuardVerdict.NO_TRADE
    assert result.is_approved is False
    assert result.rejection_code == "TRADE_BLOCKED_KILL_SWITCH"


def test_kill_switch_scopes_and_triggers(kill_switch):
    """Verify Kill Switch activates across scopes and blocks trading accordingly."""
    # 1. Strategy scope
    act1 = kill_switch.activate(
        level=KillSwitchLevel.STRATEGY,
        target="CHAKRA",
        trigger=KillSwitchTrigger.DAILY_DRAWDOWN_BREACH,
        reason="Strategy hit 5% intraday DD",
        policy=EmergencyPolicy.STOP_NEW_ORDERS,
        activated_by="RISK_ENGINE",
    )
    assert act1.is_active is True
    blocked, _ = kill_switch.is_order_blocked(strategy="CHAKRA", symbol="RELIANCE.NS")
    assert blocked is True

    # Other strategies remain unblocked
    blocked_shakti, _ = kill_switch.is_order_blocked(strategy="SHAKTI", symbol="RELIANCE.NS")
    assert blocked_shakti is False

    # 2. Instrument scope
    kill_switch.activate(
        level=KillSwitchLevel.INSTRUMENT,
        target="SBIN.NS",
        trigger=KillSwitchTrigger.ABNORMAL_VOLATILITY,
        reason="Circuit limit volatility",
        policy=EmergencyPolicy.STOP_NEW_ORDERS,
        activated_by="NSE_FEED_MONITOR",
    )
    blocked_sbin, _ = kill_switch.is_order_blocked(strategy="SHAKTI", symbol="SBIN.NS")
    assert blocked_sbin is True

    blocked_tcs, _ = kill_switch.is_order_blocked(strategy="SHAKTI", symbol="TCS.NS")
    assert blocked_tcs is False

    # 3. Global scope overrides everything
    kill_switch.activate(
        level=KillSwitchLevel.GLOBAL,
        target="ALL",
        trigger=KillSwitchTrigger.RECONCILIATION_MISMATCH,
        reason="Broker position discrepancy",
        policy=EmergencyPolicy.STOP_NEW_ORDERS,
        activated_by="RECONCILER",
    )
    blocked_global, _ = kill_switch.is_order_blocked(strategy="SHAKTI", symbol="TCS.NS")
    assert blocked_global is True


def test_kill_switch_requires_operator_token_to_clear(kill_switch):
    """Verify Kill Switch cannot be cleared without valid operator credentials."""
    act = kill_switch.activate(
        level=KillSwitchLevel.GLOBAL,
        target="ALL",
        trigger=KillSwitchTrigger.MANUAL_OPERATOR,
        reason="Emergency halt drill",
        policy=EmergencyPolicy.STOP_NEW_ORDERS,
        activated_by="CHIEF_RISK_OFFICER",
    )
    act_id = act.activation_id

    # Fails with empty token
    cleared, _ = kill_switch.clear(act_id, cleared_by="OPERATOR", authorization_token="")
    assert cleared is False
    blocked, _ = kill_switch.is_order_blocked(strategy="SHAKTI", symbol="INFY.NS")
    assert blocked is True

    # Succeeds with authorized operator token
    cleared, _ = kill_switch.clear(
        act_id,
        cleared_by="SENIOR_RISK_OFFICER",
        authorization_token="V4-RESET-SENIOR-KEY-2026",
    )
    assert cleared is True
    blocked, _ = kill_switch.is_order_blocked(strategy="SHAKTI", symbol="INFY.NS")
    assert blocked is False


def test_environment_manager_5_tiers_and_isolation():
    """Verify EnvironmentManager enforces 5 environments and limits."""
    assert len(TradingEnvironment) == 5

    # Check capital caps
    assert TradingEnvironment.PAPER.max_capital_cap == 10000000.0
    assert TradingEnvironment.SHADOW.max_capital_cap == 0.0
    assert TradingEnvironment.MICRO_LIVE.max_capital_cap == 25000.0
    assert TradingEnvironment.CONTROLLED_LIVE.max_capital_cap == 200000.0
    assert TradingEnvironment.PRODUCTION_LIVE.max_capital_cap == 1000000.0

    # Fingerprint verification
    fp = EnvironmentManager.compute_environment_fingerprint(TradingEnvironment.PAPER)
    assert isinstance(fp, str)
    assert len(fp) == 64

    # Verify authorization validation
    is_valid, _ = EnvironmentManager.validate_live_authorization(
        env=TradingEnvironment.MICRO_LIVE,
        auth_token=None,
    )
    assert is_valid is False

    valid_token = EnvironmentManager.generate_live_authorization_token(
        target_env=TradingEnvironment.MICRO_LIVE,
        operator_id="CHIEF_RISK_OFFICER",
        human_approval_ref="APPR-REF-2026-09-01",
    )
    is_valid, _ = EnvironmentManager.validate_live_authorization(
        env=TradingEnvironment.MICRO_LIVE,
        auth_token=valid_token,
    )
    assert is_valid is True


def test_trade_guard_blocks_stale_base_price(trade_guard):
    """Verify TradeGuard Gate 3 strictly blocks orders with stale base price timestamp."""
    now_iso = datetime.now(timezone.utc).isoformat()
    signal = {
        "signal_id": "SIG-TEST-STALE-BP",
        "symbol": "APOLLOHOSP.NS",
        "direction": "BUY",
        "strategy": "ALPHA",
        "timestamp": now_iso,
        "max_age_minutes": 60.0,
        "model_version": "3.5.0-FROZEN",
        "model_hash": "c5f2b87e2f5b89a80e1c667a421fbc38",
        "allocation_amount": 25000.0,
        "confidence": 0.85,
    }
    order_intent = {
        "order_intent_id": "INT-TEST-002",
        "symbol": "APOLLOHOSP.NS",
        "action": "BUY",
        "quantity": 10,
        "price": 8769.0,
        "order_type": "LIMIT",
        "strategy": "ALPHA",
        "timestamp": now_iso,
        "decision_timestamp": "2026-09-23T09:30:00+00:00",
    }
    portfolio = {
        "cash": 10000000.0,
        "margin_available": 10000000.0,
        "total_capital": 10000000.0,
    }
    # Market data has base_price from 09:10:00 (age 20m > max 5m)
    market_data = {
        "price": 8769.0,
        "base_price_timestamp": "2026-09-23T09:10:00+00:00",
        "max_price_age_seconds": 300.0,
        "bid": 8765.0,
        "ask": 8770.0,
        "volume": 50000,
        "avg_volume": 40000,
        "lower_circuit": 8000.0,
        "upper_circuit": 9500.0,
        "circuit_hit": False,
        "market_open": True,
        "simulate_open_session": True,
        "vix": 14.5,
        "quality": "HEALTHY",
        "gap_pct": 0.2,
    }

    result = trade_guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio=portfolio,
        market_data=market_data,
        active_positions=[],
        environment=TradingEnvironment.PAPER,
    )

    assert result.verdict == TradeGuardVerdict.NO_TRADE
    assert result.is_approved is False
    assert result.rejection_code == "STALE_BASE_PRICE"
    assert "exceeds allowable freshness window" in result.rejection_message
    assert "GATE_03_DATA_FRESHNESS" in result.failed_gates

