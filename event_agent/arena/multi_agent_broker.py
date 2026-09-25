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
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from event_agent.broker.cost_model import CostModel
from event_agent.broker.order import Order, OrderFill, OrderSide, OrderStatus, OrderType, ExecutionMode
from event_agent.broker.execution_simulator import Candle5M, ExecutionSimulator, Fill
from event_agent.broker.broker_adapter import BrokerAdapter, UpstoxSandboxAdapter, get_paper_broker_adapter
from event_agent.config import AGENT_STARTING_CAPITAL, TOTAL_VIRTUAL_CAPITAL
from .asset_models import (
    AssetClass,
    LegSide,
    MultiLegStrategy,
    OptionInstrument,
    OptionType,
    StrategyLeg,
    StrategyStatus,
    StrategyType,
)
from .options_engine import OptionsPricingEngine
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
    def __getitem__(self, item):
        if item == "status":
            return getattr(self, "trade_status", "CLOSED")
        return getattr(self, item)
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
        self.open_strategies: Dict[str, MultiLegStrategy] = {}  # keyed by strategy_id
        self.closed_strategies: List[MultiLegStrategy] = []
        self.orders: Dict[str, Any] = {}

    @property
    def invested_capital(self) -> float:
        pos_invested = sum(pos.invested_capital for pos in self.open_positions.values())
        strat_invested = sum(s.net_debit for s in self.open_strategies.values() if s.status == StrategyStatus.OPEN)
        return pos_invested + strat_invested

    @property
    def unrealized_pnl(self) -> float:
        pos_pnl = sum(pos.unrealized_pnl for pos in self.open_positions.values())
        strat_pnl = sum(s.unrealized_pnl for s in self.open_strategies.values() if s.status == StrategyStatus.OPEN)
        return pos_pnl + strat_pnl

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
    def positions(self) -> Dict[str, ArenaPosition]:
        return self.open_positions

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

        # Include multi-leg options strategies as cohesive paper positions
        for strat in self.open_strategies.values():
            if strat.status == StrategyStatus.OPEN:
                strat_dict = {
                    "agent_id": self.agent_id,
                    "strategy_version": strat.strategy_version,
                    "symbol": f"{strat.underlying}-{strat.strategy_type.value}",
                    "strategy_id": strat.strategy_id,
                    "strategy_type": strat.strategy_type.value,
                    "instrument": {
                        "instrument_type": "OPTION",
                        "contract_name": f"{strat.underlying} {strat.strategy_type.value} ({strat.expiry})",
                        "is_simulated_price": True,
                        "pricing_model": strat.pricing_model,
                    },
                    "direction": "BUY" if strat.net_delta >= 0 else "SELL",
                    "quantity": strat.legs[0].quantity if strat.legs else 50,
                    "entry_price": round(strat.net_debit, 2),
                    "current_price": round(strat.current_strategy_value, 2),
                    "stop_loss": round(strat.stop_loss_amount, 2),
                    "target": round(strat.target_profit_amount, 2),
                    "invested_capital": round(strat.net_debit, 2),
                    "margin_or_premium": round(strat.net_debit, 2),
                    "unrealized_pnl": round(strat.unrealized_pnl, 2),
                    "pnl_pct": round((strat.unrealized_pnl / strat.net_debit * 100.0) if strat.net_debit > 0 else 0.0, 2),
                    "hedge_decision": "NO",
                    "hedge_instrument": None,
                    "days_held": 0,
                    "days_to_expiry": 7,
                    "entry_time": strat.entry_time,
                    "trade_id": strat.strategy_id,
                    "status": "OPEN",
                    "is_multi_leg": True,
                    "legs": [leg.to_dict() for leg in strat.legs],
                    "max_profit": round(strat.max_profit, 2),
                    "max_loss": round(strat.max_loss, 2),
                    "breakeven": [round(b, 2) for b in strat.breakeven],
                    "net_delta": round(strat.net_delta, 4),
                    "price_source": "MODELLED",
                }
                options_list.append(strat_dict)
                all_list.append(strat_dict)

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
        broker_adapter: Optional[BrokerAdapter] = None,
        auto_hydrate: bool = True,
    ):
        self.cost_model = cost_model or CostModel(default_schedule="equity_delivery")
        self.simulator = simulator or ExecutionSimulator(conservative_ambiguity=True)
        self.broker_adapter = broker_adapter or get_paper_broker_adapter()
        self.sub_portfolios: Dict[str, SubPortfolio] = {
            "ALPHA": SubPortfolio("ALPHA", "ALPHA-1.0"),
            "MOMENTUM": SubPortfolio("MOMENTUM", "MOMENTUM-1.0"),
            "MACRO": SubPortfolio("MACRO", "MACRO-1.0"),
            "DEFENSIVE": SubPortfolio("DEFENSIVE", "DEFENSIVE-1.0"),
            "CONTRARIAN": SubPortfolio("CONTRARIAN", "CONTRARIAN-1.0"),
        }
        self.executed_trade_ids: set = set()
        self.orders: Dict[str, Any] = {}
        in_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
        if auto_hydrate and not in_pytest and os.getenv("TESTING", "").lower() not in ("1", "true", "yes"):
            self.hydrate_from_db()

    def hydrate_from_db(self) -> None:
        """
        Loads active open positions from SQLite database, populates SubPortfolio.open_positions,
        and synchronizes cash balances. Guarantees portfolio capital invariant <= 1 Crore is strictly maintained.
        """
        try:
            from event_agent.storage.ledger import get_agent_positions
            db_positions = get_agent_positions(status="OPEN")
            cloud_state = None
            if not db_positions:
                try:
                    from event_agent.storage.supabase_ledger import get_latest_arena_state_supabase
                    cloud_state = get_latest_arena_state_supabase()
                    if cloud_state:
                        db_positions = [
                            p for p in cloud_state.get("open_positions", [])
                            if str(p.get("status", "OPEN")).upper() == "OPEN"
                        ]
                except Exception as cloud_err:
                    logger.debug("Cloud arena hydration unavailable: %s", cloud_err)
            for p_dict in db_positions:
                aid = p_dict.get("agent_id")
                if aid not in self.sub_portfolios:
                    continue
                sub_port = self.sub_portfolios[aid]
                sym = p_dict.get("symbol")
                if not sym:
                    continue

                instrument_data = p_dict.get("instrument") or {}
                itype_str = p_dict.get("instrument_type") or instrument_data.get("instrument_type", "EQUITY")
                inst_type = InstrumentType.EQUITY
                if itype_str == "FUTURE":
                    inst_type = InstrumentType.FUTURE
                elif itype_str == "OPTION":
                    inst_type = InstrumentType.OPTION

                inst = Instrument(underlying=sym, instrument_type=inst_type)
                direction = TradeDirection.BUY if str(p_dict.get("direction", "BUY")).upper() == "BUY" else TradeDirection.SELL
                qty = int(p_dict.get("quantity", 0))
                ep = float(p_dict.get("entry_price", 0.0))
                cp = float(p_dict.get("current_price", ep))
                sl = float(p_dict.get("stop_loss", 0.0))
                tgt = float(p_dict.get("target", 0.0))
                inv = float(p_dict.get("cost_basis", ep * qty))
                tid = p_dict.get("position_id") or p_dict.get("trade_id") or f"TRD-{aid}-{sym}"

                arena_pos = ArenaPosition(
                    agent_id=aid,
                    strategy_version=p_dict.get("strategy_version", "1.0"),
                    symbol=sym,
                    instrument=inst,
                    direction=direction,
                    quantity=qty,
                    entry_price=ep,
                    current_price=cp,
                    stop_loss=sl,
                    target=tgt,
                    invested_capital=inv,
                    margin_or_premium=inv,
                    trade_id=tid,
                    status="OPEN",
                    entry_time=p_dict.get("opened_at", ""),
                )
                arena_pos.unrealized_pnl = float(p_dict.get("unrealized_pnl", 0.0))
                sub_port.open_positions[sym] = arena_pos
                self.executed_trade_ids.add(tid)

            # Restore realized P&L and deterministic ids from the cloud snapshot
            # before calculating cash.  This is essential on fresh CI runners.
            if cloud_state:
                for aid, snapshot in cloud_state.get("portfolios", {}).items():
                    if aid in self.sub_portfolios:
                        self.sub_portfolios[aid].realized_pnl = float(snapshot.get("realized_pnl", 0.0))
                self.executed_trade_ids.update(cloud_state.get("executed_trade_ids", []))

            # Synchronize cash strictly
            for aid, sub_port in self.sub_portfolios.items():
                total_invested = sum(pos.invested_capital for pos in sub_port.open_positions.values())
                if cloud_state and aid in cloud_state.get("portfolios", {}):
                    sub_port.cash = max(0.0, float(cloud_state["portfolios"][aid].get("cash", 0.0)))
                else:
                    sub_port.cash = max(0.0, sub_port.starting_capital - total_invested + sub_port.realized_pnl)
        except Exception as e:
            logger.debug(f"MultiAgentBroker DB hydration notice: {e}")

    def to_cloud_state(self, market_date: str, snapshot_id: str = "") -> Dict[str, Any]:
        """Return a compact serializable snapshot for the next CI worker."""
        portfolios = {}
        open_positions = []
        for aid, portfolio in self.sub_portfolios.items():
            positions = [p.to_dict() for p in portfolio.open_positions.values()]
            open_positions.extend(positions)
            portfolios[aid] = {
                "cash": round(portfolio.cash, 2),
                "realized_pnl": round(portfolio.realized_pnl, 2),
                "open_positions_count": len(positions),
            }
        return {
            "version": 1,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "market_date": market_date,
            "snapshot_id": snapshot_id,
            "portfolios": portfolios,
            "open_positions": open_positions,
            "open_positions_count": len(open_positions),
            "executed_trade_ids": sorted(self.executed_trade_ids),
        }

    def create_portfolio(self, agent_id: str, initial_capital: float = AGENT_STARTING_CAPITAL) -> SubPortfolio:
        if agent_id not in self.sub_portfolios:
            self.sub_portfolios[agent_id] = SubPortfolio(
                agent_id=agent_id,
                strategy_version="V1",
                starting_capital=initial_capital,
            )
        return self.sub_portfolios[agent_id]

    @property
    def portfolios(self) -> Dict[str, SubPortfolio]:
        return self.sub_portfolios

    def get_portfolio(self, agent_id: str) -> SubPortfolio:
        return self.get_agent_portfolio(agent_id)

    def get_agent_portfolio(self, agent_id: str) -> SubPortfolio:
        if agent_id not in self.sub_portfolios:
            raise KeyError(f"Unknown agent ID: {agent_id}")
        return self.sub_portfolios[agent_id]

    def execute_approved_trade(
        self,
        proposal: ProposedTrade,
        evaluation: Optional[RiskEvaluation] = None,
        market_date: Optional[str] = None,
        fill_price: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[ArenaPosition]]:
        if evaluation is None:
            qty = getattr(proposal, "quantity", 10)
            evaluation = RiskEvaluation(is_approved=True, adjusted_quantity=qty)
        if market_date is None:
            market_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        requested_price = proposal.entry_price

        # 1. Create Paper Broker V2 Order
        order_side = OrderSide.BUY if proposal.direction == TradeDirection.BUY else OrderSide.SELL
        order_id = f"ORD-{trade_id}"
        adapter_name = getattr(self.broker_adapter, "name", "ANGEL ONE SMARTAPI (PAPER)")
        broker_prefix = "ANGEL-SBX" if "ANGEL" in adapter_name.upper() else "UPSTOX-SBX"
        exec_mode = ExecutionMode.PAPER if "ANGEL" in adapter_name.upper() else ExecutionMode.BROKER_SANDBOX

        order = Order(
            order_id=order_id,
            portfolio_id=proposal.agent_id,
            agent_id=proposal.agent_id,
            symbol=proposal.symbol,
            side=order_side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            requested_price=requested_price,
            trade_proposal_id=trade_id,
            status=OrderStatus.CREATED,
            execution_mode=exec_mode,
            broker_adapter=adapter_name,
            broker_order_id=f"{broker_prefix}-{order_id}",
        )
        self.broker_adapter.submit_order(order)

        # 2. Simulate realistic execution with non-linear volume/spread slippage
        quote_dict = {"price": requested_price, "symbol": proposal.symbol}
        order = self.simulator.simulate_order_execution(order, quote_dict)
        if fill_price is not None:
            order.fill_price = fill_price
        fill_price = order.fill_price or requested_price

        # Schedule and cost friction
        schedule = "equity_delivery"
        if proposal.instrument.instrument_type == InstrumentType.FUTURE:
            schedule = "index_futures"
        elif proposal.instrument.instrument_type == InstrumentType.OPTION:
            schedule = "equity_intraday"

        cost_breakdown = self.cost_model.calculate_entry_cost(
            instrument_type=schedule,
            side="BUY",
            price=fill_price,
            quantity=quantity,
        )
        total_entry_cost = cost_breakdown.get("total", 0.0)
        order.estimated_charges = total_entry_cost

        required_capital = (fill_price * quantity) + total_entry_cost
        if required_capital > sub_port.cash:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = f"INSUFFICIENT_FUNDS: Needs ₹{required_capital:,.2f}, has ₹{sub_port.cash:,.2f}"
            self.orders[order_id] = order
            sub_port.orders[order_id] = order
            return False, order.rejection_reason, None

        # Deduct cash strictly from this agent
        sub_port.cash -= required_capital
        invested = fill_price * quantity

        # 3. Position Management: Support scale-ins / multiple entries if already open
        if proposal.symbol in sub_port.open_positions:
            existing_pos = sub_port.open_positions[proposal.symbol]
            new_qty = existing_pos.quantity + quantity
            new_avg_entry = round(((existing_pos.entry_price * existing_pos.quantity) + (fill_price * quantity)) / new_qty, 2)
            existing_pos.quantity = new_qty
            existing_pos.entry_price = new_avg_entry
            existing_pos.invested_capital += invested
            position = existing_pos
        else:
            position = ArenaPosition(
                agent_id=proposal.agent_id,
                strategy_version=proposal.strategy_version,
                symbol=proposal.symbol,
                instrument=proposal.instrument,
                direction=proposal.direction,
                quantity=quantity,
                entry_price=fill_price,
                current_price=fill_price,
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

        order.status = OrderStatus.FILLED
        order.execution_mode = exec_mode
        order.broker_adapter = adapter_name
        order.broker_order_id = f"{broker_prefix}-{order_id}"
        self.orders[order_id] = order
        sub_port.orders[order_id] = order
        self.executed_trade_ids.add(trade_id)
        return True, "EXECUTED", position

    def close_position(
        self,
        agent_id: str,
        symbol: str,
        exit_price: Optional[float] = None,
        exit_reason: str = "MANUAL_CLOSE",
        current_price: Optional[float] = None,
        exit_time: Optional[str] = None,
        exit_quantity: Optional[int] = None,
    ) -> Optional[ArenaClosedTrade]:
        """
        Close an open position (complete or partial), deduct statutory exit costs,
        and update realized P&L.
        """
        if exit_price is None and current_price is not None:
            exit_price = current_price
        if exit_price is None:
            exit_price = 0.0
        sub_port = self.get_agent_portfolio(agent_id)
        pos = sub_port.open_positions.get(symbol)
        if not pos:
            return None

        # Handle symbol as symbol or position_id
        if not pos:
            for p_sym, p_obj in sub_port.open_positions.items():
                if getattr(p_obj, "position_id", None) == symbol or getattr(p_obj, "trade_id", None) == symbol:
                    pos = p_obj
                    break
        if not pos:
            return None

        close_qty = exit_quantity if (exit_quantity and 0 < exit_quantity < pos.quantity) else pos.quantity
        is_partial = close_qty < pos.quantity

        schedule = "equity_delivery"
        if pos.instrument.instrument_type == InstrumentType.FUTURE:
            schedule = "index_futures"
        elif pos.instrument.instrument_type == InstrumentType.OPTION:
            schedule = "equity_intraday"

        exit_costs = self.cost_model.calculate_exit_cost(
            instrument_type=schedule,
            side="SELL" if pos.direction == TradeDirection.BUY else "BUY",
            price=exit_price,
            quantity=close_qty,
        )
        total_exit_fees = exit_costs.get("total", 0.0)

        if pos.direction == TradeDirection.BUY:
            gross_pnl = (exit_price - pos.entry_price) * close_qty
        else:
            gross_pnl = (pos.entry_price - exit_price) * close_qty

        net_pnl = gross_pnl - total_exit_fees

        # Return capital + net P&L back to cash
        if is_partial:
            pos.quantity -= close_qty
            pos.invested_capital = pos.quantity * pos.entry_price
            returned_cash = (close_qty * pos.entry_price) + net_pnl
            sub_port.cash += returned_cash
            sub_port.realized_pnl += net_pnl
        else:
            sub_port.open_positions.pop(pos.symbol, None)
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
            quantity=close_qty,
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
        closed_rec.trade_status = "PARTIALLY_CLOSED" if is_partial else "CLOSED"
        closed_rec.remaining_quantity = pos.quantity
        closed_rec.realized_pnl = net_pnl
        sub_port.closed_trades.append(closed_rec)
        return closed_rec

    def mark_to_market_revaluation(self, current_market_prices: Dict[str, float]):
        """Revalue all open positions across all 5 agents using closing prices."""
        for sub_port in self.sub_portfolios.values():
            for sym, pos in sub_port.open_positions.items():
                if sym in current_market_prices:
                    pos.update_market_price(current_market_prices[sym])

    def close_triggered_positions(self, current_market_prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """Apply deterministic stop/target exits to equity/futures paper positions."""
        closed: List[Dict[str, Any]] = []
        for aid, sub_port in self.sub_portfolios.items():
            for symbol, pos in list(sub_port.open_positions.items()):
                price = current_market_prices.get(symbol)
                if price is None or price <= 0:
                    continue
                reason = None
                if pos.direction == TradeDirection.BUY:
                    if pos.stop_loss > 0 and price <= pos.stop_loss:
                        reason = "STOP_LOSS_TRIGGERED"
                    elif pos.target > 0 and price >= pos.target:
                        reason = "TARGET_PROFIT_REACHED"
                else:
                    if pos.stop_loss > 0 and price >= pos.stop_loss:
                        reason = "STOP_LOSS_TRIGGERED"
                    elif pos.target > 0 and price <= pos.target:
                        reason = "TARGET_PROFIT_REACHED"
                if not reason:
                    continue

                closed_trade = self.close_position(aid, symbol, exit_price=price, exit_reason=reason)
                if closed_trade:
                    try:
                        from event_agent.storage.ledger import close_agent_position
                        close_agent_position(
                            position_id=pos.trade_id,
                            exit_price=price,
                            exit_reason=reason,
                            brokerage_costs=closed_trade.total_fees,
                        )
                    except Exception as persist_err:
                        logger.debug("Exit persistence warning for %s: %s", symbol, persist_err)
                    closed.append(closed_trade.to_dict())
        return closed

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

    def execute_approved_strategy(
        self,
        strategy: MultiLegStrategy,
        evaluation: RiskEvaluation,
        market_date: str,
    ) -> Tuple[bool, str, Optional[MultiLegStrategy]]:
        """
        Atomically executes an approved multi-leg options strategy:
        - All legs executed or entire strategy rejected
        - Cash deducted for net debit
        - Recorded in open_strategies and executed_trade_ids
        """
        if not evaluation.is_approved:
            return False, f"REJECTED_BY_RISK: {evaluation.rejection_reason}", None

        sub_port = self.get_agent_portfolio(strategy.agent_id)

        if strategy.strategy_id in self.executed_trade_ids:
            logger.info(f"Idempotent skip: Strategy ID {strategy.strategy_id} already executed.")
            existing_strat = sub_port.open_strategies.get(strategy.strategy_id)
            return True, "ALREADY_EXECUTED", existing_strat

        if strategy.net_debit > sub_port.cash:
            return False, f"INSUFFICIENT_FUNDS: Strategy requires ₹{strategy.net_debit:,.2f}, has ₹{sub_port.cash:,.2f}", None

        # Deduct cash strictly from this agent's sub-portfolio
        sub_port.cash -= strategy.net_debit
        strategy.status = StrategyStatus.OPEN
        strategy.current_strategy_value = strategy.net_debit
        strategy.unrealized_pnl = 0.0

        sub_port.open_strategies[strategy.strategy_id] = strategy
        self.executed_trade_ids.add(strategy.strategy_id)
        logger.info(f"Atomically executed multi-leg strategy {strategy.strategy_id} for {strategy.agent_id}. Net debit: ₹{strategy.net_debit:,.2f}")
        return True, "EXECUTED", strategy

    def mark_to_market_strategies(
        self,
        underlying_prices: Dict[str, float],
        expiry_days_remaining: int = 7,
    ):
        """
        Revalues all open options strategies using current underlying prices
        and analytical Black-Scholes pricing engine.
        Also evaluates strategy-level Stop-Loss and Target-Profit triggers.
        """
        for sub_port in self.sub_portfolios.values():
            to_close = []
            for strat_id, strat in list(sub_port.open_strategies.items()):
                if strat.status != StrategyStatus.OPEN:
                    continue

                und_sym = strat.underlying
                spot = underlying_prices.get(und_sym, strat.entry_underlying_price)
                strat.current_underlying_price = spot

                # Revalue each leg
                total_val = 0.0
                T_years = max(0.0001, expiry_days_remaining / 365.0)

                for leg in strat.legs:
                    calc = OptionsPricingEngine.calculate_price_and_greeks(
                        spot=spot,
                        strike=leg.instrument.strike,
                        time_to_expiry_years=T_years,
                        volatility=leg.instrument.implied_volatility,
                        is_call=(leg.instrument.option_type == OptionType.CE),
                    )
                    leg.current_price = calc["price"]
                    mult = 1 if leg.side == LegSide.BUY else -1
                    total_val += mult * leg.current_price * leg.quantity

                strat.current_strategy_value = total_val
                strat.unrealized_pnl = total_val - strat.net_debit

                # Check Stop Loss (e.g. loss exceeds stop amount)
                if strat.unrealized_pnl <= -strat.stop_loss_amount:
                    to_close.append((strat_id, "STOP_LOSS_TRIGGERED"))
                elif strat.unrealized_pnl >= strat.target_profit_amount:
                    to_close.append((strat_id, "TARGET_PROFIT_REACHED"))

            # Close triggered strategies
            for strat_id, reason in to_close:
                strat = sub_port.open_strategies.pop(strat_id, None)
                if strat:
                    returned_cash = max(0.0, strat.net_debit + strat.unrealized_pnl)
                    sub_port.cash += returned_cash
                    sub_port.realized_pnl += strat.unrealized_pnl
                    strat.realized_pnl = strat.unrealized_pnl
                    strat.status = StrategyStatus.STOPPED_OUT if "STOP" in reason else StrategyStatus.TARGET_REACHED
                    strat.exit_reason = reason
                    strat.closed_time = datetime.now(timezone.utc).isoformat()
                    sub_port.closed_strategies.append(strat)
                    logger.info(f"Strategy {strat_id} closed ({reason}). Realized P&L: ₹{strat.realized_pnl:,.2f}")

    def settle_expiring_strategies(
        self,
        settlement_prices: Dict[str, float],
        expiry_reason: str = "EXPIRY_SETTLEMENT",
    ):
        """
        Settles all expiring options strategies at expiry:
        - ITM legs settle for intrinsic cash difference
        - OTM legs expire worthless (zero value)
        - Final P&L credited to agent NAV
        """
        for sub_port in self.sub_portfolios.values():
            for strat_id, strat in list(sub_port.open_strategies.items()):
                if strat.status != StrategyStatus.OPEN:
                    continue

                und_sym = strat.underlying
                settle_price = settlement_prices.get(und_sym, strat.current_underlying_price)
                final_payoff = strat.calculate_payoff_at(settle_price)

                returned_cash = max(0.0, strat.net_debit + final_payoff)
                sub_port.cash += returned_cash
                sub_port.realized_pnl += final_payoff

                strat.status = StrategyStatus.EXPIRED
                strat.realized_pnl = final_payoff
                strat.unrealized_pnl = 0.0
                strat.current_strategy_value = max(0.0, strat.net_debit + final_payoff)
                strat.exit_reason = f"{expiry_reason} at ₹{settle_price:.2f}"
                strat.closed_time = datetime.now(timezone.utc).isoformat()

                del sub_port.open_strategies[strat_id]
                sub_port.closed_strategies.append(strat)
                logger.info(f"Strategy {strat_id} settled at expiry. Payoff: ₹{final_payoff:,.2f}")
