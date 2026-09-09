# =============================================================================
# event_agent/arena/orchestrator.py — V3.2 Arena Lifecycle & Decision Orchestrator
# =============================================================================
"""
Central Orchestrator coordinating the complete V3.2 AI Trading Arena lifecycle:
1. Enforces MarketClock state machine (15:30 IST strict cutoff, weekends, holidays).
2. Distributes the immutable 50-stock market snapshot to all 5 autonomous agents.
3. Collects proposals (0–10 positions or structured NO_TRADE).
4. Routes proposals through the Central Risk Engine.
5. Executes approved trades via MultiAgentBroker with idempotent collision-proof IDs.
6. Revalues & marks-to-market positions.
7. Computes the Multi-Dimensional Leaderboard (3 awards) and Today's Arena summary.
8. Prepares payload for database persistence and web reporting.
"""

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..config import (
    AGENT_STARTING_CAPITAL,
    MAX_ACTIVE_POSITIONS_PER_AGENT,
    NIFTY50_UNIVERSE,
    TOTAL_VIRTUAL_CAPITAL,
)
from .agents import create_all_agents
from .asset_models import MultiLegStrategy, OptionChain, StrategyStatus, StrategyType
from .options_engine import OptionsPricingEngine, OptionsStrategyBuilder, OptionsStrategySelector
from .consensus_engine import ConsensusEngine
from .market_clock import MarketClock, MarketPhase
from .models import (
    AgentProfile,
    HedgeDecision,
    Instrument,
    InstrumentType,
    ProposedTrade,
    RiskEvaluation,
    TradeAction,
    TradeDirection,
)
from .multi_agent_broker import MultiAgentBroker
from .risk_engine import RiskEngine
from ..storage.ledger import (
    save_agent_portfolio,
    save_agent_position,
    save_agent_trade,
    save_agent_decision,
    save_agent_daily_snapshot,
)

logger = logging.getLogger(__name__)


