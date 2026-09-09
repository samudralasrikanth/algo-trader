"""
test_paper_trading_v2.py — Comprehensive Test Suite for NEXUS Realistic Paper Trading V2.
"""

import pytest
from datetime import datetime, timezone, timedelta

# Adapters & Reconciler
from event_agent.adapters.market_data_adapter import YFinanceProvider, DataQuality
from event_agent.adapters.nse_adapter import NSEPublicAdapter
from event_agent.data.reconciler import MarketDataReconciler, ReconciledQuote

# Historical Universe
from event_agent.data.historical_universe import HistoricalUniverseManager

# Orders & Broker
from event_agent.broker.order import Order, OrderStatus, OrderType, OrderSide, OrderFill
from event_agent.broker.broker_adapter import InternalPaperBroker, UpstoxSandboxAdapter
from event_agent.broker.execution_simulator import ExecutionSimulator, simulate_order_execution

# Arena Models & Multi-Agent Broker
from event_agent.arena.models import ProposedTrade, InstrumentType
from event_agent.arena.multi_agent_broker import MultiAgentBroker

# Engines
from event_agent.engine.calibration import calibrate_confidence
from event_agent.arena.ensemble_engine import EnsembleEngine
from event_agent.backtest.walk_forward import WalkForwardEngine
from event_agent.engine.event_intelligence import EventIntelligenceEngine
from event_agent.engine.llm_provider import HeuristicEventParser


# --------------------------------------------------------------------------
# 1. Market Data Envelope & Freshness
# --------------------------------------------------------------------------
def test_market_data_canonical_envelope():
    provider = YFinanceProvider()
    quote = provider.get_quote("TCS.NS")
    assert quote["symbol"] == "TCS.NS"
    assert quote["price"] > 0
    assert "market_timestamp" in quote
    assert "ingestion_timestamp" in quote
    assert "freshness_seconds" in quote
    assert "quality" in quote
    assert quote["source"] == "yfinance"


def test_market_data_freshness_states():
    now = datetime.now(timezone.utc)
    provider = YFinanceProvider()

    # Case 1: Fresh (10s)
    q1 = provider._format_quote("INFY.NS", 1850.0, now - timedelta(seconds=10))
    assert q1["quality"] == DataQuality.FRESH.value
    assert q1["freshness_seconds"] <= 60

    # Case 2: Stale (120s)
    q2 = provider._format_quote("INFY.NS", 1850.0, now - timedelta(seconds=120))
    assert q2["quality"] == DataQuality.STALE.value

    # Case 3: Degraded (600s)
    q3 = provider._format_quote("INFY.NS", 1850.0, now - timedelta(seconds=600))
    assert q3["quality"] == DataQuality.DEGRADED.value

    # Case 4: Invalid (1800s)
    q4 = provider._format_quote("INFY.NS", 1850.0, now - timedelta(seconds=1800))
    assert q4["quality"] == DataQuality.INVALID.value


# --------------------------------------------------------------------------
# 2. Dual-Source Reconciler & Discrepancy Logging
# --------------------------------------------------------------------------
def test_reconciler_agreement():
    reconciler = MarketDataReconciler()
    quote = reconciler.get_reconciled_quote("RELIANCE.NS")
    assert quote.symbol == "RELIANCE.NS"
    assert quote.price > 0
    assert quote.quality in [DataQuality.FRESH.value, DataQuality.STALE.value, DataQuality.DEGRADED.value]


def test_reconciler_discrepancy_logging():
    class MockPrimary:
        def get_quote(self, s):
            now = datetime.now(timezone.utc).isoformat()
            return {"symbol": s, "price": 1250.0, "market_timestamp": now, "ingestion_timestamp": now, "freshness_seconds": 5, "quality": "FRESH", "source": "yfinance"}

    class MockSecondary:
        def get_quote(self, s):
            now = datetime.now(timezone.utc).isoformat()
            return {"symbol": s, "price": 1251.0, "market_timestamp": now, "ingestion_timestamp": now, "freshness_seconds": 5, "quality": "FRESH", "source": "nse"}

    rec = MarketDataReconciler(primary_provider=MockPrimary(), secondary_provider=MockSecondary(), max_discrepancy_pct=0.05)
    quote = rec.get_reconciled_quote("TEST.NS")
    assert quote.price == 1250.0
    assert quote.discrepancy_detected is True
    assert quote.discrepancy_pct > 0.05
    assert len(rec.discrepancy_log) == 1
    assert rec.discrepancy_log[0]["symbol"] == "TEST.NS"


def test_nse_fallback_on_primary_failure():
    class FailingPrimary:
        def get_quote(self, s):
            raise ConnectionError("Primary feed down")

    class HealthySecondary:
        def get_quote(self, s):
            now = datetime.now(timezone.utc).isoformat()
            return {"symbol": s, "price": 4200.0, "market_timestamp": now, "ingestion_timestamp": now, "freshness_seconds": 12, "quality": "FRESH", "source": "nse"}

    rec = MarketDataReconciler(primary_provider=FailingPrimary(), secondary_provider=HealthySecondary())
    quote = rec.get_reconciled_quote("TCS.NS")
    assert quote.price == 4200.0
    assert quote.source == "nse (fallback)"


