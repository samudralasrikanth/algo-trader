# =============================================================================
# event_agent/broker/broker_adapter.py — Broker Adapter Interface & Implementations
# =============================================================================
"""
Provides swappable broker adapter interface:
- BrokerAdapter (ABC)
- InternalPaperBroker (Default high-fidelity paper broker)
- UpstoxSandboxAdapter (Architecture-ready sandbox adapter)
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .order import ExecutionMode, Order, OrderFill, OrderSide, OrderStatus, OrderType

logger = logging.getLogger(__name__)


class BrokerAdapter(ABC):
    """Abstract Broker Adapter interface."""

    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        ...

    @abstractmethod
    def modify_order(self, order_id: str, new_price: float, new_quantity: int) -> Order:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> Order:
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        ...

    @abstractmethod
    def get_positions(self, portfolio_id: str) -> List[Any]:
        ...

    @abstractmethod
    def get_balance(self, portfolio_id: str) -> Dict[str, float]:
        ...


class InternalPaperBroker(BrokerAdapter):
    def execute_order(self, order: Order, market_price: float = 0.0) -> Dict[str, Any]:
        self.submit_order(order)
        price = market_price if market_price > 0 else (order.limit_price or order.requested_price)
        fill = OrderFill(
            fill_id=f"FILL-{order.order_id}",
            order_id=order.order_id,
            fill_price=price,
            fill_quantity=order.quantity,
            slippage=0.0,
            charges=0.0,
        )
        order.apply_fill(fill)
        return {
            "status": order.status.value,
            "order_id": order.order_id,
            "execution_price": order.fill_price,
            "quantity": order.fill_quantity,
        }

    """
    Internal paper broker simulating realistic order lifecycle transitions,
    state tracking, and sub-portfolio balances.
    """

    def __init__(self):
        self.orders: Dict[str, Order] = {}
        self.balances: Dict[str, float] = {}

    def submit_order(self, order: Order) -> Order:
        """Transition order from CREATED to SUBMITTED."""
        order.status = OrderStatus.SUBMITTED
        self.orders[order.order_id] = order
        logger.debug(f"Order {order.order_id} submitted to InternalPaperBroker.")
        return order

    def modify_order(self, order_id: str, new_price: float, new_quantity: int) -> Order:
        order = self.orders.get(order_id)
        if not order:
            raise KeyError(f"Order {order_id} not found.")
        if not order.is_active():
            raise ValueError(f"Cannot modify terminal order {order_id} (status: {order.status}).")
        order.requested_price = new_price
        order.quantity = new_quantity
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if not order:
            raise KeyError(f"Order {order_id} not found.")
        if not order.is_active():
            return order
        order.status = OrderStatus.CANCELLED
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def get_positions(self, portfolio_id: str) -> List[Any]:
        return []

    def get_balance(self, portfolio_id: str) -> Dict[str, float]:
        bal = self.balances.get(portfolio_id, 20_00_000.0)
        return {"cash": bal, "currency": "INR"}


class UpstoxSandboxAdapter(BrokerAdapter):
    def execute_order(self, order: Order, market_price: float = 0.0) -> Dict[str, Any]:
        self.submit_order(order)
        return {
            "status": "ACCEPTED",
            "broker_order_id": f"UPSTOX-SBX-{order.order_id}",
            "order_id": order.order_id,
            "message": "Order accepted in Upstox sandbox mode",
        }

    """
    Architecture-ready adapter for Upstox Sandbox / Developer API.
    Operates in simulated sandbox mode when no credentials are provided.
    """

    def __init__(self, api_key: Optional[str] = None, access_token: Optional[str] = None):
        self.api_key = api_key
        self.access_token = access_token
        self.orders: Dict[str, Order] = {}
        self.is_connected = bool(api_key and access_token)

    def submit_order(self, order: Order) -> Order:
        order.execution_mode = ExecutionMode.BROKER_SANDBOX
        order.status = OrderStatus.SUBMITTED
        self.orders[order.order_id] = order
        logger.info(f"Order {order.order_id} routed to UpstoxSandboxAdapter (sandbox_mode=True).")
        return order

    def modify_order(self, order_id: str, new_price: float, new_quantity: int) -> Order:
        order = self.orders.get(order_id)
        if order:
            order.requested_price = new_price
            order.quantity = new_quantity
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order and order.is_active():
            order.status = OrderStatus.CANCELLED
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def get_positions(self, portfolio_id: str) -> List[Any]:
        return []

    def get_balance(self, portfolio_id: str) -> Dict[str, float]:
        return {"cash": 20_00_000.0, "currency": "INR", "sandbox": True}
