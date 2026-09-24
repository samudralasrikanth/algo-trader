# =============================================================================
# tests/test_v422_fundamental_layer.py — 15-Scenario Comprehensive Verification Suite
# =============================================================================
"""
Exhaustive verification suite for NEXUS V4.2.2:
NSE Market Lens Fundamental Intelligence Layer & Unified PointInTimeSnapshot.

Validates all 15 institutional test scenarios:
 1. Market Lens unavailable
 2. Market Lens stale
 3. Market Lens malformed
 4. Fundamental timestamp after prediction -> reject
 5. Fundamental timestamp before prediction -> accept
 6. No fundamental data -> no fabricated score
 7. Strong fundamentals + bearish event
 8. Weak fundamentals + bullish event
 9. Contrarian oversold + strong fundamentals
10. Momentum + contradictory fundamentals
11. Fundamental regime calculation
12. Fundamental provenance hash
13. Replay produces identical snapshot
14. Fundamental data cannot bypass TradeGuard
15. Fundamental data cannot force a trade
"""

from datetime import datetime, timezone, timedelta
import math
import pytest

from event_agent.fundamentals.fundamental_snapshot import (
    FundamentalContext,
    FundamentalFreshness,
    FundamentalRegime,
    FundamentalRole,
    FundamentalSnapshot,
)
from event_agent.fundamentals.fundamental_validator import FundamentalValidator
from event_agent.fundamentals.fundamental_score import FundamentalScoreEngine
from event_agent.fundamentals.market_lens_provider import MarketLensProvider
from event_agent.engine.pit_snapshot import PointInTimeSnapshot
from event_agent.arena.thesis_validator import MarketThesis, MarketThesisValidator
from event_agent.arena.instrument_selector import InstrumentSelector
from event_agent.arena.agents.agent_alpha import AgentAlpha
from event_agent.arena.agents.agent_momentum import AgentMomentum
from event_agent.arena.agents.agent_contrarian import AgentContrarian
from event_agent.audit.attribution_engine import ForensicDecomposer8D


# ---------------------------------------------------------------------------
# Test 1: Market Lens unavailable
# ---------------------------------------------------------------------------
def test_market_lens_unavailable():
    """Verify that when Market Lens is unavailable, it gracefully returns FUNDAMENTALS_UNAVAILABLE."""
    provider = MarketLensProvider(force_mode="UNAVAILABLE")
    now_dt = datetime.now(timezone.utc)
    snap = provider.get_snapshot("RELIANCE.NS", as_of_dt=now_dt)

    assert snap.source == "FUNDAMENTALS_UNAVAILABLE"
    assert snap.freshness == FundamentalFreshness.UNAVAILABLE.value
    assert snap.quality_score is None
    assert snap.valuation_score is None
    assert snap.growth_score is None
    assert not snap.is_available


# ---------------------------------------------------------------------------
# Test 2: Market Lens stale
# ---------------------------------------------------------------------------
def test_market_lens_stale():
    """Verify that fundamental data older than 180 days is flagged as STALE."""
    now_dt = datetime.now(timezone.utc)
    stale_as_of = now_dt - timedelta(days=200)

    snap = FundamentalSnapshot(
        symbol="TCS.NS",
        as_of=stale_as_of,
        source="NSE_MARKET_LENS_LOCAL",
        valuation={"pe_ratio": 28.0, "pb_ratio": 12.0},
        profitability={"roce_pct": 50.0, "operating_margin_pct": 25.0},
        growth={"revenue_growth_yoy": 10.0, "pat_growth_yoy": 10.0},
        leverage={"debt_to_equity": 0.05},
        ownership={"promoter_holding_pct": 72.0},
        quality_score=85.0,
        valuation_score=40.0,
    )

    is_valid, errors, validated = FundamentalValidator.validate_snapshot(
        snap, decision_timestamp=now_dt
    )

    assert is_valid
    assert validated.freshness == FundamentalFreshness.STALE.value
    assert not validated.is_fresh


