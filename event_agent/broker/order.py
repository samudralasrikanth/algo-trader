# =============================================================================
# event_agent/broker/order.py — Paper Broker V2 Order Lifecycle & Models
# =============================================================================
"""
Order models and lifecycle state machine for Paper Broker V2:
CREATED -> SUBMITTED -> PENDING -> PARTIALLY_FILLED -> FILLED / REJECTED / CANCELLED / EXPIRED.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER_LIVE = "PAPER_LIVE"
    PAPER = "PAPER_LIVE"
    BROKER_SANDBOX = "BROKER_SANDBOX"


@dataclass
class OrderFill:
    """Individual fill execution record."""
    fill_id: str
    order_id: str
    fill_price: float
    fill_quantity: int
    slippage: float = 0.0
    charges: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Order:
    @classmethod
    def create(
        cls,
        order_id: str,
        agent_id: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        reference_price: float = 0.0,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        portfolio_id: Optional[str] = None,
        execution_mode: ExecutionMode = ExecutionMode.BROKER_SANDBOX,
        broker_adapter: str = "UPSTOX SANDBOX",
    ) -> "Order":
        return cls(
            order_id=order_id,
            portfolio_id=portfolio_id or f"PORT-{agent_id}",
            agent_id=agent_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            requested_price=reference_price,
            limit_price=limit_price,
            stop_price=stop_price,
            status=OrderStatus.CREATED,
            execution_mode=execution_mode,
            broker_adapter=broker_adapter,
            broker_order_id=f"UPSTOX-SBX-{order_id}",
        )

    def submit(self) -> None:
        if self.status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED):
            raise ValueError(f"Cannot submit order in terminal status {self.status}")
        self.status = OrderStatus.SUBMITTED

    def reject(self, reason: str) -> None:
        self.status = OrderStatus.REJECTED
        self.rejection_reason = reason

    def apply_fill(self, fill: OrderFill) -> None:
        self.fills.append(fill)
        total_qty = sum(f.fill_quantity for f in self.fills)
        total_val = sum(f.fill_price * f.fill_quantity for f in self.fills)
        self.fill_quantity = total_qty
        self.fill_price = round(total_val / total_qty, 2) if total_qty > 0 else fill.fill_price
        self.slippage = sum(f.slippage for f in self.fills)
        if total_qty >= self.quantity:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    @property
    def filled_quantity(self) -> int:
        return sum(f.fill_quantity for f in self.fills) if self.fills else self.fill_quantity

    @property
    def average_fill_price(self) -> float:
        if not self.fills:
            return self.fill_price or 0.0
        tot_val = sum(f.fill_price * f.fill_quantity for f in self.fills)
        tot_qty = sum(f.fill_quantity for f in self.fills)
        return round(tot_val / tot_qty, 2) if tot_qty > 0 else 0.0

    """Comprehensive Paper Broker V2 Order entity."""
    order_id: str
    portfolio_id: str
    agent_id: str
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    requested_price: float
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    fill_price: Optional[float] = None
    fill_quantity: int = 0
    slippage: float = 0.0
    estimated_charges: float = 0.0
    status: OrderStatus = OrderStatus.CREATED
    rejection_reason: str = ""
    strategy_id: Optional[str] = None
    trade_proposal_id: Optional[str] = None
    execution_mode: ExecutionMode = ExecutionMode.BROKER_SANDBOX
    broker_adapter: str = "UPSTOX SANDBOX"
    broker_order_id: Optional[str] = None
    fills: List[OrderFill] = field(default_factory=list)

    def is_active(self) -> bool:
        return self.status in (OrderStatus.CREATED, OrderStatus.SUBMITTED, OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED)

    def is_terminal(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "portfolio_id": self.portfolio_id,
            "agent_id": self.agent_id,
            "symbol": self.symbol,
            "side": self.side.value if hasattr(self.side, "value") else str(self.side),
            "quantity": self.quantity,
            "order_type": self.order_type.value if hasattr(self.order_type, "value") else str(self.order_type),
            "requested_price": round(self.requested_price, 2),
            "limit_price": round(self.limit_price, 2) if self.limit_price else None,
            "stop_price": round(self.stop_price, 2) if self.stop_price else None,
            "submitted_at": self.submitted_at,
            "fill_price": round(self.fill_price, 2) if self.fill_price else None,
            "fill_quantity": self.fill_quantity,
            "slippage": round(self.slippage, 2),
            "estimated_charges": round(self.estimated_charges, 2),
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "rejection_reason": self.rejection_reason,
            "strategy_id": self.strategy_id,
            "trade_proposal_id": self.trade_proposal_id,
            "execution_mode": self.execution_mode.value if hasattr(self.execution_mode, "value") else str(self.execution_mode),
            "broker_adapter": getattr(self, "broker_adapter", "UPSTOX SANDBOX"),
            "broker_order_id": getattr(self, "broker_order_id", f"UPSTOX-SBX-{self.order_id}"),
            "fills": [f.to_dict() for f in self.fills],
        }
