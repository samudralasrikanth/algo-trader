# =============================================================================
# event_agent/arena/multi_agent_broker.py — Multi-Agent Paper Broker & Accounting
# =============================================================================
"""
Multi-Agent Paper Broker managing 5 isolated sub-portfolios:
- Total Virtual Capital: ₹1,00,00,000 (5 × ₹20,00,000)
- Strict Capital Isolation: One agent cannot spend or access another's funds
- Separate Holdings Buckets: Equity, Futures, Options, and All
- Explicit Price Provenance (Market vs Simulated/Modelled Derivatives)
- Idempotent execution using deterministic Trade IDs
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..broker.cost_model import CostModel
from ..broker.execution_simulator import Candle5M, ExecutionSimulator, Fill
from ..config import AGENT_STARTING_CAPITAL, TOTAL_VIRTUAL_CAPITAL
from .models import (
    HedgeDecision,
    Instrument,
    InstrumentType,
    OptionType,
    ProposedTrade,
    RiskEvaluation,
    TradeAction,
    TradeDirection,
)

logger = logging.getLogger(__name__)


@dataclass
class ArenaPosition:
    """Active open position in an agent's sub-portfolio."""
    agent_id: str
    strategy_version: str
    symbol: str
    instrument: Instrument
    direction: TradeDirection
    quantity: int
    entry_price: float
    current_price: float
    stop_loss: float
    target: float
    invested_capital: float
    margin_or_premium: float
    unrealized_pnl: float = 0.0
    hedge_decision: HedgeDecision = HedgeDecision.NO
    hedge_instrument: Optional[str] = None
    days_held: int = 0
    days_to_expiry: int = 30
    entry_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trade_id: str = ""
    status: str = "OPEN"

    def update_market_price(self, new_price: float):
        """Update current price and mark-to-market unrealized P&L."""
        self.current_price = new_price
        if self.direction == TradeDirection.BUY:
            self.unrealized_pnl = (new_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - new_price) * self.quantity

    def to_dict(self) -> Dict[str, Any]:
        pnl_pct = (self.unrealized_pnl / self.invested_capital * 100.0) if self.invested_capital > 0 else 0.0
        return {
            "agent_id": self.agent_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "instrument": self.instrument.to_dict(),
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 2),
            "current_price": round(self.current_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target": round(self.target, 2),
            "invested_capital": round(self.invested_capital, 2),
            "margin_or_premium": round(self.margin_or_premium, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "hedge_decision": self.hedge_decision.value,
            "hedge_instrument": self.hedge_instrument,
            "days_held": self.days_held,
            "days_to_expiry": self.days_to_expiry,
            "entry_time": self.entry_time,
            "trade_id": self.trade_id,
            "status": self.status,
        }


@dataclass
class ArenaClosedTrade:
    """Historical record of an executed and closed trade."""
    trade_id: str
    agent_id: str
    strategy_version: str
    symbol: str
    instrument: Instrument
    direction: TradeDirection
    quantity: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    total_fees: float
    net_pnl: float
    exit_reason: str
    entry_time: str
    exit_time: str
    decision_reason: str
    hedge_decision: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "agent_id": self.agent_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "instrument": self.instrument.to_dict(),
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "total_fees": round(self.total_fees, 2),
            "net_pnl": round(self.net_pnl, 2),
            "exit_reason": self.exit_reason,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "decision_reason": self.decision_reason,
            "hedge_decision": self.hedge_decision,
        }