# ---------------------------------------------------------------------------
# Test 3: Market Lens malformed
# ---------------------------------------------------------------------------
def test_market_lens_malformed():
    """Verify that malformed numbers (NaN / Inf) are caught by the validator."""
    now_dt = datetime.now(timezone.utc)
    malformed_snap = FundamentalSnapshot(
        symbol="INFY.NS",
        as_of=now_dt - timedelta(days=20),
        source="TEST_SOURCE",
        valuation={"pe_ratio": float("nan")},
        profitability={"roce_pct": float("inf")},
        quality_score=70.0,
    )

    is_valid, errors, validated = FundamentalValidator.validate_snapshot(
        malformed_snap, decision_timestamp=now_dt
    )

    assert not is_valid
    assert any("Malformed numeric" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 4: Fundamental timestamp after prediction -> reject (causal violation)
# ---------------------------------------------------------------------------
def test_fundamental_timestamp_after_prediction():
    """Verify that a future fundamental timestamp relative to decision_timestamp is rejected."""
    decision_ts = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)
    future_as_of = datetime(2026, 9, 23, 11, 0, 0, tzinfo=timezone.utc)

    snap = FundamentalSnapshot(
        symbol="HDFCBANK.NS",
        as_of=future_as_of,
        source="TEST_FEED",
        quality_score=75.0,
    )

    is_valid, errors, validated = FundamentalValidator.validate_snapshot(
        snap, decision_timestamp=decision_ts
    )

    assert not is_valid
    assert any("CAUSAL_VIOLATION" in e for e in errors)
    assert validated.freshness == FundamentalFreshness.EXPIRED.value


# ---------------------------------------------------------------------------
# Test 5: Fundamental timestamp before prediction -> accept (valid point-in-time)
# ---------------------------------------------------------------------------
def test_fundamental_timestamp_before_prediction():
    """Verify that a fundamental timestamp before decision_timestamp is accepted."""
    decision_ts = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)
    prior_as_of = datetime(2026, 8, 15, 18, 0, 0, tzinfo=timezone.utc)

    snap = FundamentalSnapshot(
        symbol="HDFCBANK.NS",
        as_of=prior_as_of,
        source="TEST_FEED",
        valuation={"pe_ratio": 18.0},
        profitability={"roce_pct": 16.0},
        quality_score=75.0,
    )

    is_valid, errors, validated = FundamentalValidator.validate_snapshot(
        snap, decision_timestamp=decision_ts
    )

    assert is_valid
    assert len(errors) == 0
    assert validated.freshness == FundamentalFreshness.FRESH.value


# ---------------------------------------------------------------------------
# Test 6: No fundamental data -> no fabricated score (runtime truth)
# ---------------------------------------------------------------------------
def test_no_fundamental_data_no_fabricated_scores():
    """Verify runtime truth: missing fundamental data produces None, not 0 or fabricated scores."""
    provider = MarketLensProvider()
    snap = provider.get_snapshot("UNKNOWN_SYMBOL_999.NS")

    assert snap.source == "FUNDAMENTALS_UNAVAILABLE"
    assert snap.quality_score is None
    assert snap.valuation_score is None
    assert snap.growth_score is None
    assert snap.balance_sheet_score is None
    assert snap.fundamental_regime == FundamentalRegime.INSUFFICIENT_DATA.value


# ---------------------------------------------------------------------------
# Test 7: Strong fundamentals + bearish event
# ---------------------------------------------------------------------------
def test_strong_fundamentals_bearish_event():
    """Verify that a fundamentally strong company with a short-term bearish event is processed correctly."""
    high_quality_fundamentals = FundamentalSnapshot(
        symbol="TCS.NS",
        as_of=datetime.now(timezone.utc) - timedelta(days=20),
        source="NSE_MARKET_LENS_AUTHORITATIVE",
        valuation={"pe_ratio": 28.0, "pb_ratio": 12.0},
        profitability={"roce_pct": 55.0, "operating_margin_pct": 26.0},
        growth={"revenue_growth_yoy": 8.0, "pat_growth_yoy": 9.0},
        leverage={"debt_to_equity": 0.02},
        ownership={"promoter_holding_pct": 72.0},
        quality_score=88.0,
        valuation_score=65.0,
        fundamental_regime=FundamentalRegime.HEALTHY.value,
        freshness="FRESH",
    )

    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="TCS.NS",
        direction="BEARISH",
        expected_move_pct=-1.20,
        horizon="1D",
        confidence=65.0,
        catalysts=["Unexpected CFO resignation announcement"],
        invalidating_conditions=["Immediate clarifying statement from board"],
        reasoning="C-suite turnover catalyst drives near-term institutional derisking.",
        fundamental_context=FundamentalContext(
            quality_score=88.0,
            valuation_score=65.0,
            growth_score=60.0,
            balance_sheet_score=95.0,
            fundamental_regime=FundamentalRegime.HEALTHY.value,
            confirmation=False,
            contradiction=True,
            data_as_of="2026-08-30",
            source="NSE_MARKET_LENS_AUTHORITATIVE",
            role=FundamentalRole.VALUATION_CONTEXT.value,
            reasoning="High quality (88.0) and attractive valuation (65.0) contradict bearish thesis.",
        ),
    )

    validated = MarketThesisValidator.validate(thesis)
    # Contradiction should be noted as a thesis conflict (FUNDAMENTAL_CONFLICT), but thesis remains valid
    assert validated.thesis_conflict
    assert validated.is_valid
    assert any("FUNDAMENTAL_CONFLICT" in r or "Fundamental contradiction" in r for r in validated.conflict_reasons)


