# =============================================================================
# test_phase_v33.py — V3.3 Enterprise Multi-Asset & Options Strategy Test Suite
# =============================================================================
"""
V3.3 Acceptance & Unit Test Suite:
1. Options Pricing (Black-Scholes Call & Put, ITM, OTM, Expiry Intrinsic)
2. Analytical Greeks (Delta, Gamma, Theta, Vega, Net Strategy Greeks)
3. 7 Core Strategies Math (Debit, Max Profit, Max Loss, Breakeven, Payoff)
4. Central Risk Engine Strategy Evaluation (Loss limits, Liquidity, Delta)
5. Multi-Leg Paper Broker Atomic Execution & Idempotency
6. Options Mark-to-Market Accounting
7. Options Stop-Loss & Target-Profit Trigger
8. Options Expiry Settlement Engine (ITM Cash Intrinsic vs OTM Worthless)
9. Numerical Determinism
10. Explicit End-to-End Options Lifecycle:
    Agent -> Options Strategy -> Risk Approval -> Broker Atomic Execution ->
    Position -> MTM -> Stop/Target -> Exit -> Realized P&L -> Agent NAV -> Leaderboard
"""

import unittest
from datetime import datetime, timezone

from event_agent.arena.asset_models import (
    AssetClass,
    CommodityInstrument,
    EquityInstrument,
    FutureInstrument,
    LegSide,
    MultiLegStrategy,
    MutualFundInstrument,
    OptionChain,
    OptionInstrument,
    OptionType,
    StrategyLeg,
    StrategyStatus,
    StrategyType,
)
from event_agent.arena.market_clock import MarketClock
from event_agent.arena.models import ProposedTrade, RiskEvaluation, TradeAction, TradeDirection
from event_agent.arena.multi_agent_broker import MultiAgentBroker, SubPortfolio
from event_agent.arena.options_engine import (
    OptionsPricingEngine,
    OptionsStrategyBuilder,
    OptionsStrategySelector,
)
from event_agent.arena.orchestrator import ArenaOrchestrator
from event_agent.arena.risk_engine import RiskEngine


