# =============================================================================
# tests/test_v42_institutional_architecture.py — V4.2 Verification Test Suite
# =============================================================================
"""
Unit and integration tests for V4.2 Multi-Asset Intelligence & Forensic Audit:
1. OpenRouter Real Runtime Truth & Zero Key Leak Telemetry
2. Deterministic MarketThesisValidator (Bounds & THESIS_CONFLICT)
3. Two-Way Positions (LONG/SHORT, BUY/SELL, OPEN/CLOSE)
4. Central Deterministic Instrument Selector & Net Edge Hurdle (NO_TRADE)
5. Options Data Mode Governance (LIVE / MODELLED / UNAVAILABLE Invariant)
6. Portfolio Greeks Engine (Net Delta +/-0.30, Margin <60%) & Sector Exposure (<=25%)
7. Dual Exit Engines with 9-Level Priority Hierarchy & Stale Data Emergency Path
8. 8D Deterministic Forensic Decomposer & Empirical F06 Criteria
"""

import os
import pytest
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from event_agent.engine.llm_provider import OpenRouterProvider
from event_agent.arena.thesis_validator import MarketThesis, MarketThesisValidator
from event_agent.arena.models import (
    PositionSide, OrderIntent, TradeAction, TradeDirection,
    Instrument, InstrumentType, ProposedTrade, HedgeDecision
)
from event_agent.arena.option_chain_provider import OptionChainProvider, OptionDataMode
from event_agent.arena.strike_selector import StrikeSelector
from event_agent.arena.greeks_engine import PortfolioGreeksEngine
from event_agent.arena.portfolio_exposure import PortfolioExposureEngine
from event_agent.arena.instrument_selector import InstrumentSelector
from event_agent.arena.exit_engine import (
    ExitEngine, ExitPriority, EquityFuturesExitEngine, OptionsExitEngine
)
from event_agent.audit.attribution_engine import ForensicDecomposer8D


# -----------------------------------------------------------------------------
# 1. OpenRouter Runtime Truth & Zero-Leak Telemetry Tests
# -----------------------------------------------------------------------------

def test_openrouter_zero_key_leak():
    provider = OpenRouterProvider()
    status = provider.check_runtime_connection()
    raw_key = os.getenv("OPENROUTER_API_KEY", "")

    # Invariant: Raw key or raw prefix must NEVER appear in returned dictionary
    status_str = str(status)
    if raw_key and len(raw_key) > 8:
        assert raw_key not in status_str, "CRITICAL: Raw OpenRouter key leaked in connection status!"
        assert raw_key[:12] not in status_str, "CRITICAL: Raw key prefix leaked in connection status!"

    if raw_key:
        assert status["configured"] is True
        assert status["credential_fingerprint"] is not None
        assert status["credential_fingerprint"].startswith("SHA256:")
        assert len(status["credential_fingerprint"]) > 10


def test_openrouter_real_inference_and_telemetry():
    provider = OpenRouterProvider()
    if not provider.api_key:
        pytest.skip("OPENROUTER_API_KEY not configured in environment; skipping live HTTP test.")

    stock_data = {
        "base_price": 4150.0,
        "catalysts": ["Q2 Revenue up 12% YoY", "Major deal win in North America"],
        "conviction": 75.0,
        "predicted_1d_pct": 1.25,
    }
    market_context = {"regime": "NORMAL", "vix": "LOW", "usdinr": "STABLE"}

    result = provider.generate_decision_thesis(
        agent_id="ALPHA",
        symbol="TCS.NS",
        stock_data=stock_data,
        market_context=market_context,
    )

    if result["status"] == "FAILED" and ("402" in str(result.get("error", "")) or "Payment Required" in str(result.get("error", "")) or "429" in str(result.get("error", ""))):
        pytest.skip(f"OpenRouter live API credits/quota unavailable: {result.get('error')}")

    assert result["status"] == "SUCCESS", f"Live OpenRouter call failed: {result.get('error')}"
    assert result["ai_request_id"] is not None
    assert len(result["ai_request_id"]) > 5
    assert result["latency_ms"] > 0
    assert result["tokens"] > 0
    assert result["direction"] in ("BULLISH", "BEARISH")
    assert -20.0 <= float(result["expected_move_pct"]) <= 20.0
    assert result["horizon"] in ("1D", "3D", "7D")
    assert len(result.get("invalidating_conditions", [])) > 0