# ---------------------------------------------------------------------------
# Test 8: Weak fundamentals + bullish event
# ---------------------------------------------------------------------------
def test_weak_fundamentals_bullish_event():
    """Verify that Alpha correctly classifies catalyst as LOW_CREDIBILITY when company is fundamentally stressed."""
    agent = AgentAlpha()
    now_dt = datetime.now(timezone.utc)

    weak_fund = FundamentalSnapshot(
        symbol="WEAKCO.NS",
        as_of=now_dt - timedelta(days=10),
        source="TEST_FEED",
        valuation={"pe_ratio": 95.0},
        profitability={"roce_pct": 2.0},
        growth={"revenue_growth_yoy": -15.0},
        leverage={"debt_to_equity": 3.8},
        quality_score=25.0,
        growth_score=20.0,
        fundamental_regime=FundamentalRegime.STRESSED.value,
    )

    stock_data = {
        "symbol": "WEAKCO.NS",
        "base_price": 500.0,
        "base_price_timestamp": now_dt.isoformat(),
        "conviction": 52.0,
        "predicted_1d_pct": 0.80,
        "catalysts": ["Announced potential MoU with foreign partner"],
        "stock_sentiment": 0.25,
        "fundamental_snapshot": weak_fund,
    }

    market_snap = {
        "snapshot_id": "SNAP-TEST-001",
        "stocks": {"WEAKCO.NS": stock_data},
        "regime": {"composite": 0.0, "label": "NEUTRAL", "dimensions": {"risk": "NEUTRAL"}},
    }

    proposals = agent.evaluate_market(
        market_snapshot=market_snap,
        current_open_positions=[],
        current_equity=2000000.0,
        current_cash=2000000.0,
    )

    # Low credibility trims conviction (52 * 0.85 = 44.2 < 48.0 min conviction) -> NO_TRADE
    assert len(proposals) == 1
    assert proposals[0].action.value == "NO_TRADE"


