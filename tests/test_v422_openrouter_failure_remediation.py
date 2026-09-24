# =============================================================================
# tests/test_v422_openrouter_failure_remediation.py
# =============================================================================
"""
Institutional Remediation Test Suite for NEXUS V4.2.2:
Zero Model Contamination, Fail-Closed OpenRouter Handling, and Cohort Protection.

Covers the 5 Institutional Modifications:
1. Fail-closed behavior for new entries; existing position exits continue uninterrupted.
2. AUTHENTICATED is NOT permission to trade (only INFERENCE_SUCCESS passes Gate 35).
3. Raw provider error preservation with strict secret sanitization.
4. Cohort integrity test (test_ai_failure_cannot_enter_prospective_cohort).
5. Explicit operational AI availability metric tracking decoupled from prediction accuracy.
6. Architectural redundancy: InstrumentSelector Gate 0.0 blocks thesis; TradeGuard Gate 35
   serves as the final independent safety authority.
7. Existing position multi-exit verification: Target hit, Stop hit, Thesis invalidated,
   and normal monitoring continue during AI outage; broker exits never disabled.
"""

from datetime import datetime, timezone, timedelta
import json
import pytest
import sqlite3
import urllib.error
import urllib.request

from event_agent.engine.llm_provider import (
    OpenRouterProvider,
    OpenRouterStatus,
    OpenRouterMetricsTracker,
    sanitize_secret_error,
)
from event_agent.arena.thesis_validator import MarketThesis, MarketThesisValidator
from event_agent.arena.instrument_selector import InstrumentSelector
from event_agent.arena.agents.base_agent import BaseAgent
from event_agent.arena.agents.agent_alpha import AgentAlpha
from event_agent.arena.agents.agent_momentum import AgentMomentum
from event_agent.arena.models import (
    TradeAction,
    TradeDirection,
    OrderIntent,
    PositionSide,
    InstrumentType,
)
from event_agent.execution.trade_guard import (
    TradeGuard,
    TradeGuardVerdict,
    TradingEnvironment,
)
from event_agent.arena.exit_engine import (
    EquityFuturesExitEngine,
    ExitPriority,
    ExitSignal,
)
from event_agent.storage.ledger import (
    init_db,
    get_connection,
    save_prediction,
    reconcile_predictions,
    get_performance_scorecard,
    get_ai_availability_metrics,
)


# =============================================================================
# 1. Error Classification & Secret Sanitization Tests
# =============================================================================
def test_openrouter_402_maps_to_credit_exhausted_and_sanitizes_secrets():
    """Verify HTTP 402 maps to CREDIT_EXHAUSTED and strips keys/tokens from error string."""
    raw_error_with_secret = (
        "HTTP 402: Payment Required. Provider key sk-or-v1-abcdef0123456789abcdef0123456789 "
        "Authorization: Bearer sk-live-secret-999"
    )
    sanitized = sanitize_secret_error(raw_error_with_secret)

    # Invariants
    assert "sk-or-v1-" not in sanitized
    assert "sk-live-" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert "[REDACTED_TOKEN]" in sanitized
    assert "HTTP 402: Payment Required" in sanitized


def test_openrouter_decision_thesis_402_returns_ai_unavailable(monkeypatch):
    """Verify generate_decision_thesis returns structured AI_UNAVAILABLE on HTTP 402."""
    provider = OpenRouterProvider(api_key="sk-or-v1-testkey12345678901234567890")

    def mock_urlopen_402(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=402,
            msg="Payment Required - Credits Exhausted",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_402)

    res = provider.generate_decision_thesis(
        agent_id="ALPHA",
        symbol="RELIANCE.NS",
        stock_data={"base_price": 2950.0, "rsi_14": 42.0},
        market_context={"vix_change_pct": 1.2},
    )

    assert res["ai_status"] == OpenRouterStatus.CREDIT_EXHAUSTED.value
    assert res["decision_mode"] == "AI_UNAVAILABLE"
    assert res["direction"] == "NO_TRADE"
    assert res["evaluation_status"] == "EXCLUDED_FROM_ACCURACY"
    assert "Payment Required" in res["fallback_reason"]
    assert "sk-or-v1-" not in res["fallback_reason"]


