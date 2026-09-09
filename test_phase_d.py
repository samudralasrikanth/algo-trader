# =============================================================================
# test_phase_d.py — Test Suite for Phase D: Paper Broker + Execution
# =============================================================================

import sys
from datetime import datetime, timezone
import pandas as pd

# 1. Cost Model Tests
print("--- Testing 1: Cost Model (Indian Market Structure) ---")
from event_agent.broker.cost_model import CostModel, COST_SCHEDULES

cm = CostModel(default_schedule="equity_intraday")

# Intraday: STT on SELL only, Nil on BUY
buy_costs = cm.calculate_entry_cost("equity_intraday", "BUY", price=1000.0, quantity=100)
assert buy_costs["stt"] == 0.0, "Intraday BUY must have 0 STT"
assert buy_costs["stamp_duty"] > 0, "Intraday BUY must have stamp duty"

sell_costs = cm.calculate_exit_cost("equity_intraday", "SELL", price=1050.0, quantity=100)
assert sell_costs["stt"] > 0.0, "Intraday SELL must have STT"
assert sell_costs["stamp_duty"] == 0.0, "Intraday SELL stamp duty must be 0"

# Delivery: STT on both BUY and SELL
deliv_buy = cm.calculate_entry_cost("equity_delivery", "BUY", price=1000.0, quantity=100)
deliv_sell = cm.calculate_exit_cost("equity_delivery", "SELL", price=1050.0, quantity=100)
assert deliv_buy["stt"] > 0, "Delivery BUY must have 0.1% STT"
assert deliv_sell["stt"] > 0, "Delivery SELL must have 0.1% STT"

# Full round-trip friction test
rt_costs = cm.calculate_total_trade_costs(
    entry_price=1287.0,
    exit_price=1310.0,
    quantity=50,
    position_side="LONG",
    instrument_type="equity_intraday",
)
assert rt_costs["total_friction_cost"] > 0
assert "statutory_costs" in rt_costs
assert "slippage_cost" in rt_costs
print(f"✅ Cost model passed. Round-trip friction on ₹{rt_costs['turnover']:,.0f} turnover: ₹{rt_costs['total_friction_cost']:.2f}")

# 2. Execution Simulator Tests (5-min Candles + Ambiguity Rules)
print("\n--- Testing 2: Execution Simulator (5-min Candles) ---")
from event_agent.broker.execution_simulator import Candle5M, ExecutionSimulator, Fill

sim = ExecutionSimulator(conservative_ambiguity=True)

# Scenario A: Target Hit
candles_target = [
    Candle5M("09:15", 1000.0, 1008.0, 998.0, 1005.0),
    Candle5M("09:20", 1005.0, 1025.0, 1002.0, 1022.0), # Target at 1020 hit here
]
fill_target = sim.simulate_fill("LONG", entry_price=1000.0, target_price=1020.0, stop_price=980.0, candles=candles_target, symbol="RELIANCE.NS")
assert fill_target.reason == "TARGET_HIT"
assert fill_target.fill_price == 1020.0
assert fill_target.is_ambiguous is False
assert fill_target.execution_snapshot["symbol"] == "RELIANCE.NS"
assert "sha256:" in fill_target.execution_snapshot["data_hash"]

# Scenario B: Stop Hit
candles_stop = [
    Candle5M("09:15", 1000.0, 1005.0, 995.0, 998.0),
    Candle5M("09:20", 998.0, 1001.0, 975.0, 978.0),  # Stop at 980 hit here
]
fill_stop = sim.simulate_fill("LONG", entry_price=1000.0, target_price=1020.0, stop_price=980.0, candles=candles_stop)
assert fill_stop.reason == "STOP_HIT"
assert fill_stop.fill_price == 980.0
assert fill_stop.is_ambiguous is False

# Scenario C: AMBIGUOUS CANDLE (Both Target and Stop breached in same bar)
# MUST trigger conservative STOP-FIRST rule (Review Point #6 fix)
candles_ambig = [
    Candle5M("09:15", 1000.0, 1005.0, 995.0, 1000.0),
    Candle5M("09:20", 1000.0, 1030.0, 970.0, 1010.0), # High=1030 (breaches 1020), Low=970 (breaches 980)
]
fill_ambig = sim.simulate_fill("LONG", entry_price=1000.0, target_price=1020.0, stop_price=980.0, candles=candles_ambig)
assert fill_ambig.reason == "STOP_HIT", "Ambiguous candle must trigger conservative stop-first rule"
assert fill_ambig.is_ambiguous is True, "Must be flagged as ambiguous"
assert "Conservative stop-first" in fill_ambig.ambiguity_note