# ---------------------------------------------------------------------------
# Test 9: Contrarian oversold + strong fundamentals
# ---------------------------------------------------------------------------
def test_contrarian_oversold_strong_fundamentals():
    """Verify that Contrarian confirms dip-buy on an oversold high-quality company."""
    agent = AgentContrarian()
    # Deterministic AI response for testing fundamental confirmation logic
    agent.llm_provider.generate_decision_thesis = lambda *args, **kwargs: {
        "status": "SUCCESS",
        "ai_status": "INFERENCE_SUCCESS",
        "direction": "BULLISH",
        "expected_move_pct": 1.20,
        "horizon": "1D",
        "confidence": 65.0,
        "catalysts": ["Oversold quality dip"],
        "invalidating_conditions": ["Further breakdown"],
        "reasoning": "Contrarian bounce setup on high-quality stock",
        "decision_mode": "AI_INFERENCE",
        "evaluation_status": "EVALUABLE",
    }
    now_dt = datetime.now(timezone.utc)

    strong_fund = FundamentalSnapshot(
        symbol="QUALITYDIP.NS",
        as_of=now_dt - timedelta(days=15),
        source="NSE_MARKET_LENS_AUTHORITATIVE",
        valuation={"pe_ratio": 22.0},
        profitability={"roce_pct": 32.0, "operating_margin_pct": 22.0},
        growth={"revenue_growth_yoy": 12.0},
        leverage={"debt_to_equity": 0.15},
        quality_score=82.0,
        valuation_score=55.0,
        fundamental_regime=FundamentalRegime.HEALTHY.value,
    )

    stock_data = {
        "symbol": "QUALITYDIP.NS",
        "base_price": 2500.0,
        "base_price_timestamp": now_dt.isoformat(),
        "conviction": 65.0,
        "momentum_5d_pct": -2.8,
        "stock_sentiment": -0.45,
        "predicted_1d_pct": 1.20,
        "sector": "Information Technology",
        "beta": 0.95,
        "fundamental_snapshot": strong_fund,
    }

    market_snap = {
        "snapshot_id": "SNAP-TEST-002",
        "stocks": {"QUALITYDIP.NS": stock_data},
        "regime": {"composite": 0.0, "label": "NEUTRAL", "dimensions": {"risk": "NEUTRAL"}},
    }

    proposals = agent.evaluate_market(
        market_snapshot=market_snap,
        current_open_positions=[],
        current_equity=2000000.0,
        current_cash=2000000.0,
    )

    assert len(proposals) >= 1
    p = proposals[0]
    # Trade proposal should be generated with BUY direction
    assert p.action.value in ("BUY", "OPEN") or p.direction.value == "BUY"


# ---------------------------------------------------------------------------
# Test 10: Momentum + contradictory fundamentals
# ---------------------------------------------------------------------------
def test_momentum_contradictory_fundamentals():
    """Verify that contradictory fundamentals do not kill a valid momentum breakout."""
    agent = AgentMomentum()
    # Deterministic AI response for testing fundamental contradiction preservation
    agent.llm_provider.generate_decision_thesis = lambda *args, **kwargs: {
        "status": "SUCCESS",
        "ai_status": "INFERENCE_SUCCESS",
        "direction": "BULLISH",
        "expected_move_pct": 1.50,
        "horizon": "1D",
        "confidence": 65.0,
        "catalysts": ["Momentum breakout"],
        "invalidating_conditions": ["Break below 20 EMA"],
        "reasoning": "Tactical trend breakout",
        "decision_mode": "AI_INFERENCE",
        "evaluation_status": "EVALUABLE",
    }
    now_dt = datetime.now(timezone.utc)

    speculative_fund = FundamentalSnapshot(
        symbol="MOMENTUM_RUNNER.NS",
        as_of=now_dt - timedelta(days=15),
        source="TEST_FEED",
        valuation={"pe_ratio": 80.0},
        profitability={"roce_pct": 8.0},
        growth={"revenue_growth_yoy": 2.0},
        leverage={"debt_to_equity": 2.1},
        quality_score=32.0,
        valuation_score=15.0,
        fundamental_regime=FundamentalRegime.STRESSED.value,
    )

    stock_data = {
        "symbol": "MOMENTUM_RUNNER.NS",
        "base_price": 1200.0,
        "base_price_timestamp": now_dt.isoformat(),
        "conviction": 65.0,
        "momentum_5d_pct": 3.4,
        "predicted_1d_pct": 1.50,
        "sector": "Industrial",
        "beta": 1.2,
        "fundamental_snapshot": speculative_fund,
    }

    market_snap = {
        "snapshot_id": "SNAP-TEST-003",
        "stocks": {"MOMENTUM_RUNNER.NS": stock_data},
        "regime": {"composite": 0.1, "label": "BULLISH", "dimensions": {"risk": "NEUTRAL"}},
    }

    proposals = agent.evaluate_market(
        market_snapshot=market_snap,
        current_open_positions=[],
        current_equity=2000000.0,
        current_cash=2000000.0,
    )

    # Momentum proposal is preserved (not killed by fundamentals)
    assert len(proposals) >= 1
    p = proposals[0]
    assert p.symbol == "MOMENTUM_RUNNER.NS"
    assert "Caution noted" in p.decision_reason or "tactical trend momentum" in p.decision_reason