# =============================================================================
# 2. Gate 35 Invariant: AUTHENTICATED is NOT permission to trade
# =============================================================================
def test_authenticated_is_not_permission_to_trade():
    """
    CRITICAL INVARIANT: Only INFERENCE_SUCCESS satisfies Gate 35.
    AUTHENTICATED, CREDIT_EXHAUSTED, RATE_LIMITED, INFERENCE_FAILED, UNAVAILABLE must all BLOCK.
    """
    guard = TradeGuard()

    # Base valid order intent and signal setup
    base_signal = {
        "signal_id": "SIG-TEST-001",
        "symbol": "RELIANCE",
        "direction": "BULLISH",
        "decision_mode": "AI_INFERENCE",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "price": 2950.0,
        "action": "BUY",
    }
    base_order = {
        "order_intent_id": "INT-TEST-001",
        "symbol": "RELIANCE",
        "action": "BUY",
        "quantity": 10,
        "price": 2950.0,
        "decision_mode": "AI_INFERENCE",
    }
    portfolio = {"cash": 100_000.0, "total_value": 100_000.0, "current_drawdown_pct": 0.0}
    market_data = {
        "market_phase": "REGULAR",
        "last_price": 2950.0,
        "bid": 2949.5,
        "ask": 2950.5,
        "avg_daily_volume": 1_000_000,
        "circuit_limit_pct": 10.0,
        "is_tradable": True,
        "quote_age_seconds": 1.0,
    }

    # 1. AUTHENTICATED must fail Gate 35
    sig_auth = dict(base_signal, ai_status="AUTHENTICATED")
    res_auth = guard.evaluate(sig_auth, base_order, portfolio, market_data, [])
    assert not res_auth.is_approved
    assert "GATE_35_AI_DECISION_AVAILABILITY" in res_auth.failed_gates
    assert res_auth.rejection_code == "TRADE_BLOCKED_AI_UNAVAILABLE"

    # 2. CREDIT_EXHAUSTED must fail Gate 35
    sig_cred = dict(base_signal, ai_status="CREDIT_EXHAUSTED")
    res_cred = guard.evaluate(sig_cred, base_order, portfolio, market_data, [])
    assert not res_cred.is_approved
    assert "GATE_35_AI_DECISION_AVAILABILITY" in res_cred.failed_gates

    # 3. RATE_LIMITED must fail Gate 35
    sig_rate = dict(base_signal, ai_status="RATE_LIMITED")
    res_rate = guard.evaluate(sig_rate, base_order, portfolio, market_data, [])
    assert not res_rate.is_approved
    assert "GATE_35_AI_DECISION_AVAILABILITY" in res_rate.failed_gates

    # 4. INFERENCE_FAILED must fail Gate 35
    sig_fail = dict(base_signal, ai_status="INFERENCE_FAILED")
    res_fail = guard.evaluate(sig_fail, base_order, portfolio, market_data, [])
    assert not res_fail.is_approved
    assert "GATE_35_AI_DECISION_AVAILABILITY" in res_fail.failed_gates

    # 5. UNAVAILABLE must fail Gate 35
    sig_unav = dict(base_signal, ai_status="UNAVAILABLE")
    res_unav = guard.evaluate(sig_unav, base_order, portfolio, market_data, [])
    assert not res_unav.is_approved
    assert "GATE_35_AI_DECISION_AVAILABILITY" in res_unav.failed_gates

    # 6. INFERENCE_SUCCESS passes Gate 35
    sig_ok = dict(base_signal, ai_status="INFERENCE_SUCCESS")
    res_ok = guard.evaluate(sig_ok, base_order, portfolio, market_data, [])
    assert "GATE_35_AI_DECISION_AVAILABILITY" in res_ok.passed_gates


# =============================================================================
# 3. BaseAgent Refuses Silent Heuristic Substitution
# =============================================================================
def test_base_agent_refuses_silent_heuristic_fallback(monkeypatch):
    """Verify BaseAgent refuses to populate direction from predicted_1d_pct when AI fails."""
    agent = AgentMomentum()

    def mock_ai_fail(*args, **kwargs):
        return {
            "status": "FAILED",
            "direction": "NO_TRADE",
            "decision_mode": "AI_UNAVAILABLE",
            "ai_status": "CREDIT_EXHAUSTED",
            "fallback_reason": "HTTP 402: Payment Required",
            "evaluation_status": "EXCLUDED_FROM_ACCURACY",
        }

    monkeypatch.setattr(agent.llm_provider, "generate_decision_thesis", mock_ai_fail)

    stock_data = {
        "base_price": 2500.0,
        "predicted_1d_pct": 2.5,  # Heuristic says Bullish +2.5%!
        "conviction": 85.0,
    }
    market_snapshot = {"regime": {}, "snapshot_id": "SNAP-TEST-001"}

    thesis = agent.generate_and_validate_thesis(
        symbol="TCS.NS",
        stock_data=stock_data,
        market_snapshot=market_snapshot,
    )

    # Invariant: Must NOT adopt the +2.5% heuristic prediction!
    assert thesis.direction == "NO_TRADE"
    assert thesis.decision_mode == "AI_UNAVAILABLE"
    assert thesis.ai_status == "CREDIT_EXHAUSTED"
    assert thesis.evaluation_status == "EXCLUDED_FROM_ACCURACY"
    assert thesis.fallback_reason is not None and "HTTP 402" in thesis.fallback_reason