# Scenario D: Gap-through Protection (Market opens beyond stop)
candles_gap = [
    Candle5M("09:15", 965.0, 970.0, 960.0, 968.0), # Opens at 965, below stop of 980
]
fill_gap = sim.simulate_fill("LONG", entry_price=1000.0, target_price=1020.0, stop_price=980.0, candles=candles_gap)
assert fill_gap.reason == "STOP_HIT"
assert fill_gap.fill_price == 965.0, f"Gap-through fill must be open price (965.0), got {fill_gap.fill_price}"

print("✅ Execution simulator & ambiguity conservative rules passed.")

# 3. Position Tracker Tests
print("\n--- Testing 3: Position Tracker ---")
from event_agent.broker.position_tracker import PositionTracker

tracker = PositionTracker(initial_capital=10_00_000.0)
pos = tracker.open_position(
    prediction_id="PRED-TEST-001",
    symbol="TCS.NS",
    side="LONG",
    quantity=10,
    entry_price=4100.0,
    target_price=4180.0,
    stop_loss=4020.0,
)
assert pos.status == "OPEN"
assert len(tracker.get_open_positions()) == 1

closed_pos = tracker.close_position(
    position_id=pos.position_id,
    exit_price=4180.0,
    exit_reason="TARGET_HIT",
    cost_details={"total_friction_cost": 85.50},
)
assert closed_pos.status == "CLOSED"
assert closed_pos.gross_pnl == (4180.0 - 4100.0) * 10  # 800.0
assert closed_pos.net_pnl == round(800.0 - 85.50, 2)    # 714.50

summary = tracker.get_portfolio_summary()
assert summary["current_capital"] == 10_00_000.0 + 714.50
assert summary["win_rate_pct"] == 100.0
assert summary["total_closed_trades"] == 1
print("✅ Position tracker passed.")

# 4. Paper Broker Risk & Sizing Tests
print("\n--- Testing 4: Paper Broker & Risk Governance ---")
from event_agent.broker.paper_broker import PaperBroker, PORTFOLIO_CONFIG

broker = PaperBroker(config={"initial_capital": 10_00_000.0, "risk_per_trade_pct": 0.5, "max_trade_capital_pct": 10.0})

# Uncapped sizing test:
# Capital: ₹10,00,000, 0.5% risk = ₹5,000
# Entry: 100.0, Stop: 95.0 -> Stop distance = 5.0
# Raw Quantity = int(5000 / 5) = 1000 shares
# Capital required = 1000 * 100 = 100,000 (exactly matches 10% max capital cap)
qty_uncapped = broker.calculate_position_size(entry=100.0, stop=95.0)
assert qty_uncapped == 1000, f"Expected 1000, got {qty_uncapped}"

# Capped sizing test:
# For RELIANCE: Entry 1287.0, Stop: 1261.26 (dist 25.74)
# Raw qty = int(5000 / 25.74) = 194 shares -> ₹2,49,678 (exceeds ₹1,00,000 10% cap)
# Capped qty = int(100,000 / 1287.0) = 77 shares
qty_capped = broker.calculate_position_size(entry=1287.0, stop=1261.26)
assert qty_capped == 77, f"Expected 77, got {qty_capped}"

# Test trade rejection on low confidence
allowed, reason = broker.can_enter_trade("INFY.NS", confidence=50.0, entry_price=1800.0, quantity=10)
assert allowed is False
assert "LOW_CONFIDENCE" in reason

# Test full end-to-end prediction execution
mock_pred = {
    "prediction_id": "PRED-20260909-RELIANCE-v3.0.0",
    "symbol": "RELIANCE.NS",
    "action": "BUY",
    "conviction": 72.0,
    "entry_price": 1287.0,
    "target_price": 1315.0,
    "stop_loss": 1261.26,
    "base_price": 1287.0,
}

mock_candles = [
    Candle5M("09:15", 1287.0, 1295.0, 1285.0, 1292.0),
    Candle5M("09:20", 1292.0, 1318.0, 1290.0, 1316.0), # Hits target 1315.0
]

executed_trade = broker.execute_prediction(mock_pred, intraday_candles=mock_candles)
assert executed_trade is not None
assert executed_trade.status == "CLOSED"
assert executed_trade.exit_reason == "TARGET_HIT"
assert executed_trade.net_pnl > 0
assert executed_trade.total_friction_costs > 0

port_summary = broker.get_portfolio_summary()
assert port_summary["current_capital"] > 10_00_000.0
assert port_summary["total_closed_trades"] == 1
print(f"✅ Paper broker executed trade cleanly. Net P&L: ₹{executed_trade.net_pnl:.2f}, Friction: ₹{executed_trade.total_friction_costs:.2f}")

print("\n🎉 ALL PHASE D TESTS PASSED SUCCESSFULLY! (4/4 test groups)")