# ---------------------------------------------------------------------------
# Test 11: Fundamental regime calculation
# ---------------------------------------------------------------------------
def test_fundamental_regime_calculation():
    """Verify market-wide fundamental breadth and regime calculation."""
    now_dt = datetime.now(timezone.utc)
    mock_snapshots = {}

    # Create 35 healthy/high quality and 15 stressed
    for i in range(35):
        sym = f"HEALTHY_{i}.NS"
        mock_snapshots[sym] = FundamentalSnapshot(
            symbol=sym,
            as_of=now_dt,
            source="TEST",
            quality_score=75.0,
            growth_score=65.0,
            valuation_score=50.0,
            fundamental_regime=FundamentalRegime.HEALTHY.value,
        )

    for i in range(15):
        sym = f"STRESSED_{i}.NS"
        mock_snapshots[sym] = FundamentalSnapshot(
            symbol=sym,
            as_of=now_dt,
            source="TEST",
            quality_score=28.0,
            growth_score=25.0,
            valuation_score=20.0,
            fundamental_regime=FundamentalRegime.STRESSED.value,
        )

    breadth = FundamentalScoreEngine.compute_market_breadth_and_regime(mock_snapshots)

    assert breadth["total_equities"] == 50
    assert breadth["strong_quality_count"] == 35
    assert breadth["improving_growth_count"] == 35
    assert breadth["fundamentally_stressed_count"] == 15
    assert breadth["fundamental_regime"] in (FundamentalRegime.HEALTHY.value, FundamentalRegime.STRESSED.value, FundamentalRegime.MIXED.value)


# ---------------------------------------------------------------------------
# Test 12: Fundamental provenance hash
# ---------------------------------------------------------------------------
def test_fundamental_provenance_hash():
    """Verify that FundamentalSnapshot generates a deterministic SHA-256 provenance hash."""
    now_dt = datetime(2026, 9, 23, 15, 30, 0, tzinfo=timezone.utc)
    snap1 = FundamentalSnapshot(
        symbol="LT.NS",
        as_of=now_dt,
        source="NSE_MARKET_LENS",
        valuation={"pe_ratio": 32.5},
        profitability={"roce_pct": 18.2},
        quality_score=72.0,
    )

    snap2 = FundamentalSnapshot(
        symbol="LT.NS",
        as_of=now_dt,
        source="NSE_MARKET_LENS",
        valuation={"pe_ratio": 32.5},
        profitability={"roce_pct": 18.2},
        quality_score=72.0,
    )

    assert len(snap1.provenance_hash) == 64
    assert snap1.provenance_hash == snap2.provenance_hash

    # Tampering test
    snap2.valuation["pe_ratio"] = 45.0
    assert snap1.provenance_hash != snap2.compute_provenance_hash()


# ---------------------------------------------------------------------------
# Test 13: Replay produces identical snapshot
# ---------------------------------------------------------------------------
def test_replay_produces_identical_snapshot():
    """Verify that PointInTimeSnapshot replay with identical timestamps produces identical provenance hash."""
    p_ts = datetime(2026, 9, 23, 18, 15, 0, tzinfo=timezone.utc)
    mp_ts = datetime(2026, 9, 23, 15, 30, 0, tzinfo=timezone.utc)
    f_ts = datetime(2026, 9, 23, 15, 35, 12, tzinfo=timezone.utc)

    f_snap = FundamentalSnapshot(
        symbol="LT.NS",
        as_of=f_ts,
        source="NSE_MARKET_LENS",
        quality_score=75.0,
    )

    pit1 = PointInTimeSnapshot(
        symbol="LT.NS",
        market_price=3929.90,
        market_price_as_of=mp_ts,
        prediction_timestamp=p_ts,
        fundamental_snapshot=f_snap,
        fundamental_as_of=f_ts,
        macro_snapshot={"label": "NEUTRAL"},
    )

    pit2 = PointInTimeSnapshot(
        symbol="LT.NS",
        market_price=3929.90,
        market_price_as_of=mp_ts,
        prediction_timestamp=p_ts,
        fundamental_snapshot=f_snap,
        fundamental_as_of=f_ts,
        macro_snapshot={"label": "NEUTRAL"},
    )

    assert pit1.snapshot_id == pit2.snapshot_id
    assert pit1.provenance_hash == pit2.provenance_hash

    # Validate causality
    is_valid, errors = pit1.validate_causality()
    assert is_valid
    assert len(errors) == 0