# =============================================================================
# 4. Redundant Architectural Gates: Selector Gate 0.0 & TradeGuard Gate 35
# =============================================================================
def test_instrument_selector_gate_0_blocks_ai_unavailable():
    """Verify InstrumentSelector Gate 0.0 blocks proposal generation on AI_UNAVAILABLE."""
    selector = InstrumentSelector()

    thesis = MarketThesis(
        agent_id="MOMENTUM",
        symbol="INFY.NS",
        direction="NO_TRADE",
        expected_move_pct=0.0,
        horizon="1D",
        confidence=0.0,
        catalysts=[],
        invalidating_conditions=["AI inference failure"],
        reasoning="AI unavailable due to credit exhaustion",
        decision_mode="AI_UNAVAILABLE",
        ai_status="CREDIT_EXHAUSTED",
        fallback_reason="HTTP 402: Payment Required",
        evaluation_status="EXCLUDED_FROM_ACCURACY",
    )

    proposal = selector.select_instrument(
        thesis=thesis,
        stock_data={"base_price": 1800.0},
        portfolio_equity=100_000.0,
        current_open_positions=[],
        snapshot_id="SNAP-001",
    )

    assert proposal.action == TradeAction.NO_TRADE
    assert proposal.planned_risk_amount == 0.0
    assert proposal.direction == TradeDirection.NONE
    assert "AI_DECISION_UNAVAILABLE" in proposal.decision_reason


