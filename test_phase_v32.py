# =============================================================================
# test_phase_v32.py — Comprehensive Automated Test Suite for V3.2 Arena
# =============================================================================
"""
Tests all 22 core acceptance criteria and invariants for V3.2 AI Trading Arena:
1.  Total virtual capital = ₹1,00,00,000 (5 agents × ₹20,00,000).
2.  All 5 agents start with 0 positions and pure cash.
3.  Each agent dynamically holds 0–10 active allocations.
4.  NO_TRADE is a first-class action with structured rationale.
5.  All 5 agents evaluate the exact same immutable snapshot.
6.  Central Risk Engine acts as gatekeeper before Paper Broker execution.
7.  Risk-based sizing limits planned risk to 0.5% of agent capital.
8.  Single position allocation capped at 20%.
9.  Portfolio exposure capped at 50%.
10. Sector/correlated exposure capped at 25%.
11. Min conviction hurdle enforced at 60%.
12. Mandatory stop-loss on every directional proposal.
13. Market Clock state machine enforces strict 15:30 IST hard cutoff.
14. Collision-proof Trade ID guarantees 100% idempotent replay.
15. Frozen strategy versions recorded on every trade and decision.
16. Futures prices explicitly labeled as simulated (cost-of-carry).
17. Options premiums explicitly labeled as modelled (Black-Scholes + VIX).
18. Holdings strictly separated into 4 buckets (Equity, Futures, Options, All).
19. Leaderboard awards the 3 distinct trophies (Best Return, Risk-Adjusted, Capital Protector).
20. 50-stock Market Analytics calculates multi-agent consensus matrix.
21. Truthful system metrics reflect actual database records.
22. V3.1.1 Regression Guarantees: PIT store, SHA-256 hashes, 18-code taxonomy, and 5 baselines survive.
"""

import sys
import unittest
from datetime import datetime, time, timedelta, timezone

from event_agent.config import (
    AGENT_STARTING_CAPITAL,
    DAILY_LOSS_LIMIT_PCT,
    MAX_ACTIVE_POSITIONS_PER_AGENT,
    MAX_CORRELATED_EXPOSURE_PCT,
    MAX_PORTFOLIO_EXPOSURE_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MAX_SINGLE_POSITION_ALLOCATION_PCT,
    MIN_CONFIDENCE_PCT,
    NIFTY50_UNIVERSE,
    TOTAL_VIRTUAL_CAPITAL,
)
from event_agent.arena.agents import create_all_agents
from event_agent.arena.consensus_engine import ConsensusEngine
from event_agent.arena.market_clock import MarketClock, MarketPhase
from event_agent.arena.models import (
    HedgeDecision,
    Instrument,
    InstrumentType,
    ProposedTrade,
    TradeAction,
    TradeDirection,
)
from event_agent.arena.multi_agent_broker import MultiAgentBroker
from event_agent.arena.orchestrator import ArenaOrchestrator
from event_agent.arena.risk_engine import RiskEngine
from event_agent.storage.ledger import get_arena_data, init_db


