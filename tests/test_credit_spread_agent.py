# =============================================================================
# tests/test_credit_spread_agent.py — NIFTY 50 Credit Spread Agent Test Suite
# =============================================================================
"""
Unit and Integration Test Suite for the Autonomous NIFTY 50 Credit Spread Agent:
1. Delta-Based Strike Selection (0.25-0.30 target delta)
2. Strict Hedged Invariant (Never Naked Option Writing)
3. Net Credit Validation (Premium Collected > Premium Paid)
4. Capital & Sizing Limits (₹1.2L capital, 2 lots max, ₹40k buffer, ₹2,400 max risk)
5. Risk Gates & DTE Invariants (3-7 DTE window, 0 DTE strictly prohibited)
6. Volatility Width Expansion (VIX > 20 expands width to 200 pts)
7. Exit Mechanics (Stop-Loss at 50% expansion / ₹2,400 cutoff; Take-Profit at 80%)
8. Terminal Execution Logging String Format Compliance
9. End-to-End Arena Cycle Integration & Leaderboard Accounting
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from event_agent.arena.agents.agent_credit_spread import AgentCreditSpread
from event_agent.arena.asset_models import (
    LegSide,
    MultiLegStrategy,
    OptionChain,
    OptionInstrument,
    OptionType,
    StrategyLeg,
    StrategyStatus,
    StrategyType,
)
from event_agent.arena.models import (
    Instrument,
    InstrumentType,
    ProposedTrade,
    RiskEvaluation,
    TradeAction,
    TradeDirection,
)
from event_agent.arena.multi_agent_broker import MultiAgentBroker
from event_agent.arena.option_chain_provider import OptionChainProvider, OptionDataMode
from event_agent.arena.options_engine import (
    DEFAULT_LOT_SIZE,
    OptionsPricingEngine,
    OptionsStrategyBuilder,
)
from event_agent.arena.orchestrator import ArenaOrchestrator
from event_agent.arena.risk_engine import RiskEngine
from event_agent.broker.broker_adapter import InternalPaperBroker


@pytest.fixture
def agent():
    return AgentCreditSpread()


@pytest.fixture
def option_chain():
    provider = OptionChainProvider(default_mode=OptionDataMode.MODELLED)
    chain, _ = provider.get_chain(
        underlying="^NSEI",
        spot_price=25000.0,
        expiry="7D",
        days_to_expiry=7,
        implied_volatility=0.15,
    )
    return chain


def test_agent_profile_and_capital_limits(agent):
    """Verifies institutional profile invariants and capital sizing limits."""
    assert agent.agent_id == "CREDIT_SPREAD"
    assert agent.profile.starting_capital == 120_000.0
    assert agent.TOTAL_ALLOCATED_CAPITAL == 120_000.0
    assert agent.MARGIN_PER_HEDGED_LOT == 40_000.0
    assert agent.MAX_LOT_SIZE == 2
    assert agent.BUFFER_CAPITAL == 40_000.0
    assert agent.MAX_RISK_PER_TRADE == 2_400.0
    assert agent.MIN_DTE == 3
    assert agent.MAX_DTE == 7
    assert agent.TARGET_PROFIT_RATIO == 0.80
    assert agent.STOP_LOSS_RATIO == 0.50


def test_delta_based_strike_selection_bear_call(option_chain):
    """Condition A: Identifies OTM Call with Delta ~0.25 to 0.30 and 100 pt hedge."""
    spot = 25000.0
    sell_k, buy_k, width = OptionsStrategyBuilder.select_credit_spread_strikes(
        chain=option_chain,
        is_call=True,
        spot_price=spot,
        vix=15.0,
        target_delta=0.275,
    )

    assert sell_k > spot, "Bear Call sell strike must be Out-of-the-Money"
    assert buy_k == sell_k + 100.0, "Buy leg must be 100 points higher than sell leg when VIX <= 20"
    assert width == 100.0

    # Verify delta of sell leg is near 0.25 to 0.30
    sell_inst = next(s.call for s in option_chain.strikes if s.strike == sell_k)
    assert 0.18 <= sell_inst.delta <= 0.38


def test_delta_based_strike_selection_bull_put(option_chain):
    """Condition B: Identifies OTM Put with Delta ~ -0.25 to -0.30 and 100 pt hedge."""
    spot = 25000.0
    sell_k, buy_k, width = OptionsStrategyBuilder.select_credit_spread_strikes(
        chain=option_chain,
        is_call=False,
        spot_price=spot,
        vix=15.0,
        target_delta=0.275,
    )

    assert sell_k < spot, "Bull Put sell strike must be Out-of-the-Money"
    assert buy_k == sell_k - 100.0, "Buy leg must be 100 points lower than sell leg when VIX <= 20"
    assert width == 100.0

    # Verify delta of sell leg is near -0.25 to -0.30
    sell_inst = next(s.put for s in option_chain.strikes if s.strike == sell_k)
    assert -0.38 <= sell_inst.delta <= -0.18


def test_vix_greater_than_20_widens_spread_to_200():
    """VIX Check: If India VIX > 20, widen spread width to 200 points."""
    provider = OptionChainProvider(default_mode=OptionDataMode.MODELLED)
    chain, _ = provider.get_chain(
        underlying="^NSEI",
        spot_price=25000.0,
        expiry="7D",
        days_to_expiry=7,
        implied_volatility=0.24,
    )
    sell_k, buy_k, width = OptionsStrategyBuilder.select_credit_spread_strikes(
        chain=chain,
        is_call=True,
        spot_price=25000.0,
        vix=24.5,
        target_delta=0.275,
    )
    assert width == 200.0
    assert buy_k == sell_k + 200.0

    # For put side as well
    sell_kp, buy_kp, width_p = OptionsStrategyBuilder.select_credit_spread_strikes(
        chain=chain,
        is_call=False,
        spot_price=25000.0,
        vix=22.0,
        target_delta=0.275,
    )
    assert width_p == 200.0
    assert buy_kp == sell_kp - 200.0


def test_net_credit_and_strategy_construction_bear_call():
    """Validates Bear Call Spread construction: Premium Collected > Premium Paid."""
    strat = OptionsStrategyBuilder.create_bear_call_spread(
        underlying="^NSEI",
        spot_price=25000.0,
        sell_strike=25300.0,
        buy_strike=25400.0,
        expiry_days=7,
        volatility=0.15,
        lot_size=50,
        quantity=100,  # 2 lots
        agent_id="CREDIT_SPREAD",
    )

    assert strat.strategy_type == StrategyType.BEAR_CALL_SPREAD
    assert len(strat.legs) == 2
    sell_leg = next(leg for leg in strat.legs if leg.side == LegSide.SELL)
    buy_leg = next(leg for leg in strat.legs if leg.side == LegSide.BUY)

    assert sell_leg.instrument.option_type == OptionType.CE
    assert buy_leg.instrument.option_type == OptionType.CE
    assert sell_leg.entry_price > buy_leg.entry_price, "Sell premium must exceed buy premium"
    assert strat.net_credit > 0, "Trade must result in positive Net Credit"
    assert strat.max_profit == strat.net_credit, "Max profit must equal net credit collected"
    assert strat.max_loss <= 2400.0, "Max loss must be strictly capped at ₹2,400"
    assert strat.stop_loss_amount <= 2400.0, "Stop loss must not exceed ₹2,400 limit"
    assert strat.target_profit_amount == round(strat.max_profit * 0.80, 2)
    assert strat.net_debit == 80_000.0, "Net debit stores the ₹80,000 margin for 2 lots"


def test_net_credit_and_strategy_construction_bull_put():
    """Validates Bull Put Spread construction: Premium Collected > Premium Paid."""
    strat = OptionsStrategyBuilder.create_bull_put_spread(
        underlying="^NSEI",
        spot_price=25000.0,
        sell_strike=24700.0,
        buy_strike=24600.0,
        expiry_days=7,
        volatility=0.15,
        lot_size=50,
        quantity=100,  # 2 lots
        agent_id="CREDIT_SPREAD",
    )

    assert strat.strategy_type == StrategyType.BULL_PUT_SPREAD
    assert len(strat.legs) == 2
    sell_leg = next(leg for leg in strat.legs if leg.side == LegSide.SELL)
    buy_leg = next(leg for leg in strat.legs if leg.side == LegSide.BUY)

    assert sell_leg.instrument.option_type == OptionType.PE
    assert buy_leg.instrument.option_type == OptionType.PE
    assert sell_leg.entry_price > buy_leg.entry_price
    assert strat.net_credit > 0
    assert strat.max_profit == strat.net_credit
    assert strat.max_loss <= 2400.0
    assert strat.target_profit_amount == round(strat.max_profit * 0.80, 2)
    assert strat.net_debit == 80_000.0


def test_terminal_output_string_format(agent):
    """Outputs exactly in the required terminal format."""
    log_line = agent.format_execution_log(
        strategy_name="Bull Put",
        sell_strike=24700.0,
        sell_type="PE",
        sell_ltp=45.20,
        buy_strike=24600.0,
        buy_type="PE",
        buy_ltp=22.10,
        net_credit=2310.00,
        max_profit=2310.00,
        max_risk=2400.00,
    )
    expected = "[ACTION: EXECUTE] STRATEGY: Bull Put | SELL: 24700 PE @ 45.20 | BUY: 24600 PE @ 22.10 | NET CREDIT: ₹2310.00 | MAX PROFIT: ₹2310.00 | MAX RISK: ₹2400.00"
    assert log_line == expected


def test_risk_gate_rejects_zero_dte(agent):
    """DTE Gate: Rejects trades on Expiry Day (0 DTE) to avoid gamma spikes."""
    snapshot = {
        "snapshot_id": "SNAP-0DTE",
        "market_view": "BEARISH",
        "days_to_expiry": 0,
        "stocks": {"^NSEI": {"base_price": 25000.0}},
    }
    proposals = agent.evaluate_market(
        market_snapshot=snapshot,
        current_open_positions=[],
        current_equity=120_000.0,
        current_cash=120_000.0,
    )
    assert len(proposals) == 1
    assert proposals[0].action == TradeAction.NO_TRADE
    assert "0 DTE" in proposals[0].decision_reason


def test_risk_gate_rejects_dte_outside_window(agent):
    """DTE Gate: Rejects trades with DTE < 3 or DTE > 7."""
    snapshot = {
        "snapshot_id": "SNAP-2DTE",
        "market_view": "BULLISH",
        "days_to_expiry": 2,
        "stocks": {"^NSEI": {"base_price": 25000.0}},
    }
    proposals = agent.evaluate_market(
        market_snapshot=snapshot,
        current_open_positions=[],
        current_equity=120_000.0,
        current_cash=120_000.0,
    )
    assert proposals[0].action == TradeAction.NO_TRADE
    assert "DTE Gate" in proposals[0].decision_reason


def test_risk_engine_blocks_naked_option():
    """RiskEngine strictly rejects naked (unhedged) short option writing."""
    risk_engine = RiskEngine()
    calc = OptionsPricingEngine.calculate_price_and_greeks(
        spot=25000.0, strike=25300.0, time_to_expiry_years=7/365.0, volatility=0.15, is_call=True
    )
    opt_inst = OptionInstrument(
        underlying="^NSEI", strike=25300.0, option_type=OptionType.CE,
        expiry="7D", lot_size=50, model_price=calc["price"],
        delta=calc["delta"], gamma=calc["gamma"], theta=calc["theta"], vega=calc["vega"]
    )
    # Naked short leg
    naked_leg = StrategyLeg(
        leg_id="LEG-NAKED", instrument=opt_inst, side=LegSide.SELL,
        ratio=1, quantity=100, entry_price=calc["price"], current_price=calc["price"]
    )
    naked_strategy = MultiLegStrategy(
        strategy_id="STRAT-NAKED",
        strategy_type=StrategyType.BEAR_CALL_SPREAD,
        underlying="^NSEI",
        expiry="7D",
        legs=[naked_leg],  # Missing protective long leg!
        net_debit=80000.0,
        max_profit=2000.0,
        max_loss=2400.0,
        breakeven=[25320.0],
        risk_reward_ratio=1.0,
        net_delta=-25.0,
        net_gamma=0.0,
        net_theta=10.0,
        net_vega=-5.0,
        agent_id="CREDIT_SPREAD",
        net_credit=2000.0,
    )

    eval_result = risk_engine.evaluate_strategy(
        strategy=naked_strategy,
        agent_equity=120_000.0,
        agent_cash=120_000.0,
        current_open_strategies=[],
        daily_starting_equity=120_000.0,
        check_market_clock=False,
    )
    assert eval_result.is_approved is False
    assert "NAKED_OPTION_PROHIBITED" in eval_result.rejection_reason


def test_risk_engine_blocks_oversized_lots():
    """RiskEngine rejects credit spreads exceeding 2-lot maximum ceiling."""
    risk_engine = RiskEngine()
    oversized = OptionsStrategyBuilder.create_bear_call_spread(
        underlying="^NSEI",
        spot_price=25000.0,
        sell_strike=25300.0,
        buy_strike=25400.0,
        expiry_days=7,
        volatility=0.15,
        lot_size=50,
        quantity=150,  # 3 lots! Exceeds 2-lot ceiling
        agent_id="CREDIT_SPREAD",
    )

    eval_result = risk_engine.evaluate_strategy(
        strategy=oversized,
        agent_equity=120_000.0,
        agent_cash=120_000.0,
        current_open_strategies=[],
        daily_starting_equity=120_000.0,
        check_market_clock=False,
    )
    assert eval_result.is_approved is False
    assert "MAX_LOT_SIZE_EXCEEDED" in eval_result.rejection_reason


def test_mark_to_market_stop_loss_trigger():
    """Stop-loss circuit breaker triggers when loss reaches 50% credit expansion / ₹2,400."""
    broker = MultiAgentBroker(
        broker_adapter=InternalPaperBroker(),
        auto_hydrate=False,
    )
    strat = OptionsStrategyBuilder.create_bear_call_spread(
        underlying="^NSEI",
        spot_price=25000.0,
        sell_strike=25300.0,
        buy_strike=25400.0,
        expiry_days=7,
        volatility=0.15,
        lot_size=50,
        quantity=100,
        agent_id="CREDIT_SPREAD",
    )
    approved = RiskEvaluation(is_approved=True, adjusted_quantity=100)
    success, reason, executed = broker.execute_approved_strategy(
        strategy=strat,
        evaluation=approved,
        market_date="2026-10-02",
    )
    assert success is True
    sub_port = broker.get_agent_portfolio("CREDIT_SPREAD")
    assert "STRAT-BCALL" in next(iter(sub_port.open_strategies.keys()))
    assert abs(sub_port.cash - 40_000.0) < 50.0, "₹80,000 margin reserved from cash, reserving ~₹40,000 buffer capital"

    # Spot spikes past strikes to 25,600 (huge adverse move against Bear Call)
    broker.mark_to_market_strategies(
        underlying_prices={"^NSEI": 25600.0},
        expiry_days_remaining=5,
    )

    # Strategy should have hit stop loss and closed automatically
    assert len(sub_port.open_strategies) == 0
    assert len(sub_port.closed_strategies) == 1
    closed_strat = sub_port.closed_strategies[0]
    assert closed_strat.status == StrategyStatus.STOPPED_OUT
    assert closed_strat.exit_reason == "STOP_LOSS_TRIGGERED"
    # Cash returned was margin plus realized PnL
    assert sub_port.cash > 0


def test_mark_to_market_take_profit_trigger():
    """Take-profit triggers automatically when position achieves 80% of max profit."""
    broker = MultiAgentBroker(
        broker_adapter=InternalPaperBroker(),
        auto_hydrate=False,
    )
    strat = OptionsStrategyBuilder.create_bull_put_spread(
        underlying="^NSEI",
        spot_price=25000.0,
        sell_strike=24700.0,
        buy_strike=24600.0,
        expiry_days=7,
        volatility=0.15,
        lot_size=50,
        quantity=100,
        agent_id="CREDIT_SPREAD",
    )
    approved = RiskEvaluation(is_approved=True, adjusted_quantity=100)
    broker.execute_approved_strategy(
        strategy=strat,
        evaluation=approved,
        market_date="2026-10-02",
    )
    sub_port = broker.get_agent_portfolio("CREDIT_SPREAD")

    # Spot moves favorably to 25,400 with 1 day to expiry -> both OTM puts decay to near 0
    broker.mark_to_market_strategies(
        underlying_prices={"^NSEI": 25400.0},
        expiry_days_remaining=1,
    )

    # Strategy should have hit take profit at 80% gain and freed margin
    assert len(sub_port.open_strategies) == 0
    assert len(sub_port.closed_strategies) == 1
    closed_strat = sub_port.closed_strategies[0]
    assert closed_strat.status == StrategyStatus.TARGET_REACHED
    assert closed_strat.exit_reason == "TARGET_PROFIT_REACHED"
    assert sub_port.realized_pnl > 0


def test_orchestrator_end_to_end_cycle_with_credit_spread(monkeypatch):
    """Full end-to-end Arena Orchestrator cycle executing Credit Spread Agent."""
    # Mock database persistence
    monkeypatch.setattr("event_agent.storage.ledger.save_agent_strategy", lambda s: None)
    monkeypatch.setattr("event_agent.storage.ledger.save_agent_portfolio", lambda p: None)
    monkeypatch.setattr("event_agent.storage.ledger.save_agent_position", lambda p: None)
    monkeypatch.setattr("event_agent.storage.ledger.save_agent_decision", lambda d: None)
    monkeypatch.setattr("event_agent.storage.ledger.save_agent_daily_snapshot", lambda s: None)
    monkeypatch.setattr("event_agent.storage.ledger.save_order", lambda o: None)
    monkeypatch.setattr("event_agent.storage.supabase_ledger.save_arena_state_supabase", lambda s: None)

    broker = MultiAgentBroker(broker_adapter=InternalPaperBroker(), auto_hydrate=False)
    orchestrator = ArenaOrchestrator(broker=broker)

    # Ingest a Bearish Market View on NIFTY
    regime = {
        "label": "BEARISH",
        "composite": -0.35,
        "india_vix": 16.5,
        "dimensions": {
            "risk": "RISK_OFF",
            "monetary": "HAWKISH",
            "inflation": "ELEVATED",
            "growth": "CONTRACTION",
            "volatility": "NORMAL",
        },
    }

    result = orchestrator.run_cycle(
        market_date="2026-10-02",
        regime_data=regime,
        force_execute=True,
        execute_trades=True,
    )

    # Check portfolios in cycle summary
    portfolios = result["portfolios"]
    assert "CREDIT_SPREAD" in portfolios
    cs_portfolio = portfolios["CREDIT_SPREAD"]
    assert cs_portfolio["starting_capital"] == 120_000.0

    # Verify executed trade log contains Credit Spread execution
    decisions = result["decisions"]
    cs_decisions = [d for d in decisions if d["agent_id"] == "CREDIT_SPREAD"]
    assert len(cs_decisions) >= 1
    assert cs_decisions[0]["action"] == "BUY"
    assert "Bear Call" in cs_decisions[0]["reason"]
    assert cs_decisions[0]["risk_approved"] == 1