# -----------------------------------------------------------------------------
# 2. MarketThesisValidator Tests
# -----------------------------------------------------------------------------

def test_thesis_validator_bounds_rejection():
    # Out of bounds confidence (147.0) and expected move (-500%)
    bad_thesis = MarketThesis(
        agent_id="MOMENTUM",
        symbol="RELIANCE.NS",
        direction="maybe bullish",
        expected_move_pct=-500.0,
        horizon="tomorrowish",
        confidence=147.0,
        catalysts=[],
        invalidating_conditions=[],
        reasoning="Testing invalid inputs",
    )

    validated = MarketThesisValidator.validate(bad_thesis)
    # Validator must clamp and canonicalize
    assert validated.confidence == 100.0, "Confidence > 100 was not clamped"
    assert validated.expected_move_pct == 0.0, "Unrealistic expected move was not rejected"
    assert validated.horizon == "1D", "Invalid horizon was not normalized to canonical 1D"
    assert validated.direction == "NEUTRAL", "Invalid direction was not flagged"
    assert len(validated.invalidating_conditions) > 0, "Missing invalidating conditions were not populated"


def test_thesis_validator_macro_conflict():
    bullish_thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="INFY.NS",
        direction="BULLISH",
        expected_move_pct=1.5,
        horizon="1D",
        confidence=65.0,
        catalysts=["New cloud contract"],
        invalidating_conditions=["Market crash"],
        reasoning="Solid cloud pipeline growth.",
    )

    # Adverse macro evidence: India VIX surges +6.5%, USDINR rises +0.35%, Global futures down -1.1%
    macro_evidence = {
        "vix_change_pct": 6.5,
        "usdinr_change_pct": 0.35,
        "global_futures_pct": -1.1,
        "adv_dec_ratio": 0.40,
    }

    validated = MarketThesisValidator.validate(bullish_thesis, structured_evidence=macro_evidence)
    assert validated.is_conflicted is True, "Thesis conflict was not flagged despite surging VIX and dropping futures"
    assert len(validated.conflict_reasons) >= 3
    assert any("VIX" in r for r in validated.conflict_reasons)


# -----------------------------------------------------------------------------
# 3. Two-Way Order Semantics & Data Model Tests
# -----------------------------------------------------------------------------

def test_two_way_position_semantics():
    inst = Instrument(underlying="TCS.NS", instrument_type=InstrumentType.EQUITY)

    # Scenario 1: Open Long
    open_long = ProposedTrade(
        agent_id="ALPHA",
        strategy_version="V4.2",
        symbol="TCS.NS",
        action=TradeAction.BUY,
        instrument=inst,
        direction=TradeDirection.BUY,
        entry_price=4000.0,
        stop_loss=3920.0,
        target=4120.0,
        confidence=75.0,
        expected_move_pct=3.0,
        planned_risk_amount=2000.0,
        hedge_decision=HedgeDecision.NO,
        position_side=PositionSide.LONG,
        order_action=TradeAction.BUY,
        order_intent=OrderIntent.OPEN,
    )
    assert open_long.position_side == PositionSide.LONG
    assert open_long.order_action == TradeAction.BUY
    assert open_long.order_intent == OrderIntent.OPEN

    # Scenario 2: Open Short
    open_short = ProposedTrade(
        agent_id="MOMENTUM",
        strategy_version="V4.2",
        symbol="TCS.NS",
        action=TradeAction.SELL,
        instrument=inst,
        direction=TradeDirection.SELL,
        entry_price=4000.0,
        stop_loss=4080.0,
        target=3880.0,
        confidence=72.0,
        expected_move_pct=-3.0,
        planned_risk_amount=2000.0,
        hedge_decision=HedgeDecision.NO,
        position_side=PositionSide.SHORT,
        order_action=TradeAction.SELL,
        order_intent=OrderIntent.OPEN,
    )
    assert open_short.position_side == PositionSide.SHORT
    assert open_short.order_action == TradeAction.SELL
    assert open_short.order_intent == OrderIntent.OPEN