class SubPortfolio:
    """
    Isolated sub-portfolio belonging to a single agent.
    Zero cross-contamination of cash or capital allowed.
    """

    def __init__(self, agent_id: str, strategy_version: str, starting_capital: float = AGENT_STARTING_CAPITAL):
        self.agent_id = agent_id
        self.strategy_version = strategy_version
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.realized_pnl = 0.0
        self.peak_portfolio_value = starting_capital
        self.open_positions: Dict[str, ArenaPosition] = {}  # keyed by symbol
        self.closed_trades: List[ArenaClosedTrade] = []

    @property
    def invested_capital(self) -> float:
        return sum(pos.invested_capital for pos in self.open_positions.values())

    @property
    def unrealized_pnl(self) -> float:
        return sum(pos.unrealized_pnl for pos in self.open_positions.values())

    @property
    def portfolio_value(self) -> float:
        return self.cash + self.invested_capital + self.unrealized_pnl

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def return_pct(self) -> float:
        if self.starting_capital <= 0:
            return 0.0
        return ((self.portfolio_value - self.starting_capital) / self.starting_capital) * 100.0

    @property
    def max_drawdown_pct(self) -> float:
        current_val = self.portfolio_value
        if current_val > self.peak_portfolio_value:
            self.peak_portfolio_value = current_val
        if self.peak_portfolio_value <= 0:
            return 0.0
        return ((self.peak_portfolio_value - current_val) / self.peak_portfolio_value) * 100.0

    @property
    def win_rate(self) -> float:
        wins = sum(1 for t in self.closed_trades if t.net_pnl > 0)
        total = len(self.closed_trades)
        return (wins / total * 100.0) if total > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.net_pnl for t in self.closed_trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in self.closed_trades if t.net_pnl < 0))
        return (gross_profit / gross_loss) if gross_loss > 0 else (2.5 if gross_profit > 0 else 1.0)

    @property
    def sharpe_ratio(self) -> float:
        if self.max_drawdown_pct > 0:
            return max(0.0, round(self.return_pct / self.max_drawdown_pct, 2))
        return round(max(0.5, 1.0 + self.return_pct / 10.0), 2)

    @property
    def status(self) -> str:
        if self.max_drawdown_pct >= 30.0:
            return 'SUSPENDED'
        elif self.max_drawdown_pct >= 20.0:
            return 'WARNING'
        return 'ACTIVE'

    @property
    def all_positions(self) -> List[ArenaPosition]:
        return list(self.open_positions.values())

    def get_holdings_by_instrument(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Return strictly separated holdings lists:
        equity, futures, options, and all.
        """
        equity_list = []
        futures_list = []
        options_list = []
        all_list = []

        for pos in self.open_positions.values():
            pos_dict = pos.to_dict()
            all_list.append(pos_dict)
            if pos.instrument.instrument_type == InstrumentType.EQUITY:
                equity_list.append(pos_dict)
            elif pos.instrument.instrument_type == InstrumentType.FUTURE:
                futures_list.append(pos_dict)
            elif pos.instrument.instrument_type == InstrumentType.OPTION:
                options_list.append(pos_dict)

        return {
            "equity": equity_list,
            "futures": futures_list,
            "options": options_list,
            "all": all_list,
        }

    def get_summary(self) -> Dict[str, Any]:
        wins = sum(1 for t in self.closed_trades if t.net_pnl > 0)
        losses = sum(1 for t in self.closed_trades if t.net_pnl < 0)
        total_closed = len(self.closed_trades)
        win_rate = (wins / total_closed * 100.0) if total_closed > 0 else 0.0

        gross_profit = sum(t.net_pnl for t in self.closed_trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in self.closed_trades if t.net_pnl < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (2.5 if gross_profit > 0 else 1.0)

        exposure_pct = (self.invested_capital / self.portfolio_value * 100.0) if self.portfolio_value > 0 else 0.0

        return {
            "agent_id": self.agent_id,
            "strategy_version": self.strategy_version,
            "starting_capital": self.starting_capital,
            "current_cash": round(self.cash, 2),
            "invested_capital": round(self.invested_capital, 2),
            "portfolio_value": round(self.portfolio_value, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "return_pct": round(self.return_pct, 2),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "total_trades": total_closed,
            "open_positions_count": len(self.open_positions),
            "exposure_pct": round(exposure_pct, 1),
        }


class MultiAgentBroker:
    """
    Autonomous multi-agent broker handling execution simulation, accounting,
    and portfolio isolation for all 5 Arena agents.
    """

    def __init__(
        self,
        cost_model: Optional[CostModel] = None,
        simulator: Optional[ExecutionSimulator] = None,
    ):
        self.cost_model = cost_model or CostModel(default_schedule="equity_delivery")
        self.simulator = simulator or ExecutionSimulator(conservative_ambiguity=True)
        self.sub_portfolios: Dict[str, SubPortfolio] = {
            "ALPHA": SubPortfolio("ALPHA", "ALPHA-1.0"),
            "MOMENTUM": SubPortfolio("MOMENTUM", "MOMENTUM-1.0"),
            "MACRO": SubPortfolio("MACRO", "MACRO-1.0"),
            "DEFENSIVE": SubPortfolio("DEFENSIVE", "DEFENSIVE-1.0"),
            "CONTRARIAN": SubPortfolio("CONTRARIAN", "CONTRARIAN-1.0"),
        }
        self.executed_trade_ids: set = set()

    def get_agent_portfolio(self, agent_id: str) -> SubPortfolio:
        if agent_id not in self.sub_portfolios:
            raise KeyError(f"Unknown agent ID: {agent_id}")
        return self.sub_portfolios[agent_id]

    def execute_approved_trade(
        self,
        proposal: ProposedTrade,
        evaluation: RiskEvaluation,
        market_date: str,
    ) -> Tuple[bool, str, Optional[ArenaPosition]]:
        """
        Execute an approved proposal idempotently in the agent's isolated portfolio.
        """
        if not evaluation.is_approved:
            return False, f"REJECTED_BY_RISK: {evaluation.rejection_reason}", None

        if proposal.action in (TradeAction.NO_TRADE, TradeAction.HOLD):
            return True, f"{proposal.action.value}_RECORDED", None

        trade_id = proposal.generate_trade_id(market_date)
        if trade_id in self.executed_trade_ids:
            logger.info(f"Idempotent skip: Trade ID {trade_id} already executed.")
            sub_port = self.get_agent_portfolio(proposal.agent_id)
            existing_pos = sub_port.open_positions.get(proposal.symbol)
            return True, "ALREADY_EXECUTED", existing_pos

        sub_port = self.get_agent_portfolio(proposal.agent_id)
        quantity = evaluation.adjusted_quantity
        entry_price = proposal.entry_price

        # Schedule and cost friction
        schedule = "equity_delivery"
        if proposal.instrument.instrument_type == InstrumentType.FUTURE:
            schedule = "index_futures"
        elif proposal.instrument.instrument_type == InstrumentType.OPTION:
            schedule = "equity_intraday"

        cost_breakdown = self.cost_model.calculate_entry_cost(
            instrument_type=schedule,
            side="BUY",
            price=entry_price,
            quantity=quantity,
        )
        total_entry_cost = cost_breakdown.get("total", 0.0)

        required_capital = (entry_price * quantity) + total_entry_cost
        if required_capital > sub_port.cash:
            return False, f"INSUFFICIENT_FUNDS: Needs ₹{required_capital:,.2f}, has ₹{sub_port.cash:,.2f}", None

        # Deduct cash strictly from this agent
        sub_port.cash -= required_capital
        invested = entry_price * quantity

        position = ArenaPosition(
            agent_id=proposal.agent_id,
            strategy_version=proposal.strategy_version,
            symbol=proposal.symbol,
            instrument=proposal.instrument,
            direction=proposal.direction,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=proposal.stop_loss,
            target=proposal.target,
            invested_capital=invested,
            margin_or_premium=invested,
            hedge_decision=proposal.hedge_decision,
            hedge_instrument=proposal.hedge_instrument,
            trade_id=trade_id,
            status="OPEN",
        )

        sub_port.open_positions[proposal.symbol] = position
        self.executed_trade_ids.add(trade_id)
        return True, "EXECUTED", position

    def close_position(
        self,
        agent_id: str,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        exit_time: Optional[str] = None,
    ) -> Optional[ArenaClosedTrade]:
        """Close an open position, deduct statutory exit costs, and update realized P&L."""
        sub_port = self.get_agent_portfolio(agent_id)
        pos = sub_port.open_positions.pop(symbol, None)
        if not pos:
            return None

        schedule = "equity_delivery"
        if pos.instrument.instrument_type == InstrumentType.FUTURE:
            schedule = "index_futures"
        elif pos.instrument.instrument_type == InstrumentType.OPTION:
            schedule = "equity_intraday"

        exit_costs = self.cost_model.calculate_exit_cost(
            instrument_type=schedule,
            side="SELL" if pos.direction == TradeDirection.BUY else "BUY",
            price=exit_price,
            quantity=pos.quantity,
        )
        total_exit_fees = exit_costs.get("total", 0.0)

        if pos.direction == TradeDirection.BUY:
            gross_pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            gross_pnl = (pos.entry_price - exit_price) * pos.quantity

        net_pnl = gross_pnl - total_exit_fees

        # Return capital + net P&L back to cash
        returned_cash = pos.invested_capital + net_pnl
        sub_port.cash += returned_cash
        sub_port.realized_pnl += net_pnl

        now_str = exit_time or datetime.now(timezone.utc).isoformat()
        closed_rec = ArenaClosedTrade(
            trade_id=pos.trade_id,
            agent_id=pos.agent_id,
            strategy_version=pos.strategy_version,
            symbol=pos.symbol,
            instrument=pos.instrument,
            direction=pos.direction,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            gross_pnl=gross_pnl,
            total_fees=total_exit_fees,
            net_pnl=net_pnl,
            exit_reason=exit_reason,
            entry_time=pos.entry_time,
            exit_time=now_str,
            decision_reason=f"Closed at ₹{exit_price:.2f} ({exit_reason})",
            hedge_decision=pos.hedge_decision.value,
        )
        sub_port.closed_trades.append(closed_rec)
        return closed_rec

    def mark_to_market_revaluation(self, current_market_prices: Dict[str, float]):
        """Revalue all open positions across all 5 agents using closing prices."""
        for sub_port in self.sub_portfolios.values():
            for sym, pos in sub_port.open_positions.items():
                if sym in current_market_prices:
                    pos.update_market_price(current_market_prices[sym])

    def get_total_arena_summary(self) -> Dict[str, Any]:
        """Aggregate performance summary across the entire ₹1 Crore virtual arena."""
        total_starting = sum(p.starting_capital for p in self.sub_portfolios.values())
        total_val = sum(p.portfolio_value for p in self.sub_portfolios.values())
        total_cash = sum(p.cash for p in self.sub_portfolios.values())
        total_invested = sum(p.invested_capital for p in self.sub_portfolios.values())
        total_pnl = sum(p.total_pnl for p in self.sub_portfolios.values())
        total_trades = sum(len(p.closed_trades) for p in self.sub_portfolios.values())
        total_return_pct = ((total_val - total_starting) / total_starting * 100.0) if total_starting > 0 else 0.0

        agent_summaries = [p.get_summary() for p in self.sub_portfolios.values()]

        return {
            "total_virtual_capital": total_starting,
            "current_portfolio_value": round(total_val, 2),
            "total_cash": round(total_cash, 2),
            "total_invested": round(total_invested, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round(total_return_pct, 2),
            "total_trades": total_trades,
            "agents": {s["agent_id"]: s for s in agent_summaries},
        }