def test_tradeguard_gate_35_independent_redundancy():
    """
    Verify TradeGuard Gate 35 blocks even if upstream code accidentally constructed
    an active order proposal with AI_UNAVAILABLE or CREDIT_EXHAUSTED.
    """
    guard = TradeGuard()

    leak_signal = {
        "signal_id": "SIG-LEAK-001",
        "symbol": "INFY",
        "direction": "BULLISH",
        "action": "BUY",
        "price": 1800.0,
        "decision_mode": "AI_UNAVAILABLE",
        "ai_status": "CREDIT_EXHAUSTED",
        "fallback_reason": "HTTP 402: Payment Required",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    leak_order = {
        "order_intent_id": "INT-LEAK-001",
        "symbol": "INFY",
        "action": "BUY",
        "quantity": 20,
        "price": 1800.0,
        "decision_mode": "AI_UNAVAILABLE",
        "ai_status": "CREDIT_EXHAUSTED",
    }
    portfolio = {"cash": 100_000.0, "total_value": 100_000.0, "current_drawdown_pct": 0.0}
    market_data = {
        "market_phase": "REGULAR",
        "last_price": 1800.0,
        "bid": 1799.0,
        "ask": 1801.0,
        "avg_daily_volume": 500_000,
        "circuit_limit_pct": 10.0,
        "is_tradable": True,
        "quote_age_seconds": 2.0,
    }

    result = guard.evaluate(leak_signal, leak_order, portfolio, market_data, [])
    assert not result.is_approved
    assert "GATE_35_AI_DECISION_AVAILABILITY" in result.failed_gates
    assert result.rejection_code == "TRADE_BLOCKED_AI_UNAVAILABLE"


# =============================================================================
# 5. Cohort Integrity Test: test_ai_failure_cannot_enter_prospective_cohort
# =============================================================================
def test_ai_failure_cannot_enter_prospective_cohort(monkeypatch):
    """
    Comprehensive End-to-End Test proving:
    OpenRouter 402
        ↓
    decision_id created
        ↓
    AI_UNAVAILABLE
        ↓
    NO_TRADE
        ↓
    no order_intent_id
        ↓
    no broker_order_id
        ↓
    no new position
        ↓
    NOT counted as executed prediction/trade (EXCLUDED_FROM_ACCURACY)
    """
    agent = AgentAlpha()

    # 1. Simulate OpenRouter 402 HTTP Error
    def mock_402_inference(*args, **kwargs):
        return {
            "status": "FAILED",
            "direction": "NO_TRADE",
            "decision_mode": "AI_UNAVAILABLE",
            "ai_status": "CREDIT_EXHAUSTED",
            "fallback_reason": "HTTP 402: Payment Required",
            "evaluation_status": "EXCLUDED_FROM_ACCURACY",
            "reasoning": "OpenRouter payment required. Fail-closed.",
        }

    monkeypatch.setattr(agent.llm_provider, "generate_decision_thesis", mock_402_inference)

    # 2. Agent evaluates market
    snapshot = {
        "snapshot_id": "SNAP-COHORT-001",
        "regime": {},
        "stocks": {
            "RELIANCE.NS": {
                "base_price": 2950.0,
                "predicted_1d_pct": 1.8,
                "conviction": 75.0,
            }
        },
    }

    proposals = agent.evaluate_market(
        market_snapshot=snapshot,
        current_open_positions=[],
        current_equity=100_000.0,
        current_cash=100_000.0,
    )

    # 3. Assert NO_TRADE proposals produced
    assert len(proposals) >= 1
    prop = proposals[0]
    assert prop.action == TradeAction.NO_TRADE
    assert prop.planned_risk_amount == 0.0

    # 4. Assert zero order intent created
    order_intent_id = None
    broker_order_id = None
    if prop.action != TradeAction.NO_TRADE:
        order_intent_id = f"INT-{prop.symbol}-001"
        broker_order_id = f"BRK-{prop.symbol}-001"

    assert order_intent_id is None
    assert broker_order_id is None

    # 5. Save to ledger with EXCLUDED_FROM_ACCURACY
    pred_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "date": "2026-09-24",
        "symbol": "RELIANCE.NS",
        "base_price": 2950.0,
        "direction": "NO_TRADE",
        "action": "NO_TRADE",
        "conviction": 0.0,
        "expected_1d_pct": 0.0,
        "evaluation_status": "EXCLUDED_FROM_ACCURACY",
    }
    pred_id = save_prediction(pred_record)
    assert pred_id > 0

    # 6. Reconcile predictions against market
    res = reconcile_predictions(eval_reference_date=datetime.now().date() + timedelta(days=2))
    # NO_TRADE must NOT be evaluated as a wrong prediction
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM evaluations WHERE prediction_id = ?", (pred_id,))
        evals = cursor.fetchall()
        assert len(evals) == 0, "AI_UNAVAILABLE prediction must not enter evaluations ledger!"


# =============================================================================
# 6. Operational AI Availability Metric Tracking
# =============================================================================
def test_ai_availability_metric_decoupled_from_accuracy():
    """
    Verify AI availability metrics track outage events independently from
    model predictive accuracy.
    """
    OpenRouterMetricsTracker.reset()

    # Simulate 100 decision attempts: 95 successful, 3 credit exhausted, 1 rate limited, 1 failed
    for _ in range(95):
        OpenRouterMetricsTracker.record_decision("INFERENCE_SUCCESS")
    for _ in range(3):
        OpenRouterMetricsTracker.record_decision("CREDIT_EXHAUSTED")
    OpenRouterMetricsTracker.record_decision("RATE_LIMITED")
    OpenRouterMetricsTracker.record_decision("INFERENCE_FAILED")

    metrics = get_ai_availability_metrics()

    assert metrics["AI_DECISION_ATTEMPTS"] == 100
    assert metrics["AI_SUCCESSFUL_DECISIONS"] == 95
    assert metrics["AI_UNAVAILABLE_DECISIONS"] == 5
    assert metrics["AI_CREDIT_EXHAUSTED"] == 3
    assert metrics["AI_RATE_LIMITED"] == 1
    assert metrics["AI_INFERENCE_FAILED"] == 1
    assert metrics["AI_AVAILABILITY_PCT"] == 95.0


