from datetime import datetime, timezone

from event_agent.arena.asset_models import StrategyType
from event_agent.arena.instrument_selector import InstrumentSelector
from event_agent.arena.models import RiskEvaluation
from event_agent.arena.options_engine import OptionsStrategyBuilder
from event_agent.arena.thesis_validator import MarketThesis
from event_agent.arena.multi_agent_broker import MultiAgentBroker
from event_agent.broker.broker_adapter import InternalPaperBroker


def test_option_selection_returns_executable_strategy():
    now = datetime.now(timezone.utc)
    thesis = MarketThesis(
        agent_id="ALPHA",
        symbol="LT.NS",
        direction="BULLISH",
        expected_move_pct=1.8,
        horizon="1D",
        confidence=80.0,
        catalysts=["validated catalyst"],
        invalidating_conditions=["invalidated thesis"],
        reasoning="validated thesis",
    )

    proposal = InstrumentSelector().select_instrument(
        thesis=thesis,
        stock_data={
            "base_price": 3500.0,
            "base_price_timestamp": now.isoformat(),
            "sector": "Industrials",
            "beta": 1.0,
        },
        portfolio_equity=2_000_000.0,
        current_open_positions=[],
        snapshot_id="SNAP-REGRESSION",
        decision_timestamp=now,
    )

    assert proposal.instrument.instrument_type.value == "OPTION"
    assert proposal.strategy is not None
    assert proposal.strategy.strategy_type == StrategyType.LONG_CALL
    assert proposal.strategy.legs
    assert proposal.strategy.legs[0].entry_price > 0


def test_strategy_execution_creates_filled_leg_orders(monkeypatch):
    persisted_orders = []
    persisted_strategies = []
    monkeypatch.setattr(
        "event_agent.storage.ledger.save_order",
        lambda order: persisted_orders.append(order),
    )
    monkeypatch.setattr(
        "event_agent.storage.ledger.save_agent_strategy",
        lambda strategy: persisted_strategies.append(strategy),
    )

    broker = MultiAgentBroker(
        broker_adapter=InternalPaperBroker(),
        auto_hydrate=False,
    )
    strategy = OptionsStrategyBuilder.create_long_call(
        underlying="LT.NS",
        spot_price=3500.0,
        strike=3500.0,
        lot_size=50,
        quantity=50,
        agent_id="ALPHA",
        snapshot_id="SNAP-REGRESSION",
    )
    approved = RiskEvaluation(is_approved=True, adjusted_quantity=50)

    success, reason, executed = broker.execute_approved_strategy(
        strategy=strategy,
        evaluation=approved,
        market_date="2026-09-25",
    )

    assert success is True
    assert reason == "EXECUTED"
    assert executed is strategy
    assert strategy.status.value == "OPEN"
    assert len(broker.orders) == 1
    order = next(iter(broker.orders.values()))
    assert order.status.value == "FILLED"
    assert order.strategy_id == strategy.strategy_id
    assert order.symbol == strategy.legs[0].instrument.symbol
    assert persisted_orders and persisted_orders[0]["status"] == "FILLED"
    assert persisted_strategies and persisted_strategies[0]["status"] == "OPEN"