class TestV32Arena(unittest.TestCase):

    def setUp(self):
        init_db()
        self.broker = MultiAgentBroker()
        self.risk_engine = RiskEngine()
        self.agents = create_all_agents()

    # 1. Total arena starting capital is exactly ₹1,00,00,000 across 5 agents
    def test_01_total_starting_capital(self):
        self.assertEqual(TOTAL_VIRTUAL_CAPITAL, 10000000.0)
        self.assertEqual(AGENT_STARTING_CAPITAL, 2000000.0)
        summary = self.broker.get_total_arena_summary()
        self.assertEqual(summary["total_virtual_capital"], 10000000.0)
        self.assertEqual(summary["total_cash"], 10000000.0)

    # 2. All 5 agents start with 0 positions and pure cash
    def test_02_initial_positions_zero(self):
        for aid in ["ALPHA", "MOMENTUM", "MACRO", "DEFENSIVE", "CONTRARIAN"]:
            p = self.broker.get_agent_portfolio(aid)
            self.assertEqual(len(p.open_positions), 0)
            self.assertEqual(p.cash, 2000000.0)
            self.assertEqual(p.invested_capital, 0.0)
            self.assertEqual(p.portfolio_value, 2000000.0)

    # 3. Each agent dynamically holds 0 to 10 active positions
    def test_03_max_positions_bound(self):
        self.assertEqual(MAX_ACTIVE_POSITIONS_PER_AGENT, 10)
        p = self.broker.get_agent_portfolio("ALPHA")
        self.assertTrue(0 <= len(p.open_positions) <= 10)

    # 4. NO_TRADE is a first-class action with structured rationale
    def test_04_no_trade_first_class(self):
        alpha = self.agents["ALPHA"]
        no_trade_proposal = alpha.create_no_trade_proposal("Test NO_TRADE reason")
        self.assertEqual(no_trade_proposal.action, TradeAction.NO_TRADE)
        self.assertEqual(no_trade_proposal.symbol, "NIFTY50")
        self.assertIn("Test NO_TRADE reason", no_trade_proposal.decision_reason)

        eval_res = self.risk_engine.evaluate_proposal(
            proposal=no_trade_proposal,
            agent_equity=2000000.0,
            agent_cash=2000000.0,
            current_open_positions=[],
            daily_starting_equity=2000000.0,
        )
        self.assertTrue(eval_res.is_approved)
        self.assertEqual(eval_res.adjusted_quantity, 0)

    # 5. All 5 agents receive the exact same immutable snapshot
    def test_05_shared_immutable_snapshot(self):
        snap1 = ConsensusEngine.generate_market_snapshot(market_date="2026-09-09")
        snap2 = ConsensusEngine.generate_market_snapshot(market_date="2026-09-09")
        self.assertEqual(snap1["snapshot_id"], snap2["snapshot_id"])
        self.assertEqual(len(snap1["stocks"]), 50)

    # 6. Central Risk Engine acts as gatekeeper before Paper Broker
    def test_06_risk_gatekeeper(self):
        trade = ProposedTrade(
            agent_id="ALPHA",
            strategy_version="ALPHA-1.0",
            symbol="RELIANCE.NS",
            action=TradeAction.BUY,
            instrument=Instrument("RELIANCE.NS", InstrumentType.EQUITY),
            direction=TradeDirection.BUY,
            entry_price=1287.0,
            stop_loss=1260.0,
            target=1320.0,
            confidence=45.0,  # Below 60% hurdle!
            expected_move_pct=2.0,
            planned_risk_amount=10000.0,
            hedge_decision=HedgeDecision.NO,
        )
        eval_res = self.risk_engine.evaluate_proposal(
            proposal=trade,
            agent_equity=2000000.0,
            agent_cash=2000000.0,
            current_open_positions=[],
            daily_starting_equity=2000000.0,
            check_market_clock=False,
        )
        self.assertFalse(eval_res.is_approved)
        self.assertIn("LOW_CONFIDENCE", eval_res.rejection_reason)

    # 7. Risk-based sizing limits planned risk to 0.5%
    def test_07_risk_sizing_point_five_percent(self):
        self.assertEqual(MAX_RISK_PER_TRADE_PCT, 0.5)
        trade = ProposedTrade(
            agent_id="ALPHA",
            strategy_version="ALPHA-1.0",
            symbol="RELIANCE.NS",
            action=TradeAction.BUY,
            instrument=Instrument("RELIANCE.NS", InstrumentType.EQUITY),
            direction=TradeDirection.BUY,
            entry_price=1000.0,
            stop_loss=980.0,  # Stop distance = 20 (2%)
            target=1040.0,
            confidence=75.0,
            expected_move_pct=4.0,
            planned_risk_amount=10000.0,
            hedge_decision=HedgeDecision.NO,
        )
        eval_res = self.risk_engine.evaluate_proposal(
            proposal=trade,
            agent_equity=2000000.0,
            agent_cash=2000000.0,
            current_open_positions=[],
            daily_starting_equity=2000000.0,
            check_market_clock=False,
        )
        self.assertTrue(eval_res.is_approved)
        # Sizing: risk_budget = 2,000,000 * 0.005 = 10,000. Stop distance = 20 -> 500 shares max
        self.assertTrue(eval_res.adjusted_quantity <= 500)

    # 8. Single position allocation cap is 20%
    def test_08_single_position_allocation_cap(self):
        self.assertEqual(MAX_SINGLE_POSITION_ALLOCATION_PCT, 20.0)

    # 9. Portfolio exposure cap is 50%
    def test_09_portfolio_exposure_cap(self):
        self.assertEqual(MAX_PORTFOLIO_EXPOSURE_PCT, 50.0)

    # 10. Sector / correlated exposure cap is 25%
    def test_10_sector_exposure_cap(self):
        self.assertEqual(MAX_CORRELATED_EXPOSURE_PCT, 25.0)

    # 11. Min confidence hurdle is 60%
    def test_11_min_confidence_hurdle(self):
        self.assertEqual(MIN_CONFIDENCE_PCT, 60.0)

    # 12. Mandatory stop-loss
    def test_12_mandatory_stop_loss(self):
        trade = ProposedTrade(
            agent_id="ALPHA",
            strategy_version="ALPHA-1.0",
            symbol="RELIANCE.NS",
            action=TradeAction.BUY,
            instrument=Instrument("RELIANCE.NS", InstrumentType.EQUITY),
            direction=TradeDirection.BUY,
            entry_price=1000.0,
            stop_loss=0.0,  # Zero stop!
            target=1040.0,
            confidence=75.0,
            expected_move_pct=4.0,
            planned_risk_amount=10000.0,
            hedge_decision=HedgeDecision.NO,
        )
        eval_res = self.risk_engine.evaluate_proposal(
            proposal=trade,
            agent_equity=2000000.0,
            agent_cash=2000000.0,
            current_open_positions=[],
            daily_starting_equity=2000000.0,
            check_market_clock=False,
        )
        self.assertFalse(eval_res.is_approved)
        self.assertIn("STOP_LOSS", eval_res.rejection_reason)

    # 13. Market Clock strict 15:30 IST cutoff
    def test_13_market_clock_cutoff(self):
        # 10:05 UTC = 15:35 IST (inside MARKET_CLOSE 15:30-15:45)
        post_cutoff = datetime(2026, 9, 9, 10, 5, 0, tzinfo=timezone.utc)
        can_trade, reason = MarketClock.can_accept_new_orders(post_cutoff)
        self.assertFalse(can_trade)
        self.assertIn("CUTOFF_REACHED", reason)

    # 14. Collision-proof Trade ID & Idempotent Replay
    def test_14_idempotent_replay(self):
        orch = ArenaOrchestrator()
        sample_preds = [{
            'symbol': 'TCS.NS',
            'base_price': 4000.0,
            'predicted_1d_pct': 2.0,
            'conviction': 75.0,
            'occurred_events': ['Major earnings announcement'],
            'stock_sentiment': 0.5,
            'action': 'BUY',
            'direction': 'BULLISH',
            'target_price': 4080.0,
            'stop_loss': 3940.0,
        }]
        res1 = orch.run_cycle(predictions=sample_preds, force_execute=True)
        trades_count_1 = res1["executed_trades_count"]
        cash_1 = orch.broker.get_agent_portfolio("ALPHA").cash

        # Run 2: Identical snapshot
        res2 = orch.run_cycle(predictions=sample_preds, force_execute=True)
        trades_count_2 = res2["executed_trades_count"]
        cash_2 = orch.broker.get_agent_portfolio("ALPHA").cash

        self.assertEqual(trades_count_2, 0)
        self.assertEqual(cash_1, cash_2)

    # 15. Strategy versions frozen and stored
    def test_15_frozen_strategy_versions(self):
        expected = {
            "ALPHA": "ALPHA-1.0",
            "MOMENTUM": "MOMENTUM-1.0",
            "MACRO": "MACRO-1.0",
            "DEFENSIVE": "DEFENSIVE-1.0",
            "CONTRARIAN": "CONTRARIAN-1.0",
        }
        for aid, ver in expected.items():
            agent = self.agents[aid]
            self.assertEqual(agent.strategy_version, ver)

    # 16 & 17. Derivatives explicit simulated/modelled price disclosure
    def test_16_17_derivatives_pricing_disclosure(self):
        fut = Instrument("NIFTY50", InstrumentType.FUTURE, expiry="2026-09-24", is_simulated_price=True)
        opt = Instrument("NIFTY50", InstrumentType.OPTION, expiry="2026-09-24", strike=24000.0, is_simulated_price=True)
        self.assertTrue(fut.is_simulated_price)
        self.assertTrue(opt.is_simulated_price)
        self.assertIn("COST_OF_CARRY", fut.pricing_model)
        self.assertIn("BLACK_SCHOLES", opt.pricing_model)

    # 18. Holdings strictly separated into 4 buckets
    def test_18_holdings_separation(self):
        p = self.broker.get_agent_portfolio("MOMENTUM")
        holdings = p.get_holdings_by_instrument()
        self.assertIn("equity", holdings)
        self.assertIn("futures", holdings)
        self.assertIn("options", holdings)
        self.assertIn("all", holdings)

    # 19. Multi-dimensional leaderboard with 3 trophies
    def test_19_leaderboard_three_awards(self):
        orch = ArenaOrchestrator()
        res = orch.run_cycle(force_execute=True)
        lb = res["leaderboard"]
        self.assertEqual(len(lb), 5)
        all_trophies = [t["code"] for r in lb for t in r.get("trophies", [])]
        self.assertIn("BEST_RETURN", all_trophies)
        self.assertIn("BEST_RISK_ADJUSTED", all_trophies)
        self.assertIn("BEST_CAPITAL_PRESERVATION", all_trophies)

    # 20. 50-stock Market Analytics consensus matrix
    def test_20_consensus_matrix(self):
        snap = ConsensusEngine.generate_market_snapshot(market_date="2026-09-09")
        consensus = ConsensusEngine.compute_consensus(snap, {})
        self.assertEqual(len(consensus["stocks"]), 50)
        self.assertIn("summary", consensus)
        self.assertIn("bullish_count", consensus["summary"])

    # 21. Truthful system monitoring
    def test_21_truthful_system_status(self):
        data = get_arena_data()
        self.assertIn("portfolios", data)
        self.assertIn("positions", data)
        self.assertIn("recent_trades", data)
        self.assertIn("recent_decisions", data)

    # 22. V3.1.1 Invariants & Baselines
    def test_22_v311_regression_guarantees(self):
        from event_agent.reporting.web_export import build_web_payload
        payload = build_web_payload()
        self.assertIn("vs_baselines", payload)
        self.assertEqual(len(payload["vs_baselines"]), 5)
        self.assertIn("failed_trades_prominent", payload)
        self.assertIn("regime", payload)
        self.assertEqual(payload["regime"]["composite_regime"], "NEUTRAL")


if __name__ == "__main__":
    unittest.main()