# -----------------------------------------------------------------------------
# 4. Central Instrument Selector & Capacity-Constrained Funnel Tests
# -----------------------------------------------------------------------------

def test_instrument_selector_net_edge_hurdle():
    selector = InstrumentSelector()
    # Weak expected move: +0.20% (does not clear 0.35% roundtrip costs)
    weak_thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="HDFCBANK.NS",
        direction="BULLISH",
        expected_move_pct=0.20,
        horizon="1D",
        confidence=60.0,
        catalysts=["Minor branch expansion"],
        invalidating_conditions=["Rate hike"],
        reasoning="Small upward drift expected.",
    )
    stock_data = {"base_price": 1650.0, "sector": "Private Banking", "beta": 0.95}

    proposal = selector.select_instrument(
        thesis=weak_thesis,
        stock_data=stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
    )

    assert proposal.action == TradeAction.NO_TRADE, "Weak move below net edge hurdle must result in NO_TRADE"
    assert "net edge hurdle" in proposal.decision_reason


def test_instrument_selector_two_way_mapping():
    selector = InstrumentSelector()
    # Strong bearish setup
    bear_thesis = MarketThesis(
        agent_id="MOMENTUM",
        symbol="WIPRO.NS",
        direction="BEARISH",
        expected_move_pct=-2.5,
        horizon="1D",
        confidence=75.0,
        catalysts=["Earnings guidance slashed"],
        invalidating_conditions=["Short squeeze"],
        reasoning="Guidance downgrade implies swift breakdown.",
    )
    stock_data = {"base_price": 450.0, "sector": "IT Services", "beta": 1.15}

    proposal = selector.select_instrument(
        thesis=bear_thesis,
        stock_data=stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
    )

    assert proposal.action == TradeAction.SELL
    assert proposal.position_side == PositionSide.SHORT
    assert proposal.order_action == TradeAction.SELL
    assert proposal.order_intent == OrderIntent.OPEN
    assert proposal.target < proposal.entry_price
    assert proposal.stop_loss > proposal.entry_price


# -----------------------------------------------------------------------------
# 5. Options Data Mode Governance Invariant
# -----------------------------------------------------------------------------

def test_options_data_mode_invariant():
    # 1. UNAVAILABLE Mode -> Strictly NO options trade
    prov_unavail = OptionChainProvider(default_mode=OptionDataMode.UNAVAILABLE)
    assert prov_unavail.can_trade_options("LIVE") is False
    assert prov_unavail.can_trade_options("PAPER") is False
    chain, mode = prov_unavail.get_chain("NIFTY50", 25000.0)
    assert chain is None
    assert mode == OptionDataMode.UNAVAILABLE

    # 2. MODELLED Mode -> Permitted for PAPER RESEARCH ONLY, forbidden for LIVE
    prov_modelled = OptionChainProvider(default_mode=OptionDataMode.MODELLED)
    assert prov_modelled.can_trade_options("PAPER") is True
    assert prov_modelled.can_trade_options("LIVE") is False
    chain_m, mode_m = prov_modelled.get_chain("NIFTY50", 25000.0)
    assert chain_m is not None
    assert mode_m == OptionDataMode.MODELLED
    assert chain_m.is_modelled_data is True

    # 3. LIVE Mode -> Options May Trade
    prov_live = OptionChainProvider(default_mode=OptionDataMode.LIVE)
    # Without live broker feed connected, is_stale evaluates to True, preventing stale trades
    prov_live._last_fetch_timestamp = datetime.now().timestamp()
    assert prov_live.can_trade_options("LIVE") is True