# --------------------------------------------------------------------------
# 3. Historical Universe PIT Manager
# --------------------------------------------------------------------------
def test_historical_universe_pit():
    mgr = HistoricalUniverseManager()
    
    # In 2018, YESBANK was in Nifty 50, TATACONSUM was not
    univ_2018 = mgr.get_universe_at_date("2018-05-01")
    assert "YESBANK.NS" in univ_2018
    assert "TATACONSUM.NS" not in univ_2018

    # In 2025, YESBANK is out, TATACONSUM is in
    univ_2025 = mgr.get_universe_at_date("2025-01-01")
    assert "YESBANK.NS" not in univ_2025
    assert "TATACONSUM.NS" in univ_2025
    assert len(univ_2025) == 50


# --------------------------------------------------------------------------
# 4. Order Lifecycle State Machine
# --------------------------------------------------------------------------
def test_order_lifecycle_valid_transitions():
    order = Order.create("ORD-1", "AGENT_A", "TCS.NS", OrderSide.BUY, OrderType.MARKET, 50, reference_price=4200.0)
    assert order.status == OrderStatus.CREATED

    order.submit()
    assert order.status == OrderStatus.SUBMITTED

    fill = OrderFill("F-1", "ORD-1", fill_price=4201.5, fill_quantity=50, slippage=1.5, charges=2.5, timestamp=datetime.now(timezone.utc).isoformat())
    order.apply_fill(fill)
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 50
    assert order.average_fill_price == 4201.5


def test_order_lifecycle_invalid_transition():
    order = Order.create("ORD-2", "AGENT_A", "TCS.NS", OrderSide.BUY, OrderType.MARKET, 50, reference_price=4200.0)
    order.submit()
    order.reject("Risk check failed")
    assert order.status == OrderStatus.REJECTED

    with pytest.raises(ValueError):
        order.submit()


# --------------------------------------------------------------------------
# 5. Non-Linear Slippage & Limit Order Condition
# --------------------------------------------------------------------------
def test_non_linear_slippage():
    sim = ExecutionSimulator()
    
    # Small size (100 shares out of 1M ADV)
    order_small = Order.create("ORD-S", "AGENT_A", "TCS.NS", OrderSide.BUY, OrderType.MARKET, 100, reference_price=4000.0)
    res_small = sim.simulate_order_execution(order_small, {"price": 4000.0}, daily_volatility=0.015, adv_shares=1000000.0)
    
    # Large size (50,000 shares out of 1M ADV)
    order_large = Order.create("ORD-L", "AGENT_A", "TCS.NS", OrderSide.BUY, OrderType.MARKET, 50000, reference_price=4000.0)
    res_large = sim.simulate_order_execution(order_large, {"price": 4000.0}, daily_volatility=0.015, adv_shares=1000000.0)

    assert res_small.status == OrderStatus.FILLED
    assert res_large.status == OrderStatus.FILLED
    slippage_per_share_small = (res_small.fill_price - 4000.0)
    slippage_per_share_large = (res_large.fill_price - 4000.0)
    assert slippage_per_share_large > slippage_per_share_small


def test_limit_order_condition():
    sim = ExecutionSimulator()
    # Buy Limit at 100: market at 105 should remain PENDING (not filled)
    order_unfilled = Order.create("ORD-U", "AGENT_A", "ABC.NS", OrderSide.BUY, OrderType.LIMIT, 10, reference_price=100.0, limit_price=100.0)
    res_unfilled = sim.simulate_order_execution(order_unfilled, {"price": 105.0})
    assert res_unfilled.status == OrderStatus.PENDING

    # Buy Limit at 100: market at 99 should FILL at <= 100
    order_filled = Order.create("ORD-F", "AGENT_A", "ABC.NS", OrderSide.BUY, OrderType.LIMIT, 10, reference_price=100.0, limit_price=100.0)
    res_filled = sim.simulate_order_execution(order_filled, {"price": 99.0})
    assert res_filled.status == OrderStatus.FILLED
    assert res_filled.fill_price <= 100.0


# --------------------------------------------------------------------------
# 6. Scale-In Weighted Average & Partial Exits
# --------------------------------------------------------------------------
def test_scale_in_and_partial_exit():
    broker = MultiAgentBroker()
    broker.create_portfolio("AGENT_TEST", initial_capital=2000000.0)

    # Buy 10 @ 100
    t1 = ProposedTrade.create_simple("AGENT_TEST", "XYZ.NS", "BUY", 10, 100.0, 90.0, 120.0, confidence=75)
    success1, _, pos1 = broker.execute_approved_trade(t1, fill_price=100.0)
    assert success1 is True
    assert pos1.quantity == 10
    assert pos1.entry_price == 100.0

    # Buy 10 more @ 110 -> Weighted Average = 105.0
    t2 = ProposedTrade.create_simple("AGENT_TEST", "XYZ.NS", "BUY", 10, 110.0, 90.0, 120.0, confidence=75, sequence=2)
    success2, _, pos2 = broker.execute_approved_trade(t2, fill_price=110.0)
    assert success2 is True
    assert pos2.quantity == 20
    assert pos2.entry_price == 105.0

    # Partial exit: close 10 shares @ 125 -> Realized P&L = 10 * (125 - 105) = +200
    res = broker.close_position("AGENT_TEST", "XYZ.NS", current_price=125.0, exit_quantity=10)
    assert res["status"] == "PARTIALLY_CLOSED"
    assert res["remaining_quantity"] == 10
    assert res["gross_pnl"] == 200.0
    assert round(res["realized_pnl"], 1) == 198.7  # ₹200 gross - ₹1.30 statutory fees

    port = broker.get_portfolio("AGENT_TEST")
    remaining_pos = port.positions["XYZ.NS"]
    assert remaining_pos.quantity == 10
    assert remaining_pos.entry_price == 105.0