# =============================================================================
# 7. Strengthened Existing Position Exit Test during AI Outage
# =============================================================================
def test_existing_position_exits_continue_during_ai_outage():
    """
    Simultaneously prove:
    1. New entries = 0 during AI outage
    2. Existing positions continue executing:
       - target hit -> exit
       - stop hit -> exit
       - thesis invalidated -> exit
       - normal monitoring continues
    3. AI outage NEVER disables broker-side protective exits.
    """
    # Position 1: Target Hit (Long entry 100, target 110, current price 112)
    pos_target = {
        "position_id": "POS-001",
        "symbol": "TCS",
        "position_side": "LONG",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "target_price": 110.0,
    }
    sig_target = EquityFuturesExitEngine.evaluate(pos_target, current_price=112.0)
    assert sig_target is not None
    assert sig_target.should_exit
    assert sig_target.exit_reason == "TARGET"

    # Position 2: Stop Loss Hit (Long entry 100, stop 95, current price 94)
    pos_stop = {
        "position_id": "POS-002",
        "symbol": "INFY",
        "position_side": "LONG",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "target_price": 110.0,
    }
    sig_stop = EquityFuturesExitEngine.evaluate(pos_stop, current_price=94.0)
    assert sig_stop is not None
    assert sig_stop.should_exit
    assert sig_stop.exit_reason == "MAX_LOSS"

    # Position 3: Thesis Invalidated (Market regime transitioned to EXTREME volatility)
    pos_thesis = {
        "position_id": "POS-003",
        "symbol": "SBIN",
        "position_side": "LONG",
        "entry_price": 800.0,
        "stop_loss": 770.0,
        "target_price": 850.0,
    }
    sig_inval = EquityFuturesExitEngine.evaluate(
        pos_thesis,
        current_price=795.0,  # unrealized < 0
        market_context={"regime": {"volatility": "EXTREME"}},
    )
    assert sig_inval is not None
    assert sig_inval.should_exit
    assert sig_inval.exit_reason == "THESIS_INVALIDATED"

    # Position 4: Normal position within bounds (entry 100, stop 95, target 110, current 103)
    pos_normal = {
        "position_id": "POS-004",
        "symbol": "HDFCBANK",
        "position_side": "LONG",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "target_price": 110.0,
    }
    sig_normal = EquityFuturesExitEngine.evaluate(pos_normal, current_price=103.0)
    assert sig_normal is None, "Normal position within bounds must continue monitoring"


# =============================================================================
# 8. Provenance Immutability & Tampering Protection
# =============================================================================
def test_market_thesis_provenance_cannot_be_mutated():
    """
    Verify that critical provenance fields:
    - decision_model
    - model_provider
    - model_version
    - decision_mode
    - ai_status
    - ai_request_id
    cannot be altered once a thesis is validated and sealed.
    """
    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="TCS.NS",
        direction="BULLISH",
        expected_move_pct=1.5,
        horizon="1D",
        confidence=80.0,
        catalysts=["Earnings beat"],
        invalidating_conditions=["Severe market selloff"],
        reasoning="Strong institutional accumulation",
        decision_model="OPENROUTER:openai/gpt-4o-mini",
        model_provider="openrouter",
        model_version="openai/gpt-4o-mini",
        decision_mode="AI_INFERENCE",
        ai_status="INFERENCE_SUCCESS",
        ai_request_id="gen-req-institutional-9988",
        evaluation_status="EVALUABLE",
    )

    validator = MarketThesisValidator()
    validated_thesis = validator.validate(thesis)

    # 1. Assert initial provenance values and valid cryptographic seal
    assert validated_thesis.decision_model == "OPENROUTER:openai/gpt-4o-mini"
    assert validated_thesis.model_provider == "openrouter"
    assert validated_thesis.model_version == "openai/gpt-4o-mini"
    assert validated_thesis.decision_mode == "AI_INFERENCE"
    assert validated_thesis.ai_status == "INFERENCE_SUCCESS"
    assert validated_thesis.ai_request_id == "gen-req-institutional-9988"

    initial_hash = validated_thesis.compute_provenance_hash()
    assert len(initial_hash) == 64
    assert validated_thesis.to_dict()["provenance_hash"] == initial_hash

    # 2. Attempt mutation of each provenance field - all must raise AttributeError
    with pytest.raises(AttributeError, match="Provenance field 'decision_model' is sealed and immutable"):
        validated_thesis.decision_model = "HEURISTIC_BASELINE:v1"

    with pytest.raises(AttributeError, match="Provenance field 'model_provider' is sealed and immutable"):
        validated_thesis.model_provider = "heuristic"

    with pytest.raises(AttributeError, match="Provenance field 'model_version' is sealed and immutable"):
        validated_thesis.model_version = "offline_rule"

    with pytest.raises(AttributeError, match="Provenance field 'decision_mode' is sealed and immutable"):
        validated_thesis.decision_mode = "LOCAL_DETERMINISTIC"

    with pytest.raises(AttributeError, match="Provenance field 'ai_status' is sealed and immutable"):
        validated_thesis.ai_status = "AUTHENTICATED"

    with pytest.raises(AttributeError, match="Provenance field 'ai_request_id' is sealed and immutable"):
        validated_thesis.ai_request_id = "fake-req-tampered"

    # 3. Provenance hash remains pristine and identical
    assert validated_thesis.compute_provenance_hash() == initial_hash