# -----------------------------------------------------------------------------
# 6. Portfolio Greeks & Sector Exposure Engine Tests
# -----------------------------------------------------------------------------

def test_portfolio_greeks_bounds():
    # Construct positions with excessive delta
    positions = [
        {"symbol": "RELIANCE.NS", "quantity": 500, "entry_price": 3000.0, "current_price": 3000.0, "instrument_type": "EQUITY", "position_side": "LONG"},
        {"symbol": "TCS.NS", "quantity": 300, "entry_price": 4000.0, "current_price": 4000.0, "instrument_type": "EQUITY", "position_side": "LONG"},
    ]
    # Total delta = (500*3000) + (300*4000) = 15L + 12L = 27L
    # On portfolio equity of 20L, normalized delta = 27L / 20L = 1.35 (Breaches 0.30 cap!)
    greeks = PortfolioGreeksEngine.calculate_portfolio_greeks(
        open_positions=positions,
        portfolio_equity=2000000.0,
    )
    assert greeks.is_delta_compliant is False
    assert any("Normalized Delta" in b for b in greeks.breaches)


def test_portfolio_exposure_sector_cap():
    # Existing Banking positions totaling 24% of portfolio
    existing = [
        {"symbol": "HDFCBANK.NS", "quantity": 250, "entry_price": 1600.0, "cost_basis": 400000.0, "sector": "Private Banking"},
        {"symbol": "ICICIBANK.NS", "quantity": 100, "entry_price": 1000.0, "cost_basis": 100000.0, "sector": "Private Banking"},
    ]
    # Candidate trade adding another 2L into Private Banking (would push to 35% > 25% cap!)
    proposed = {
        "symbol": "KOTAKBANK.NS",
        "quantity": 100,
        "entry_price": 1800.0,
        "cost_basis": 180000.0,
        "sector": "Private Banking",
    }
    exposure = PortfolioExposureEngine.evaluate_exposure(
        open_positions=existing,
        portfolio_equity=2000000.0,
        proposed_trade=proposed,
        candidate_sector="Private Banking",
    )
    assert exposure.is_compliant is False
    assert "exceeds limit of 25.0%" in exposure.rejection_reason


# -----------------------------------------------------------------------------
# 7. Dual Exit Engines & Priority Hierarchy Tests
# -----------------------------------------------------------------------------

def test_exit_priority_hierarchy():
    # Position that hits BOTH emergency kill switch (Priority 1) and Target profit (Priority 7)
    pos = {
        "position_id": "POS-101",
        "symbol": "TCS.NS",
        "entry_price": 4000.0,
        "target_price": 4150.0,
        "stop_loss": 3900.0,
        "position_side": "LONG",
    }
    # When kill switch is active, Priority 1 must override Target!
    signal = EquityFuturesExitEngine.evaluate(
        position=pos,
        current_price=4160.0,
        is_kill_switch_active=True,
    )
    assert signal is not None
    assert signal.should_exit is True
    assert signal.priority == ExitPriority.BROKER_SAFETY_EMERGENCY
    assert signal.exit_reason == "BROKER_SAFETY_EMERGENCY"


def test_options_stale_data_protective_path():
    pos = {
        "position_id": "POS-OPT-202",
        "symbol": "NIFTY-25000-CE",
        "entry_price": 120.0,
        "target_price": 200.0,
        "stop_loss": 60.0,
        "underlying_stop": 24800.0,
        "position_side": "LONG",
    }
    # Case A: Stale data (>60s old), but underlying spot safe -> Analytical exit paused
    sig_a = OptionsExitEngine.evaluate(
        position=pos,
        current_premium=130.0,
        underlying_spot=24950.0,
        is_stale_data=True,
    )
    assert sig_a is not None
    assert sig_a.should_exit is False  # Does NOT execute market sell on stale invented quotes
    assert sig_a.exit_reason == "DATA_INTEGRITY_STALE_QUOTE"

    # Case B: Stale data, BUT underlying spot breaches hard emergency stop -> Emergency exit triggers!
    sig_b = OptionsExitEngine.evaluate(
        position=pos,
        current_premium=130.0,
        underlying_spot=24750.0,  # Below 24800.0 emergency stop!
        is_stale_data=True,
    )
    assert sig_b is not None
    assert sig_b.should_exit is True
    assert sig_b.is_emergency_order is True
    assert sig_b.priority == ExitPriority.MAX_LOSS