# --------------------------------------------------------------------------
# 7. Confidence Calibration Guard (N < 30 -> INSUFFICIENT DATA)
# --------------------------------------------------------------------------
def test_confidence_calibration_insufficient_data():
    res = calibrate_confidence(0.75, historical_closed_trades=15)
    assert res["status"] == "INSUFFICIENT DATA"
    assert res["is_calibrated"] is False
    assert res["calibrated_confidence"] == 0.75

    res_valid = calibrate_confidence(0.75, historical_closed_trades=45)
    assert res_valid["status"] == "CALIBRATED"
    assert res_valid["is_calibrated"] is True


# --------------------------------------------------------------------------
# 8. Bayesian Ensemble & NO_TRADE Trigger
# --------------------------------------------------------------------------
def test_bayesian_ensemble_no_trade():
    engine = EnsembleEngine()

    # Conflicted proposals: 2 BUY, 2 SELL -> NO_TRADE
    proposals = [
        ProposedTrade.create_simple("MOMENTUM", "TCS.NS", "BUY", 20, 4200.0, 4100.0, 4400.0, confidence=60),
        ProposedTrade.create_simple("BREAKOUT", "TCS.NS", "BUY", 20, 4200.0, 4100.0, 4400.0, confidence=55),
        ProposedTrade.create_simple("MEAN_REV", "TCS.NS", "SELL", 20, 4200.0, 4300.0, 4000.0, confidence=65),
        ProposedTrade.create_simple("INSTITUTIONAL", "TCS.NS", "SELL", 20, 4200.0, 4300.0, 4000.0, confidence=60),
    ]
    ensemble_dec = engine.evaluate_proposals("TCS.NS", proposals)
    assert ensemble_dec["action"] == "NO_TRADE"
    assert "DISAGREEMENT" in ensemble_dec["reason"] or "CONFLICT" in ensemble_dec["reason"] or "ABSTAIN" in ensemble_dec["reason"]


# --------------------------------------------------------------------------
# 9. Broker Adapters (Internal & Upstox Sandbox)
# --------------------------------------------------------------------------
def test_broker_adapters():
    internal_broker = InternalPaperBroker()
    order = Order.create("ORD-TEST", "AGENT_A", "INFY.NS", OrderSide.BUY, OrderType.MARKET, 25, reference_price=1800.0)
    exec_res = internal_broker.execute_order(order, market_price=1800.0)
    assert exec_res["status"] == "FILLED"
    assert exec_res["execution_price"] > 0

    upstox_sandbox = UpstoxSandboxAdapter()
    upstox_res = upstox_sandbox.execute_order(order, market_price=1800.0)
    assert upstox_res["status"] == "ACCEPTED"
    assert "UPSTOX-SBX" in upstox_res["broker_order_id"]


# --------------------------------------------------------------------------
# 10. Walk Forward 2018-2026 Multi-Regime
# --------------------------------------------------------------------------
def test_walk_forward_schedule():
    wf = WalkForwardEngine()
    splits = wf.get_splits()
    assert len(splits) >= 4
    
    first = splits[0]
    assert "2018" in first["train_start"]
    assert "2021" in first["train_end"]
    assert "2022" in first["val_year"]
    assert "2023" in first["test_year"]

    last = splits[-1]
    assert "2026" in last["test_year"]


# --------------------------------------------------------------------------
# 11. Event Intelligence Deduplication & Parser Fallback
# --------------------------------------------------------------------------
def test_event_intelligence_jaccard_dedup():
    engine = EventIntelligenceEngine()
    e1 = engine.ingest_news("Tata Consultancy Services wins mega cloud transformation contract worth $1 Billion", "Reuters")
    e2 = engine.ingest_news("Tata Consultancy Services wins mega cloud transformation contract valued at $1 Billion", "Bloomberg")
    
    assert e1["event_id"] == e2["event_id"]
    assert e2["is_duplicate"] is True
    assert "Bloomberg" in e2["sources"]


def test_heuristic_parser_offline_fallback():
    parser = HeuristicEventParser()
    res = parser.parse_event("Reliance Industries announces quarterly net profit jumps 22% on strong retail growth")
    assert res["symbol"] == "RELIANCE.NS"
    assert res["sentiment"] == "POSITIVE"
    assert res["confidence"] >= 0.70
    assert "thesis" in res