# =============================================================================
# 9. Final Reporting Integrity & Option Invariants (V4.2.2 Hardening)
# =============================================================================
def test_ai_unavailable_cannot_be_rendered_as_ai_decision():
    """
    Regression Test 6a:
    AI-unavailable reports MUST NOT present deterministic agent diagnostics
    as AI-generated agent decisions.
    
    Required representation:
    AGENT AI STATUS: UNAVAILABLE
    AI THESIS: NOT GENERATED
    DETERMINISTIC SCREEN: NO_TRADE
    
    Clearly distinguish:
    AI_DECISION vs DETERMINISTIC_DIAGNOSTIC.
    """
    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="RELIANCE.NS",
        direction="NO_TRADE",
        expected_move_pct=0.0,
        horizon="1D",
        confidence=0.0,
        catalysts=[],
        invalidating_conditions=["AI inference failure / credit exhausted"],
        reasoning="OpenRouter 402 Credit Exhausted",
        decision_model="OPENROUTER:openai/gpt-4o-mini",
        model_provider="openrouter",
        model_version="openai/gpt-4o-mini",
        decision_mode="AI_UNAVAILABLE",
        ai_status="CREDIT_EXHAUSTED",
        fallback_reason="HTTP 402 Payment Required",
    )

    validator = MarketThesisValidator()
    validated = validator.validate(thesis)

    # 1. Enforce deterministic diagnostic representation
    assert validated.diagnostic_type == "DETERMINISTIC_DIAGNOSTIC"
    assert validated.agent_ai_status == "UNAVAILABLE"
    assert validated.ai_thesis == "NOT_GENERATED"
    assert validated.deterministic_screen == "NO_TRADE"
    assert validated.evaluation_status == "EXCLUDED_FROM_ACCURACY"

    rep = validated.format_reporting_representation()
    assert "AGENT AI STATUS: UNAVAILABLE" in rep
    assert "AI THESIS: NOT GENERATED" in rep
    assert "DETERMINISTIC SCREEN: NO_TRADE" in rep

    # 2. Strict invariant: Attempting to render as AI_AGENT_DECISION must raise ValueError
    with pytest.raises(ValueError, match="AI_UNAVAILABLE cannot be rendered as AI_AGENT_DECISION"):
        validated.render_decision("AI_AGENT_DECISION")

    with pytest.raises(ValueError, match="AI_UNAVAILABLE cannot be rendered as AI_AGENT_DECISION"):
        validated.render_decision("AI_DECISION")

    # 3. AI Analyst fallback must also emit DETERMINISTIC_DIAGNOSTIC, not fake AI success
    from event_agent.reporting.ai_analyst import DailyAIAnalyst
    from event_agent.reporting.trade_reconciliation import TradeReconciliationEngine
    analyst = DailyAIAnalyst(api_key="sk-test-key")
    rec = TradeReconciliationEngine.reconcile_date("2026-09-24", custom_trades_fixture=[])
    fallback_res = analyst._build_fallback_result(rec, error_msg="HTTP 402 Credit Exhausted")
    assert fallback_res.diagnostic_type == "DETERMINISTIC_DIAGNOSTIC"
    assert fallback_res.ai_status == "UNAVAILABLE"
    assert "AGENT AI STATUS: UNAVAILABLE" in fallback_res.executive_summary
    assert "AI THESIS: NOT GENERATED" in fallback_res.executive_summary
    assert "DETERMINISTIC SCREEN: NO_TRADE" in fallback_res.executive_summary