# -----------------------------------------------------------------------------
# 8. 8D Forensic Decomposer & Empirical F06 Criteria Tests
# -----------------------------------------------------------------------------

def test_f06_empirical_deterministic_classification():
    # TCS-like profile:
    # Predicted: +0.46% (target ~18.8 Rs)
    # Actual: -3.45%
    # Intraday High: 4180 (+0.7%), Low: 4010 (-3.6%), Close: 4020 (-3.4%)
    # RV was 2.1x predicted, MAE was 1.9x target, 2 reversals, gap confirmed
    diag = ForensicDecomposer8D.decompose(
        symbol="TCS.NS",
        predicted_pct=0.46,
        actual_pct=-3.45,
        base_price=4150.0,
        actual_high=4180.0,
        actual_low=4010.0,
        actual_close=4020.0,
        predicted_volatility=0.012,
    )

    assert diag.is_f06_whipsaw is True
    assert diag.root_cause_code == "F06"
    assert diag.root_cause_name == "INTRADAY_VOLATILITY_WHIPSAW"
    assert diag.realized_vol_ratio >= 1.80
    assert diag.mae_ratio >= 1.50
    assert diag.reversal_count >= 2
    assert "F06 Deterministic Whipsaw" in diag.deterministic_summary


def test_cause_undetermined_when_thresholds_not_met():
    # Normal stochastic deviation: predicted +0.8%, actual -0.4%
    # No extreme RV, no 1.5x MAE, no 2 reversals
    diag = ForensicDecomposer8D.decompose(
        symbol="INFY.NS",
        predicted_pct=0.80,
        actual_pct=-0.40,
        base_price=1800.0,
        actual_high=1805.0,
        actual_low=1790.0,
        actual_close=1792.0,
        predicted_volatility=0.015,
    )

    # Invariant: Must NOT fabricate a whipsaw or false category; must emit CAUSE_UNDETERMINED
    assert diag.root_cause_code == "CAUSE_UNDETERMINED"
    assert diag.root_cause_name == "CAUSE_UNDETERMINED"
    assert "CAUSE_UNDETERMINED" in diag.deterministic_summary


# -----------------------------------------------------------------------------
# 9. TradeGuard Hard Invariant: Stale Base Price & Zero Silent Rebasing Tests
# -----------------------------------------------------------------------------

def test_stale_base_price_rejected():
    """
    TEST_STALE_BASE_PRICE_REJECTED:
    Given:
      prediction.base_price = 8769.0
      base_price_timestamp = 09:00:00
      decision_timestamp = 09:30:00
      MAX_PRICE_AGE = 5 minutes (300s)
    When:
      InstrumentSelector receives thesis
    Then:
      NO_TRADE
      reason contains STALE_BASE_PRICE
      no order intent
      entry_price = 0.0
    """
    selector = InstrumentSelector()
    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="APOLLOHOSP.NS",
        direction="BULLISH",
        expected_move_pct=1.50,
        horizon="1D",
        confidence=80.0,
        catalysts=["Solid Q2 hospital occupancy expansion"],
        invalidating_conditions=["Policy cap on margins"],
        reasoning="Occupancy rate expansion driving strong EBITDA.",
    )
    stock_data = {
        "base_price": 8769.0,
        "base_price_timestamp": "2026-09-23T09:00:00+00:00",
        "max_price_age_seconds": 300.0,
        "sector": "Healthcare",
        "beta": 0.85,
    }
    decision_time = datetime(2026, 9, 23, 9, 30, 0, tzinfo=timezone.utc)

    proposal = selector.select_instrument(
        thesis=thesis,
        stock_data=stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
        snapshot_id="SNAP-TEST-STALE",
        decision_timestamp=decision_time,
    )

    assert proposal.action == TradeAction.NO_TRADE
    assert proposal.order_action == TradeAction.NO_TRADE
    assert "STALE_BASE_PRICE" in proposal.decision_reason
    assert proposal.entry_price == 0.0
    assert proposal.target == 0.0
    assert proposal.stop_loss == 0.0