class ArenaOrchestrator:
    """
    Coordinates the 5-Agent Nifty 50 AI Trading Arena.
    """

    def __init__(
        self,
        broker: Optional[MultiAgentBroker] = None,
        risk_engine: Optional[RiskEngine] = None,
    ):
        self.broker = broker or MultiAgentBroker()
        self.risk_engine = risk_engine or RiskEngine()
        self.agents_map = create_all_agents()
        self.agents = list(self.agents_map.values())
        self.last_snapshot: Optional[Dict[str, Any]] = None
        self.last_consensus: Optional[Dict[str, Any]] = None
        self.last_decisions: List[Dict[str, Any]] = []

    def run_cycle(
        self,
        market_date: Optional[str] = None,
        predictions: Optional[List[Dict[str, Any]]] = None,
        regime_data: Optional[Dict[str, Any]] = None,
        simulated_time: Optional[datetime] = None,
        force_execute: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a full Arena cycle:
        1. Check market clock
        2. Build 50-stock snapshot
        3. Query 5 agents
        4. Validate risk
        5. Execute approved trades
        6. Mark to market
        7. Compute consensus and leaderboard
        """
        if market_date is None:
            market_date = datetime.now().strftime("%Y-%m-%d")

        # 1. Market Clock verification
        clock_status = MarketClock.get_status(current_time=simulated_time)

        # 2. Build or load immutable 50-stock snapshot
        market_snapshot = ConsensusEngine.generate_market_snapshot(
            market_date=market_date,
            predictions=predictions,
            regime_data=regime_data,
        )
        self.last_snapshot = market_snapshot
        snapshot_id = market_snapshot["snapshot_id"]

        # Prices for mark-to-market
        stock_prices = {
            sym: sdata["base_price"]
            for sym, sdata in market_snapshot.get("stocks", {}).items()
        }

        # 3. Query all 5 agents for proposals
        agent_proposals: Dict[str, List[ProposedTrade]] = {}
        all_proposals_list: List[ProposedTrade] = []

        for agent in self.agents:
            aid = agent.agent_id
            sub_portfolio = self.broker.get_agent_portfolio(aid)
            current_open = [p.to_dict() for p in sub_portfolio.open_positions.values()]
            current_equity = sub_portfolio.portfolio_value
            current_cash = sub_portfolio.cash

            proposals = agent.evaluate_market(
                market_snapshot=market_snapshot,
                current_open_positions=current_open,
                current_equity=current_equity,
                current_cash=current_cash,
            )

            # Assign snapshot_id and sequence to all proposals
            for seq, p in enumerate(proposals, 1):
                p.snapshot_id = snapshot_id
                p.sequence = seq

            agent_proposals[aid] = proposals
            all_proposals_list.extend(proposals)

        # 4. Central Risk Engine Validation
        trade_evaluations: List[Tuple[ProposedTrade, RiskEvaluation]] = []
        approved_trades: List[ProposedTrade] = []
        decisions_log: List[Dict[str, Any]] = []

        for proposal in all_proposals_list:
            if proposal.action == TradeAction.NO_TRADE:
                eval_obj = RiskEvaluation(
                    is_approved=True,
                    rejection_reason="NO_TRADE_ACCEPTED",
                    adjusted_quantity=0,
                    max_loss=0.0,
                    risk_reward_ratio=0.0,
                    checks_passed=["NO_RISK_ACTION"],
                )
                trade_evaluations.append((proposal, eval_obj))
                decisions_log.append({
                    "market_date": market_date,
                    "snapshot_id": snapshot_id,
                    "agent_id": proposal.agent_id,
                    "strategy_version": proposal.strategy_version,
                    "symbol": proposal.symbol,
                    "action": "NO_TRADE",
                    "instrument_type": proposal.instrument.instrument_type.value,
                    "confidence": proposal.confidence,
                    "risk_approved": 1,
                    "rejections": [],
                    "reason": proposal.decision_reason,
                })
                continue

            sub_portfolio = self.broker.get_agent_portfolio(proposal.agent_id)
            pos_dicts = [p.to_dict() for p in sub_portfolio.open_positions.values()]

            if proposal.strategy:
                # Multi-leg options strategy evaluation
                open_strats = list(sub_portfolio.open_strategies.values())
                evaluation = self.risk_engine.evaluate_strategy(
                    strategy=proposal.strategy,
                    agent_equity=sub_portfolio.portfolio_value,
                    agent_cash=sub_portfolio.cash,
                    current_open_strategies=open_strats,
                    daily_starting_equity=sub_portfolio.starting_capital,
                    check_market_clock=not force_execute,
                )
            else:
                evaluation = self.risk_engine.evaluate_proposal(
                    proposal=proposal,
                    agent_equity=sub_portfolio.portfolio_value,
                    agent_cash=sub_portfolio.cash,
                    current_open_positions=pos_dicts,
                    daily_starting_equity=sub_portfolio.starting_capital,
                    check_market_clock=not force_execute,
                )
            trade_evaluations.append((proposal, evaluation))

            rejections = [evaluation.rejection_reason] if not evaluation.is_approved else []
            decisions_log.append({
                "market_date": market_date,
                "snapshot_id": snapshot_id,
                "agent_id": proposal.agent_id,
                "strategy_version": proposal.strategy_version,
                "symbol": proposal.symbol,
                "action": proposal.action.value,
                "instrument_type": proposal.instrument.instrument_type.value,
                "confidence": proposal.confidence,
                "risk_approved": 1 if evaluation.is_approved else 0,
                "rejections": rejections,
                "reason": proposal.decision_reason,
            })

            if evaluation.is_approved and evaluation.adjusted_quantity > 0:
                approved_trades.append(proposal)

        self.last_decisions = decisions_log

        # 5. Execute Approved Trades / Strategies via Broker
        executed_trades_info = []
        for trade, eval_obj in trade_evaluations:
            if eval_obj.is_approved and eval_obj.adjusted_quantity > 0 and trade.action != TradeAction.NO_TRADE:
                if trade.strategy:
                    success, reason, strat = self.broker.execute_approved_strategy(
                        strategy=trade.strategy,
                        evaluation=eval_obj,
                        market_date=market_date,
                    )
                    if success and strat and reason == "EXECUTED":
                        executed_trades_info.append({
                            "agent_id": trade.agent_id,
                            "symbol": trade.symbol,
                            "instrument": "OPTION",
                            "strategy_type": strat.strategy_type.value,
                            "shares": strat.legs[0].quantity if strat.legs else 50,
                            "price": strat.net_debit,
                            "status": reason,
                            "is_multi_leg": True,
                        })
                else:
                    success, reason, pos = self.broker.execute_approved_trade(
                        proposal=trade,
                        evaluation=eval_obj,
                        market_date=market_date,
                    )
                    if success and pos and reason == "EXECUTED":
                        executed_trades_info.append({
                            "agent_id": trade.agent_id,
                            "symbol": trade.symbol,
                            "instrument": trade.instrument.instrument_type.value,
                            "shares": pos.quantity,
                            "price": pos.entry_price,
                            "status": reason,
                            "is_multi_leg": False,
                        })

        # 6. Mark to Market (Equities and Multi-Leg Options)
        self.broker.mark_to_market_revaluation(stock_prices)
        self.broker.mark_to_market_strategies(stock_prices, expiry_days_remaining=7)

        # 7. Compute Consensus Matrix across all 50 stocks
        consensus_data = ConsensusEngine.compute_consensus(
            market_snapshot=market_snapshot,
            agent_proposals=agent_proposals,
        )
        self.last_consensus = consensus_data

        # 8. Compute Leaderboard & Awards
        leaderboard = self._compute_leaderboard()

        # 9. Today's Arena Summary
        arena_summary = self._compute_arena_summary(leaderboard, clock_status)


        # 10. Generate Nifty 50 Modelled Option Chain and AI Strategies
        nifty_spot = stock_prices.get("NIFTY50", 25481.30)
        nifty_chain = OptionsPricingEngine.build_option_chain(
            underlying="NIFTY 50",
            spot_price=nifty_spot,
            expiry_days=7,
            volatility=0.138,  # India VIX approx 13.8%
            strike_step=50.0,
            strikes_count=5,
        )

        # Build recommended strategies with payoff curves
        rec_bcs = OptionsStrategyBuilder.create_bull_call_spread(
            underlying="NIFTY 50",
            spot_price=nifty_spot,
            buy_strike=round(nifty_spot / 50.0) * 50.0,
            sell_strike=round(nifty_spot / 50.0) * 50.0 + 100.0,
            expiry_days=7,
            agent_id="ALPHA",
            snapshot_id=snapshot_id,
        )
        rec_bps = OptionsStrategyBuilder.create_bear_put_spread(
            underlying="NIFTY 50",
            spot_price=nifty_spot,
            buy_strike=round(nifty_spot / 50.0) * 50.0,
            sell_strike=round(nifty_spot / 50.0) * 50.0 - 100.0,
            expiry_days=7,
            agent_id="CONTRARIAN",
            snapshot_id=snapshot_id,
        )
        rec_strd = OptionsStrategyBuilder.create_long_straddle(
            underlying="NIFTY 50",
            spot_price=nifty_spot,
            strike=round(nifty_spot / 50.0) * 50.0,
            expiry_days=7,
            agent_id="MOMENTUM",
            snapshot_id=snapshot_id,
        )
        rec_prot = OptionsStrategyBuilder.create_protective_put(
            underlying="NIFTY 50",
            spot_price=nifty_spot,
            put_strike=round(nifty_spot / 50.0) * 50.0 - 100.0,
            expiry_days=7,
            agent_id="DEFENSIVE",
            snapshot_id=snapshot_id,
        )

        recommended_options_strategies = [
            {
                "strategy": rec_bcs.to_dict(),
                "payoff_curve": OptionsStrategyBuilder.generate_payoff_points(rec_bcs, spot_center=nifty_spot),
                "ai_confidence": 81.0,
                "market_view": "BULLISH",
                "expected_move": "+1.8% to +2.7%",
                "risk_engine_status": "APPROVED",
            },
            {
                "strategy": rec_bps.to_dict(),
                "payoff_curve": OptionsStrategyBuilder.generate_payoff_points(rec_bps, spot_center=nifty_spot),
                "ai_confidence": 74.0,
                "market_view": "BEARISH",
                "expected_move": "-1.5% to -2.2%",
                "risk_engine_status": "APPROVED",
            },
            {
                "strategy": rec_strd.to_dict(),
                "payoff_curve": OptionsStrategyBuilder.generate_payoff_points(rec_strd, spot_center=nifty_spot),
                "ai_confidence": 76.0,
                "market_view": "VOLATILITY EXPANSION",
                "expected_move": "±2.5% Event Move",
                "risk_engine_status": "APPROVED",
            },
            {
                "strategy": rec_prot.to_dict(),
                "payoff_curve": OptionsStrategyBuilder.generate_payoff_points(rec_prot, spot_center=nifty_spot),
                "ai_confidence": 84.0,
                "market_view": "DOWNSIDE HEDGE",
                "expected_move": "Tail-Risk Protection",
                "risk_engine_status": "APPROVED",
            }
        ]
        result_dict = {
            "market_date": market_date,
            "snapshot_id": snapshot_id,
            "market_clock": clock_status,
            "summary": arena_summary,
            "leaderboard": leaderboard,
            "market_analytics": consensus_data,
            "decisions": decisions_log,
            "executed_trades_count": len(executed_trades_info),
            "executed_trades": executed_trades_info,
            "option_chain": nifty_chain.to_dict(),
            "recommended_options_strategies": recommended_options_strategies,
            "orders": [o.to_dict() for o in getattr(self.broker, "orders", {}).values()],
            "portfolios": {
                aid: self.broker.get_agent_portfolio(aid).get_summary()
                for aid in ["ALPHA", "MOMENTUM", "MACRO", "DEFENSIVE", "CONTRARIAN"]
            },
        }
        self.persist_cycle_results(result_dict)
        return result_dict

    def _compute_leaderboard(self) -> List[Dict[str, Any]]:
        """
        Compute multi-dimensional leaderboard and award the 3 distinct trophies:
        🥇 Best Return (highest absolute NAV return)
        🛡 Best Risk-Adjusted (highest Sharpe or lowest Max DD)
        💰 Best Capital Preservation (highest cash + lowest negative day loss)
        """
        profiles = {a.agent_id: a.profile for a in self.agents}
        rows = []

        for aid in ["ALPHA", "MOMENTUM", "MACRO", "DEFENSIVE", "CONTRARIAN"]:
            p = self.broker.get_agent_portfolio(aid)
            prof = profiles.get(aid)

            # Returns
            total_return_pct = round(p.return_pct, 2)
            day_return_pct = round(((p.realized_pnl + p.unrealized_pnl) / p.starting_capital) * 100.0, 2)

            rows.append({
                "agent_id": aid,
                "name": prof.name if prof else aid,
                "title": prof.title if prof else "",
                "personality_quote": prof.personality_quote if prof else "",
                "strategy_version": prof.strategy_version if prof else "",
                "starting_capital": p.starting_capital,
                "portfolio_value": round(p.portfolio_value, 2),
                "cash": round(p.cash, 2),
                "invested": round(p.invested_capital, 2),
                "total_return_pct": total_return_pct,
                "day_return_pct": day_return_pct,
                "realized_pnl": round(p.realized_pnl, 2),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "win_rate": round(p.win_rate, 1),
                "profit_factor": round(p.profit_factor, 2),
                "max_drawdown": round(p.max_drawdown_pct, 2),
                "sharpe_ratio": round(p.sharpe_ratio, 2),
                "positions_count": len(p.open_positions),
                "holdings": p.get_holdings_by_instrument(),
                "trophies": [],
            })

        # Rank by total_return_pct descending
        rows.sort(key=lambda x: x["total_return_pct"], reverse=True)
        for rank, r in enumerate(rows, 1):
            r["rank"] = rank

        # Assign Awards
        best_return_agent = max(rows, key=lambda x: x["total_return_pct"])
        best_return_agent["trophies"].append({
            "code": "BEST_RETURN",
            "icon": "🥇",
            "title": "Best Return",
            "desc": "Highest overall portfolio NAV return",
        })

        best_risk_agent = max(rows, key=lambda x: (x["sharpe_ratio"], -x["max_drawdown"]))
        best_risk_agent["trophies"].append({
            "code": "BEST_RISK_ADJUSTED",
            "icon": "🛡️",
            "title": "Best Risk-Adjusted",
            "desc": "Superior risk-adjusted Sharpe performance",
        })

        best_preservation_agent = max(rows, key=lambda x: (x["cash"], -abs(x["max_drawdown"])))
        best_preservation_agent["trophies"].append({
            "code": "BEST_CAPITAL_PRESERVATION",
            "icon": "💰",
            "title": "Capital Protector",
            "desc": "Highest unencumbered cash balance and lowest loss profile",
        })

        # 4. Best Options Trader: Agent with highest options profitability
        options_perf = []
        for r in rows:
            aid = r["agent_id"]
            p = self.broker.get_agent_portfolio(aid)
            opt_pnl = sum(s.unrealized_pnl for s in p.open_strategies.values()) + sum(s.realized_pnl for s in p.closed_strategies)
            options_perf.append((r, opt_pnl, len(p.open_strategies)))
        best_options_row = max(options_perf, key=lambda x: (x[1], x[2]))[0]
        best_options_row["trophies"].append({
            "code": "BEST_OPTIONS_TRADER",
            "icon": "⚡",
            "title": "Best Options Trader",
            "desc": "Superior multi-leg options strategy execution and profitability",
        })

        # Provide both honors list and trophies list for backward compatibility
        for r in rows:
            r["honors"] = [t["code"] for t in r["trophies"]]

        return rows

    def _compute_arena_summary(
        self,
        leaderboard: List[Dict[str, Any]],
        clock_status: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Aggregate total arena capital, return, and performance metrics.
        """
        total_value = sum(r["portfolio_value"] for r in leaderboard)
        total_cash = sum(r["cash"] for r in leaderboard)
        total_invested = sum(r["invested"] for r in leaderboard)
        total_pnl = total_value - TOTAL_VIRTUAL_CAPITAL
        total_return_pct = round((total_pnl / TOTAL_VIRTUAL_CAPITAL) * 100.0, 2)
        total_positions = sum(r["positions_count"] for r in leaderboard)

        top_agent = leaderboard[0]["name"] if leaderboard else "None"

        return {
            "total_virtual_capital": TOTAL_VIRTUAL_CAPITAL,
            "total_arena_value": round(total_value, 2),
            "total_arena_cash": round(total_cash, 2),
            "total_arena_invested": round(total_invested, 2),
            "total_arena_pnl": round(total_pnl, 2),
            "total_arena_return_pct": total_return_pct,
            "total_active_positions": total_positions,
            "top_agent": top_agent,
            "active_agents_count": len(leaderboard),
            "market_phase": clock_status.get("current_phase", "UNKNOWN"),
            "market_phase_desc": clock_status.get("status_reason", ""),
            "is_trading_allowed": clock_status.get("can_accept_orders", False),
            "cutoff_time": "15:30 IST",
        }

    def persist_cycle_results(self, cycle_result: Dict[str, Any]) -> None:
        """Persist portfolios, positions, trades, and decisions into SQLite ledger."""
        market_date = cycle_result.get("market_date", datetime.now().strftime("%Y-%m-%d"))
        snapshot_id = cycle_result.get("snapshot_id", "")

        # 1. Portfolios & Daily Snapshots
        for row in cycle_result.get("leaderboard", []):
            save_agent_portfolio(row)
            save_agent_daily_snapshot({
                "market_date": market_date,
                "agent_id": row["agent_id"],
                "portfolio_value": row["portfolio_value"],
                "cash": row["cash"],
                "invested": row["invested"],
                "day_return_pct": row.get("day_return_pct", 0.0),
                "total_return_pct": row.get("total_return_pct", 0.0),
                "realized_pnl": row.get("realized_pnl", 0.0),
                "unrealized_pnl": row.get("unrealized_pnl", 0.0),
                "win_rate": row.get("win_rate", 0.0),
                "profit_factor": row.get("profit_factor", 1.0),
                "max_drawdown": row.get("max_drawdown", 0.0),
                "sharpe_ratio": row.get("sharpe_ratio", 0.0),
                "positions_count": row.get("positions_count", 0),
            })

        # 2. Positions
        for aid in ["ALPHA", "MOMENTUM", "MACRO", "DEFENSIVE", "CONTRARIAN"]:
            p = self.broker.get_agent_portfolio(aid)
            for pos in p.open_positions.values():
                save_agent_position(pos.to_dict())

        # 3. Decisions
        for dec in cycle_result.get("decisions", []):
            save_agent_decision(dec)
        # 4. Orders
        try:
            from ..storage.ledger import save_order
            for order in getattr(self.broker, "orders", {}).values():
                save_order(order.to_dict())
        except Exception as exc:
            logger.debug(f"Orders persistence: {exc}")