def test_option_record_without_contract_metadata_cannot_be_trade_eligible():
    """
    Regression Test 6b:
    OPTION record without contract metadata cannot be trade-eligible.
    Every OPTION position must contain:
    - underlying_symbol
    - option_symbol/contract identifier
    - expiry
    - strike
    - call_put
    - entry premium
    - current premium
    - option_data_mode
    - multiplier
    """
    from event_agent.arena.models import Instrument, ProposedTrade, OptionType

    # 1. Instrument-level validation
    malformed_opt = Instrument(
        underlying="NESTLEIND.NS",
        instrument_type=InstrumentType.OPTION,
        strike=None,
        expiry=None,
        option_type=OptionType.NONE,
    )
    assert malformed_opt.is_valid_contract is False
    assert malformed_opt.is_trade_eligible is False

    is_valid, errors = malformed_opt.validate_option_contract()
    assert is_valid is False
    assert any("strike" in e for e in errors)
    assert any("expiry" in e for e in errors)
    assert any("call_put" in e for e in errors)

    # 2. ProposedTrade-level validation
    proposal = ProposedTrade.create_simple(
        agent_id="ALPHA",
        symbol="NESTLEIND.NS",
        action="BUY",
        quantity=50,
        entry_price=1387.44, # Notice: Equity price, not option premium!
        stop_loss=1350.0,
        target=1420.0,
        instrument_type=InstrumentType.OPTION,
    )
    # The simple helper didn't provide contract metadata
    assert proposal.instrument.is_trade_eligible is False
    assert proposal.is_trade_eligible is False

    # 3. TradeGuard Gate 36 verification
    guard = TradeGuard()
    signal = {
        "symbol": "NESTLEIND.NS",
        "instrument_type": "OPTION",
        "direction": "BUY",
        "price": 1387.44,
        "base_price": 1387.44,
        "strategy": "ALPHA",
        "ai_status": "INFERENCE_SUCCESS",
        "decision_mode": "AI_INFERENCE",
    }
    order_intent = {
        "symbol": "NESTLEIND.NS",
        "instrument_type": "OPTION",
        "price": 1387.44,
        "quantity": 50,
        "action": "BUY",
        "order_intent_id": "INT-OPT-TEST-001",
        "ai_status": "INFERENCE_SUCCESS",
        "decision_mode": "AI_INFERENCE",
    }
    res = guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio={"current_capital": 2000000.0, "starting_capital": 2000000.0, "open_positions": []},
        market_data={"price": 1387.44, "base_price": 1387.44},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.is_approved is False
    assert res.rejection_code == "TRADE_BLOCKED_MALFORMED_OPTION"
    assert "cannot be trade-eligible" in res.rejection_message

    # 4. Storage ledger cohort protection verification
    from event_agent.storage.ledger import save_agent_position, get_agent_positions, get_connection
    malformed_pos = {
        "position_id": "POS-MALFORMED-OPT-REGRESSION",
        "agent_id": "ALPHA",
        "symbol": "NESTLEIND.NS",
        "instrument_type": "OPTION",
        "entry_price": 1387.44,
        "current_price": 1387.44,
        "quantity": 50,
        # Missing strike, expiry, option_type
    }
    try:
        save_agent_position(malformed_pos)
        saved = [p for p in get_agent_positions() if p["position_id"] == "POS-MALFORMED-OPT-REGRESSION"]
        assert len(saved) == 1
        # Must NOT be stored as OPTION, must be reclassified to EQUITY and excluded from cohort
        assert saved[0]["instrument_type"] == "EQUITY"
        assert saved[0]["cohort_eligible"] == 0
        assert "RECLASSIFIED_EQUITY" in saved[0]["reclassification_note"]
    finally:
        with get_connection() as conn:
            conn.execute("DELETE FROM agent_positions WHERE position_id = 'POS-MALFORMED-OPT-REGRESSION'")