def test_fresh_base_price_accepted():
    """
    TEST_FRESH_BASE_PRICE_ACCEPTED:
    Given:
      base_price = 8769.0
      base_price_timestamp = 09:29:30 (age = 30 seconds)
      decision_timestamp = 09:30:00
      MAX_PRICE_AGE = 5 minutes
    Then:
      Normal instrument selection passes (BUY) with exact math from fresh price.
    """
    selector = InstrumentSelector()
    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="APOLLOHOSP.NS",
        direction="BULLISH",
        expected_move_pct=1.50,
        horizon="1D",
        confidence=80.0,
        catalysts=["Solid Q2 hospital occupancy expansion"],
        invalidating_conditions=["Policy cap on margins"],
        reasoning="Occupancy rate expansion driving strong EBITDA.",
    )
    stock_data = {
        "base_price": 8769.0,
        "base_price_timestamp": "2026-09-23T09:29:30+00:00",
        "max_price_age_seconds": 300.0,
        "sector": "Healthcare",
        "beta": 0.85,
    }
    decision_time = datetime(2026, 9, 23, 9, 30, 0, tzinfo=timezone.utc)

    proposal = selector.select_instrument(
        thesis=thesis,
        stock_data=stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
        snapshot_id="SNAP-TEST-FRESH",
        decision_timestamp=decision_time,
    )

    assert proposal.action == TradeAction.BUY
    assert proposal.entry_price == 8769.0
    expected_target = round(8769.0 * (1.0 + 1.50 / 100.0), 2)
    assert proposal.target == expected_target
    assert proposal.direction == TradeDirection.BUY


def test_target_never_rebased_silently():
    """
    TEST_TARGET_NEVER_REBASED_SILENTLY:
    Given stale prediction with old base = 8769.0 and live market price = 8927.0:
    The system must NOT silently mutate target = 8856.69 into 9016.27 just to prevent immediate exit.
    It must reject the stale baseline as NO_TRADE with STALE_BASE_PRICE.
    """
    selector = InstrumentSelector()
    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="APOLLOHOSP.NS",
        direction="BULLISH",
        expected_move_pct=1.00,
        horizon="1D",
        confidence=75.0,
        catalysts=["Expansion update"],
        invalidating_conditions=["Regulatory clamp"],
        reasoning="Expansion update supports 1.0% drift.",
    )
    # Stale prediction baseline: old base 8769 (timestamp from 20 minutes ago)
    # Live market price is already 8927
    stale_stock_data = {
        "base_price": 8769.0,
        "base_price_timestamp": "2026-09-23T09:10:00+00:00",
        "live_price": 8927.0,
        "max_price_age_seconds": 300.0,
        "sector": "Healthcare",
        "beta": 0.85,
    }
    decision_time = datetime(2026, 9, 23, 9, 30, 0, tzinfo=timezone.utc)

    proposal = selector.select_instrument(
        thesis=thesis,
        stock_data=stale_stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
        snapshot_id="SNAP-TEST-NO-REBASE",
        decision_timestamp=decision_time,
    )

    # Invariant: Must NOT rebase to 8927 * 1.01 = 9016.27!
    # Must reject stale prediction baseline directly
    assert proposal.action == TradeAction.NO_TRADE
    assert "STALE_BASE_PRICE" in proposal.decision_reason
    assert proposal.target != 9016.27
    assert proposal.target == 0.0