class TestV33EnterpriseOptions(unittest.TestCase):

    def setUp(self):
        self.pricing = OptionsPricingEngine()
        self.spot = 25000.0
        self.strike = 25000.0
        self.T = 7.0 / 365.0
        self.vol = 0.14

    # -------------------------------------------------------------------------
    # 1. Options Pricing Tests (Black-Scholes Call & Put)
    # -------------------------------------------------------------------------
    def test_01_call_put_pricing_and_boundaries(self):
        # ATM Call & Put
        c = OptionsPricingEngine.calculate_price_and_greeks(self.spot, self.strike, self.T, self.vol, is_call=True)
        p = OptionsPricingEngine.calculate_price_and_greeks(self.spot, self.strike, self.T, self.vol, is_call=False)
        self.assertGreater(c["price"], 50.0)
        self.assertGreater(p["price"], 50.0)

        # ITM vs OTM pricing
        c_itm = OptionsPricingEngine.calculate_price_and_greeks(25500.0, 25000.0, self.T, self.vol, is_call=True)
        c_otm = OptionsPricingEngine.calculate_price_and_greeks(24500.0, 25000.0, self.T, self.vol, is_call=True)
        self.assertGreater(c_itm["price"], c_otm["price"])
        self.assertGreaterEqual(c_itm["price"], 500.0)  # Must reflect intrinsic value >= 500

    def test_02_expiry_intrinsic_settlement(self):
        # At expiry (T = 0)
        c_itm_exp = OptionsPricingEngine.calculate_price_and_greeks(25200.0, 25000.0, 0.0, self.vol, is_call=True)
        self.assertEqual(c_itm_exp["price"], 200.0)

        c_otm_exp = OptionsPricingEngine.calculate_price_and_greeks(24800.0, 25000.0, 0.0, self.vol, is_call=True)
        self.assertEqual(c_otm_exp["price"], 0.05)  # Min tick

        p_itm_exp = OptionsPricingEngine.calculate_price_and_greeks(24750.0, 25000.0, 0.0, self.vol, is_call=False)
        self.assertEqual(p_itm_exp["price"], 250.0)

        p_otm_exp = OptionsPricingEngine.calculate_price_and_greeks(25200.0, 25000.0, 0.0, self.vol, is_call=False)
        self.assertEqual(p_otm_exp["price"], 0.05)

    # -------------------------------------------------------------------------
    # 2. Analytical Greeks Tests
    # -------------------------------------------------------------------------
    def test_03_analytical_greeks(self):
        c = OptionsPricingEngine.calculate_price_and_greeks(self.spot, self.strike, self.T, self.vol, is_call=True)
        p = OptionsPricingEngine.calculate_price_and_greeks(self.spot, self.strike, self.T, self.vol, is_call=False)

        # Delta range
        self.assertTrue(0.40 < c["delta"] < 0.65)
        self.assertTrue(-0.65 < p["delta"] < -0.40)
        # Gamma is identical and positive for Call and Put
        self.assertAlmostEqual(c["gamma"], p["gamma"], places=5)
        self.assertGreater(c["gamma"], 0.0)
        # Theta is negative (decay)
        self.assertLess(c["theta"], 0.0)
        self.assertLess(p["theta"], 0.0)
        # Vega is positive
        self.assertGreater(c["vega"], 0.0)

    # -------------------------------------------------------------------------
    # 3. 7 Core Strategies Math & Payoffs
    # -------------------------------------------------------------------------
    def test_04_bull_call_spread_math(self):
        bcs = OptionsStrategyBuilder.create_bull_call_spread("NIFTY50", 25000.0, 25000.0, 25100.0, quantity=50)
        self.assertEqual(bcs.strategy_type, StrategyType.BULL_CALL_SPREAD)
        self.assertEqual(len(bcs.legs), 2)
        self.assertGreater(bcs.net_debit, 0.0)
        self.assertEqual(bcs.max_loss, bcs.net_debit)
        self.assertGreater(bcs.max_profit, 0.0)
        # Max profit + max loss = spread width * qty
        spread_total = (25100.0 - 25000.0) * 50
        self.assertAlmostEqual(bcs.max_profit + bcs.max_loss, spread_total, delta=1.0)
        self.assertTrue(25000.0 < bcs.breakeven[0] < 25100.0)

    def test_05_bear_put_spread_math(self):
        bps = OptionsStrategyBuilder.create_bear_put_spread("NIFTY50", 25000.0, 25000.0, 24900.0, quantity=50)
        self.assertEqual(bps.strategy_type, StrategyType.BEAR_PUT_SPREAD)
        self.assertEqual(len(bps.legs), 2)
        self.assertGreater(bps.net_debit, 0.0)
        self.assertEqual(bps.max_loss, bps.net_debit)
        spread_total = (25000.0 - 24900.0) * 50
        self.assertAlmostEqual(bps.max_profit + bps.max_loss, spread_total, delta=1.0)
        self.assertTrue(24900.0 < bps.breakeven[0] < 25000.0)

    def test_06_long_straddle_and_strangle_math(self):
        strd = OptionsStrategyBuilder.create_long_straddle("NIFTY50", 25000.0, 25000.0, quantity=50)
        self.assertEqual(len(strd.legs), 2)
        self.assertEqual(len(strd.breakeven), 2)
        self.assertTrue(strd.breakeven[0] < 25000.0 < strd.breakeven[1])

        strg = OptionsStrategyBuilder.create_long_strangle("NIFTY50", 25000.0, 24900.0, 25100.0, quantity=50)
        self.assertEqual(len(strg.legs), 2)
        self.assertLess(strg.net_debit, strd.net_debit)  # Strangle is cheaper than straddle

    def test_07_protective_put_math(self):
        prot = OptionsStrategyBuilder.create_protective_put("NIFTY50", 25000.0, 24900.0, quantity=50)
        self.assertEqual(prot.strategy_type, StrategyType.PROTECTIVE_PUT)
        self.assertGreater(prot.max_loss, 0.0)
        self.assertGreater(prot.net_debit, 0.0)

    def test_08_payoff_points_generation(self):
        bcs = OptionsStrategyBuilder.create_bull_call_spread("NIFTY50", 25000.0, 25000.0, 25100.0)
        points = OptionsStrategyBuilder.generate_payoff_points(bcs, spot_center=25000.0, pct_range=3.0, num_points=11)
        self.assertEqual(len(points), 11)
        # Lowest spot payoff should equal -max_loss
        self.assertAlmostEqual(points[0]["payoff"], -bcs.max_loss, delta=1.0)
        # Highest spot payoff should equal max_profit
        self.assertAlmostEqual(points[-1]["payoff"], bcs.max_profit, delta=1.0)

    # -------------------------------------------------------------------------
    # 4. Central Risk Engine Strategy Evaluation
    # -------------------------------------------------------------------------
    def test_09_risk_engine_strategy_evaluation(self):
        risk = RiskEngine()
        bcs = OptionsStrategyBuilder.create_bull_call_spread("NIFTY50", 25000.0, 25000.0, 25100.0)

        # Approved case
        res_ok = risk.evaluate_strategy(
            strategy=bcs,
            agent_equity=2000000.0,
            agent_cash=2000000.0,
            current_open_strategies=[],
            daily_starting_equity=2000000.0,
            check_market_clock=False,
        )
        self.assertTrue(res_ok.is_approved)
        self.assertEqual(res_ok.rejection_reason, "APPROVED")

        # Rejected case: Insufficient cash
        res_no_cash = risk.evaluate_strategy(
            strategy=bcs,
            agent_equity=2000000.0,
            agent_cash=100.0,  # Only ₹100 cash!
            current_open_strategies=[],
            daily_starting_equity=2000000.0,
            check_market_clock=False,
        )
        self.assertFalse(res_no_cash.is_approved)
        self.assertIn("INSUFFICIENT_CASH", res_no_cash.rejection_reason)

    # -------------------------------------------------------------------------
    # 5. Multi-Leg Paper Broker Atomic Execution & Accounting
    # -------------------------------------------------------------------------
    def test_10_broker_atomic_execution_and_idempotency(self):
        broker = MultiAgentBroker()
        risk = RiskEngine()
        bcs = OptionsStrategyBuilder.create_bull_call_spread("NIFTY50", 25000.0, 25000.0, 25100.0, agent_id="ALPHA")

        eval_res = risk.evaluate_strategy(bcs, 2000000.0, 2000000.0, [], 2000000.0, check_market_clock=False)
        sub_port = broker.get_agent_portfolio("ALPHA")
        initial_cash = sub_port.cash

        # First execution
        success, reason, strat = broker.execute_approved_strategy(bcs, eval_res, market_date="2026-09-09")
        self.assertTrue(success)
        self.assertEqual(reason, "EXECUTED")
        self.assertEqual(sub_port.cash, initial_cash - bcs.net_debit)
        self.assertEqual(len(sub_port.open_strategies), 1)

        # Idempotent replay: must return ALREADY_EXECUTED without double debit
        success2, reason2, strat2 = broker.execute_approved_strategy(bcs, eval_res, market_date="2026-09-09")
        self.assertTrue(success2)
        self.assertEqual(reason2, "ALREADY_EXECUTED")
        self.assertEqual(sub_port.cash, initial_cash - bcs.net_debit)  # Cash unchanged

    # -------------------------------------------------------------------------
    # 6. Mark-to-Market & Stop Loss / Target Trigger
    # -------------------------------------------------------------------------
    def test_11_strategy_mtm_and_stop_loss_trigger(self):
        broker = MultiAgentBroker()
        sub_port = broker.get_agent_portfolio("ALPHA")
        bcs = OptionsStrategyBuilder.create_bull_call_spread("NIFTY50", 25000.0, 25000.0, 25100.0, agent_id="ALPHA")
        bcs.stop_loss_amount = 1000.0

        # Inject into broker as OPEN position
        bcs.status = StrategyStatus.OPEN
        broker.executed_trade_ids.add(bcs.strategy_id)
        sub_port.cash -= bcs.net_debit
        sub_port.open_strategies[bcs.strategy_id] = bcs

        # Spot crashes to 24000 (breaches stop)
        broker.mark_to_market_strategies({"NIFTY50": 24000.0}, expiry_days_remaining=1)
        # Should be stopped out automatically
        self.assertEqual(len(sub_port.open_strategies), 0)
        self.assertEqual(len(sub_port.closed_strategies), 1)
        closed = sub_port.closed_strategies[0]
        self.assertEqual(closed.status, StrategyStatus.STOPPED_OUT)
        self.assertLess(closed.realized_pnl, 0.0)

    # -------------------------------------------------------------------------
    # 7. Expiry Settlement Engine
    # -------------------------------------------------------------------------
    def test_12_expiry_settlement_itm_vs_otm(self):
        broker = MultiAgentBroker()
        sub_port = broker.get_agent_portfolio("ALPHA")
        initial_cash = sub_port.cash

        # Bull Call Spread (25000/25100)
        bcs = OptionsStrategyBuilder.create_bull_call_spread("NIFTY50", 25000.0, 25000.0, 25100.0, agent_id="ALPHA")
        bcs.status = StrategyStatus.OPEN
        sub_port.cash -= bcs.net_debit
        sub_port.open_strategies[bcs.strategy_id] = bcs

        # Settle at 25200 (completely above 25100, maximum profit!)
        broker.settle_expiring_strategies({"NIFTY50": 25200.0})
        self.assertEqual(len(sub_port.open_strategies), 0)
        self.assertEqual(len(sub_port.closed_strategies), 1)
        settled = sub_port.closed_strategies[0]
        self.assertEqual(settled.status, StrategyStatus.EXPIRED)
        self.assertAlmostEqual(settled.realized_pnl, bcs.max_profit, delta=1.0)
        self.assertAlmostEqual(sub_port.cash, initial_cash + bcs.max_profit, delta=1.0)

    # -------------------------------------------------------------------------
    # 8. Numerical Determinism
    # -------------------------------------------------------------------------
    def test_13_pricing_and_strategy_determinism(self):
        # Pricing run 1 vs 2
        r1 = OptionsPricingEngine.calculate_price_and_greeks(25123.45, 25100.0, 0.038, 0.142)
        r2 = OptionsPricingEngine.calculate_price_and_greeks(25123.45, 25100.0, 0.038, 0.142)
        self.assertEqual(r1["price"], r2["price"])
        self.assertEqual(r1["delta"], r2["delta"])
        self.assertEqual(r1["gamma"], r2["gamma"])
        self.assertEqual(r1["theta"], r2["theta"])
        self.assertEqual(r1["vega"], r2["vega"])

    # -------------------------------------------------------------------------
    # 9. Future Asset Class Boundaries (Mutual Funds & Commodities)
    # -------------------------------------------------------------------------
    def test_14_future_asset_class_boundaries(self):
        mf = MutualFundInstrument("120503", "HDFC Top 100 Fund")
        self.assertEqual(mf.asset_class, AssetClass.MUTUAL_FUND)
        self.assertFalse(mf.to_dict()["is_enabled"])

        cmd = CommodityInstrument("GOLD", "MCX Gold 1kg")
        self.assertEqual(cmd.asset_class, AssetClass.COMMODITY)
        self.assertFalse(cmd.to_dict()["is_enabled"])

    # -------------------------------------------------------------------------
    # 10. EXPLICIT END-TO-END OPTIONS LIFECYCLE (Mandatory Acceptance Criterion)
    # -------------------------------------------------------------------------
    def test_15_explicit_end_to_end_options_lifecycle(self):
        """
        Acceptance Criterion:
        Agent Proposal -> Options Strategy Construction -> Risk Approval ->
        Atomic Multi-Leg Broker Execution -> Active Position ->
        Mark-to-Market Revaluation -> Stop-Loss/Target Trigger ->
        Exit Settlement -> Realized P&L Credited -> Agent NAV Updated -> Arena Leaderboard Verified.
        """
        orch = ArenaOrchestrator()
        agent_id = "ALPHA"
        sub_port = orch.broker.get_agent_portfolio(agent_id)
        start_cap = sub_port.portfolio_value
        self.assertEqual(start_cap, 2000000.0)

        # 1. High conviction catalyst triggering an options proposal
        sample_preds = [{
            "symbol": "TCS.NS",
            "base_price": 4000.0,
            "predicted_1d_pct": 2.2,
            "conviction": 85.0,
            "occurred_events": ["Major macro growth acceleration & earnings breakout"],
            "stock_sentiment": 0.65,
            "action": "BUY",
            "direction": "BULLISH",
            "target_price": 25550.0,
            "stop_loss": 24800.0,
        }]

        # 2. Run Orchestrator Cycle
        res = orch.run_cycle(predictions=sample_preds, force_execute=True)
        self.assertIn("option_chain", res)
        self.assertIn("recommended_options_strategies", res)

        # Verify options strategy exists in Agent Alpha's holdings
        holdings = sub_port.get_holdings_by_instrument()
        self.assertGreaterEqual(len(holdings["options"]), 1)
        opt_pos = holdings["options"][0]
        self.assertTrue(opt_pos.get("is_multi_leg", False) or opt_pos.get("instrument", {}).get("instrument_type") == "OPTION")
        self.assertEqual(opt_pos["status"], "OPEN")

        # 3. Mark to market with positive price rally
        orch.broker.mark_to_market_strategies({"TCS.NS": 4150.0, "NIFTY50": 25250.0}, expiry_days_remaining=5)
        self.assertGreater(sub_port.portfolio_value, 2000000.0)

        # 4. Settle at Expiry
        orch.broker.settle_expiring_strategies({"TCS.NS": 4200.0, "NIFTY50": 25300.0})
        self.assertEqual(len(sub_port.open_strategies), 0)
        self.assertGreaterEqual(len(sub_port.closed_strategies), 1)

        # Realized P&L credited to agent NAV
        self.assertGreater(sub_port.realized_pnl, 0.0)
        self.assertGreater(sub_port.portfolio_value, start_cap)

        # 5. Leaderboard reflects option trading & honors
        leaderboard = orch._compute_leaderboard()
        alpha_entry = next(e for e in leaderboard if e["agent_id"] == "ALPHA")
        self.assertGreater(alpha_entry["portfolio_value"], start_cap)
        self.assertIn("BEST_OPTIONS_TRADER", alpha_entry["honors"])


if __name__ == "__main__":
    unittest.main()