# ---------------------------------------------------------------------------
# Test 14: Fundamental data cannot bypass TradeGuard
# ---------------------------------------------------------------------------
def test_fundamental_cannot_bypass_tradeguard():
    """Verify that even with 100 quality score, stale base price is rejected by Gate 0.1 / TradeGuard."""
    selector = InstrumentSelector()
    now_dt = datetime.now(timezone.utc)
    stale_dt = now_dt - timedelta(seconds=600)  # 10 minutes old (>300s)

    perfect_fund = FundamentalSnapshot(
        symbol="TCS.NS",
        as_of=now_dt - timedelta(days=10),
        source="NSE_MARKET_LENS",
        quality_score=100.0,
        fundamental_regime=FundamentalRegime.HEALTHY.value,
    )

    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="TCS.NS",
        direction="BULLISH",
        expected_move_pct=1.50,
        horizon="1D",
        confidence=80.0,
        catalysts=["Major deal win"],
        invalidating_conditions=["Deal canceled"],
        reasoning="Deal catalyst with perfect quality fundamentals.",
        fundamental_context=FundamentalContext(
            quality_score=100.0,
            confirmation=True,
        ),
    )

    stock_data = {
        "symbol": "TCS.NS",
        "base_price": 4120.0,
        "base_price_timestamp": stale_dt.isoformat(),
        "sector": "Information Technology",
        "beta": 0.85,
        "fundamental_snapshot": perfect_fund,
    }

    trade = selector.select_instrument(
        thesis=thesis,
        stock_data=stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
        decision_timestamp=now_dt,
    )

    assert trade.action.value == "NO_TRADE"
    assert "STALE_BASE_PRICE" in trade.decision_reason


# ---------------------------------------------------------------------------
# Test 15: Fundamental data cannot force a trade
# ---------------------------------------------------------------------------
def test_fundamental_cannot_force_trade():
    """Verify that perfect fundamentals cannot force a trade if raw trading edge < hurdle (0.35%)."""
    selector = InstrumentSelector()
    now_dt = datetime.now(timezone.utc)

    perfect_fund = FundamentalSnapshot(
        symbol="INFY.NS",
        as_of=now_dt - timedelta(days=10),
        source="NSE_MARKET_LENS",
        quality_score=100.0,
        fundamental_regime=FundamentalRegime.HEALTHY.value,
    )

    # Sub-hurdle move (+0.20% < 0.35%)
    sub_hurdle_thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="INFY.NS",
        direction="BULLISH",
        expected_move_pct=0.20,
        horizon="1D",
        confidence=85.0,
        catalysts=["Minor contract extension"],
        invalidating_conditions=["Contract delay"],
        reasoning="Tiny expected edge with perfect fundamental backing.",
        fundamental_context=FundamentalContext(
            quality_score=100.0,
            confirmation=True,
        ),
    )

    stock_data = {
        "symbol": "INFY.NS",
        "base_price": 1850.0,
        "base_price_timestamp": now_dt.isoformat(),
        "sector": "Information Technology",
        "beta": 0.90,
        "fundamental_snapshot": perfect_fund,
    }

    trade = selector.select_instrument(
        thesis=sub_hurdle_thesis,
        stock_data=stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
        decision_timestamp=now_dt,
    )

    assert trade.action.value == "NO_TRADE"
    assert "below net edge hurdle" in trade.decision_reason


# ---------------------------------------------------------------------------
# Test 16: Future fundamental publication rejection
# ---------------------------------------------------------------------------
def test_future_fundamental_publication_rejection():
    """Verify that fundamental_as_of > prediction_timestamp is strictly rejected as a causal violation."""
    p_ts = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)
    future_f_ts = datetime(2026, 9, 23, 10, 30, 0, tzinfo=timezone.utc)
    now_mp_ts = datetime(2026, 9, 23, 9, 58, 0, tzinfo=timezone.utc)

    f_snap = FundamentalSnapshot(
        symbol="RELIANCE.NS",
        as_of=future_f_ts,
        source="NSE_OFFICIAL_EXPORT",
        quality_score=80.0,
    )

    pit = PointInTimeSnapshot(
        symbol="RELIANCE.NS",
        market_price=2950.0,
        market_price_as_of=now_mp_ts,
        prediction_timestamp=p_ts,
        fundamental_snapshot=f_snap,
        fundamental_as_of=future_f_ts,
    )

    is_valid, errors = pit.validate_causality()
    assert not is_valid
    assert any("FUNDAMENTAL_FUTURE" in err for err in errors)