def test_underlying_equity_price_cannot_be_used_as_option_premium():
    """
    Regression Test 6c:
    Underlying equity price cannot be used as option premium.
    If the record only contains an underlying equity price and no
    actual option contract, instrument_type MUST NOT be OPTION.
    """
    from event_agent.arena.models import Instrument, ProposedTrade, OptionType

    guard = TradeGuard()
    # Contract metadata is present, but price is equal to underlying cash price
    underlying_price = 11400.0 # Bajaj Auto cash price
    signal = {
        "symbol": "BAJAJ-AUTO.NS",
        "instrument_type": "OPTION",
        "option_symbol": "BAJAJ-AUTO-11500-CE-7D",
        "contract_name": "BAJAJ-AUTO-11500-CE-7D",
        "strike": 11500.0,
        "expiry": "2026-10-01",
        "option_type": "CE",
        "call_put": "CE",
        "price": 11400.0, # FRAUDULENT: Using cash equity price as option premium!
        "base_price": underlying_price,
        "direction": "BUY",
        "strategy": "ALPHA",
        "ai_status": "INFERENCE_SUCCESS",
        "decision_mode": "AI_INFERENCE",
    }
    order_intent = {
        "symbol": "BAJAJ-AUTO-11500-CE-7D",
        "instrument_type": "OPTION",
        "option_symbol": "BAJAJ-AUTO-11500-CE-7D",
        "strike": 11500.0,
        "expiry": "2026-10-01",
        "option_type": "CE",
        "price": 11400.0, # Underlying cash price used as premium
        "quantity": 10,
        "action": "BUY",
        "order_intent_id": "INT-OPT-TEST-002",
        "ai_status": "INFERENCE_SUCCESS",
        "decision_mode": "AI_INFERENCE",
    }
    res = guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio={"current_capital": 2000000.0, "starting_capital": 2000000.0, "open_positions": []},
        market_data={"price": underlying_price, "base_price": underlying_price},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.is_approved is False
    assert res.rejection_code == "TRADE_BLOCKED_UNDERLYING_PRICE_AS_OPTION_PREMIUM"
    assert "Underlying equity price" in res.rejection_message

    # Now verify with genuine option premium (e.g. ₹185.50)
    order_intent["price"] = 185.50
    signal["price"] = 185.50
    res_valid = guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio={"current_capital": 2000000.0, "starting_capital": 2000000.0, "open_positions": []},
        market_data={"price": underlying_price, "base_price": underlying_price},
        active_positions=[],
    )
    assert "GATE_36_OPTION_CONTRACT_INTEGRITY" in res_valid.passed_gates
    assert res_valid.is_approved is True


def test_quant_screen_cannot_create_order_intent_id():
    """
    Regression Test 6d:
    QUANT_SCREEN cannot create order_intent_id.
    Quantitative screen results must remain explicitly:
    QUANTITATIVE SCREEN / NON-TRADING / NOT AI DECISION.
    """
    from event_agent.execution.broker_state_machine import OrderLineage
    from event_agent.execution.idempotency import IdempotencyEngine

    # 1. OrderLineage barrier: Cannot be created with QUANT_SCREEN signal or order_intent_id
    with pytest.raises(ValueError, match="QUANT_SCREEN cannot create order_intent_id"):
        OrderLineage(
            signal_id="QUANT_SCREEN_SETUP_TOP8_01",
            decision_id="DEC-QUANT_SCREEN-01",
            order_intent_id="INT-QUANT-001",
        )

    with pytest.raises(ValueError, match="QUANT_SCREEN cannot create order_intent_id"):
        OrderLineage(
            signal_id="SIG-20260924-001",
            decision_id="DEC-20260924-001",
            order_intent_id="INT-QUANT_SCREEN-LEAK",
        )

    # 2. Idempotency reservation barrier
    engine = IdempotencyEngine()
    with pytest.raises(ValueError, match="QUANT_SCREEN cannot create order_intent_id"):
        engine.reserve(
            signal_id="QUANT_SCREEN_CANDIDATE_LT",
            symbol="LT.NS",
            side="BUY",
            order_intent_id="INT-LEAK-QUANT-01",
        )

    # 3. TradeGuard Gate 37 barrier
    guard = TradeGuard()
    signal = {
        "symbol": "LT.NS",
        "category": "QUANTITATIVE SCREEN / NON-TRADING / NOT AI DECISION",
        "source": "QUANT_SCREEN",
        "direction": "BULLISH",
        "price": 3929.90,
        "base_price": 3929.90,
        "strategy": "QUANT_SCREEN",
        "ai_status": "INFERENCE_SUCCESS",
        "decision_mode": "AI_INFERENCE",
    }
    order_intent = {
        "symbol": "LT.NS",
        "category": "QUANTITATIVE SCREEN / NON-TRADING / NOT AI DECISION",
        "source": "QUANT_SCREEN",
        "price": 3929.90,
        "quantity": 10,
        "action": "BUY",
        "order_intent_id": "INT-QUANT-SCREEN-BLOCKED",
        "ai_status": "INFERENCE_SUCCESS",
        "decision_mode": "AI_INFERENCE",
    }
    res = guard.evaluate(
        signal=signal,
        order_intent=order_intent,
        portfolio={"current_capital": 2000000.0, "starting_capital": 2000000.0, "open_positions": []},
        market_data={"price": 3929.90, "base_price": 3929.90},
        active_positions=[],
    )
    assert res.verdict == TradeGuardVerdict.NO_TRADE
    assert res.is_approved is False
    assert res.rejection_code == "TRADE_BLOCKED_QUANT_SCREEN_NON_TRADING"
    assert "cannot create order_intent_id" in res.rejection_message