# ---------------------------------------------------------------------------
# Test 17: Sector normalization
# ---------------------------------------------------------------------------
def test_sector_normalization():
    """Verify that the same raw metric (e.g. D/E=3.5) yields different normalized interpretations across sectors."""
    from event_agent.fundamentals.fundamental_normalizer import FundamentalNormalizer

    raw_leverage = {"debt_to_equity": 3.5, "interest_coverage": 3.0}

    # For Financial Services / Bank, D/E of 3.5 is normal operating liability structure -> healthy score
    bank_leverage_score = FundamentalNormalizer.normalize_leverage(
        raw_leverage, sector="Financial Services"
    )

    # For Information Technology, D/E of 3.5 is abnormal / deeply distressed -> stressed score
    it_leverage_score = FundamentalNormalizer.normalize_leverage(
        raw_leverage, sector="Information Technology"
    )

    assert bank_leverage_score >= 60.0, f"Expected bank score >= 60, got {bank_leverage_score}"
    assert it_leverage_score < 20.0, f"Expected IT score < 20, got {it_leverage_score}"
    assert bank_leverage_score > it_leverage_score + 40.0


# ---------------------------------------------------------------------------
# Test 18: Fundamental shadow-vs-live separation
# ---------------------------------------------------------------------------
def test_fundamental_shadow_vs_live_separation():
    """Verify that execution edge is strictly unmodified while shadow edge captures fundamental adjustment."""
    selector = InstrumentSelector()
    now_dt = datetime.now(timezone.utc)
    base_price = 2000.0

    # Strong fundamentals giving positive boost
    strong_fund = FundamentalSnapshot(
        symbol="TCS.NS",
        as_of=now_dt - timedelta(days=20),
        source="REFERENCE_DATASET",
        data_mode="REFERENCE_ONLY",
        trade_eligible=False,
        financial_period="Q1 FY27",
        quality_score=90.0,
        fundamental_regime=FundamentalRegime.HEALTHY.value,
    )

    raw_trading_edge = 0.62  # +0.62%

    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="TCS.NS",
        direction="BULLISH",
        expected_move_pct=raw_trading_edge,
        horizon="1D",
        confidence=80.0,
        catalysts=["Major digital cloud contract win"],
        invalidating_conditions=["Contract delay or regulatory probe"],
        reasoning="Contract catalyst with high-conviction alpha.",
        fundamental_context=FundamentalContext(
            quality_score=90.0,
            confirmation=True,
            contradiction=False,
            source="REFERENCE_DATASET",
            data_mode="REFERENCE_ONLY",
            trade_eligible=False,
        ),
    )

    stock_data = {
        "symbol": "TCS.NS",
        "base_price": base_price,
        "base_price_timestamp": now_dt.isoformat(),
        "sector": "Information Technology",
        "beta": 0.85,
        "fundamental_snapshot": strong_fund,
    }

    trade = selector.select_instrument(
        thesis=thesis,
        stock_data=stock_data,
        portfolio_equity=2000000.0,
        current_open_positions=[],
        decision_timestamp=now_dt,
    )

    assert trade.action.value != "NO_TRADE"
    assert trade.execution_edge == raw_trading_edge
    assert trade.fundamental_adj is not None and trade.fundamental_adj > 0.0
    assert trade.shadow_adjusted_edge is not None and trade.execution_edge is not None
    assert trade.shadow_adjusted_edge > trade.execution_edge
    assert abs(trade.shadow_adjusted_edge - (raw_trading_edge + trade.fundamental_adj)) < 1e-4

    # Target price MUST be calculated strictly against execution_edge (0.62%), NOT shadow edge
    expected_target = round(base_price * (1.0 + raw_trading_edge / 100.0), 2)
    assert trade.target == expected_target

