# =============================================================================
# tests/test_v364_upstox_sandbox_paper_trading.py
# Upstox Sandbox Paper Trading Integration & Routing Acceptance Suite
# =============================================================================
"""
Verifies that:
1. Upstox Sandbox Developer API credentials are securely configured and loaded.
2. All paper trading is routed to Upstox Sandbox rather than internal/inbuilt simulator.
3. Order lifecycle states (CREATED -> SUBMITTED -> FILLED) set BROKER_SANDBOX execution mode.
4. UpstoxSandboxAdapter provides OAuth dialog URLs and token exchange helpers.
5. MultiAgentBroker executes approved trades via UpstoxSandboxAdapter.
6. Web app frontend and data bundles reflect Upstox Sandbox execution.
"""

import json
import os
from pathlib import Path
import pytest

from event_agent.broker.order import ExecutionMode, Order, OrderSide, OrderStatus, OrderType
from event_agent.broker.broker_adapter import (
    BrokerAdapter,
    InternalPaperBroker,
    UpstoxSandboxAdapter,
    get_paper_broker_adapter,
)
from event_agent.arena.multi_agent_broker import MultiAgentBroker
from event_agent.arena.models import ProposedTrade, Instrument, InstrumentType, TradeDirection

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_DIR = WORKSPACE_ROOT / "web_app"
INDEX_HTML = WEB_APP_DIR / "index.html"
APP_JS = WEB_APP_DIR / "app.js"
DATA_JSON = WEB_APP_DIR / "data.json"


class TestUpstoxSandboxCredentialsAndAdapter:
    """Verifies Upstox Sandbox adapter initialization and credential handling."""

    def test_default_adapter_credentials(self):
        adapter = UpstoxSandboxAdapter()
        assert adapter.api_key == "5d237a8c-ac42-412b-9ec4-c60f21a495cd"
        assert adapter.api_secret == "bcg94q6w6a"
        assert adapter.sandbox is True
        assert adapter.is_connected is True

    def test_factory_returns_upstox_sandbox_by_default(self):
        adapter = get_paper_broker_adapter()
        assert isinstance(adapter, UpstoxSandboxAdapter)

    def test_oauth_login_url_generation(self):
        adapter = UpstoxSandboxAdapter()
        login_url = adapter.get_login_url(redirect_uri="https://127.0.0.1:5000/callback")
        assert "api.upstox.com/v2/login/authorization/dialog" in login_url
        assert "5d237a8c-ac42-412b-9ec4-c60f21a495cd" in login_url
        assert "redirect_uri=https://127.0.0.1:5000/callback" in login_url

    def test_token_exchange_simulation(self):
        adapter = UpstoxSandboxAdapter()
        token_res = adapter.exchange_code_for_token("auth_test_code_123")
        assert token_res["status"] == "SUCCESS"
        assert token_res["sandbox"] is True
        assert "access_token" in token_res

    def test_order_execution_in_upstox_sandbox(self):
        adapter = UpstoxSandboxAdapter()
        order = Order.create(
            order_id="ORD-TEST-SBX-01",
            agent_id="ALPHA",
            symbol="INFY.NS",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=50,
            reference_price=1850.0,
        )
        res = adapter.execute_order(order, market_price=1850.0)

        # Must conform to test_paper_trading_v2 expectations
        assert res["status"] == "ACCEPTED"
        assert "UPSTOX-SBX" in res["broker_order_id"]
        assert res["execution_status"] == "FILLED"
        assert res["broker"] == "Upstox Sandbox"
        assert order.status == OrderStatus.FILLED
        assert order.execution_mode == ExecutionMode.BROKER_SANDBOX
        assert order.broker_adapter == "UPSTOX SANDBOX"

    def test_place_sandbox_order_direct(self):
        adapter = UpstoxSandboxAdapter()
        res = adapter.place_sandbox_order(
            symbol="TCS.NS",
            quantity=25,
            side="BUY",
            order_type="MARKET",
            price=4200.0,
        )
        assert res["status"] == "ACCEPTED"
        assert res["quantity"] == 25
        assert res["broker"] == "Upstox Sandbox"

    def test_get_balance_sandbox(self):
        adapter = UpstoxSandboxAdapter()
        bal = adapter.get_balance("PORT-ALPHA")
        assert bal["sandbox"] is True
        assert bal["broker"] == "Upstox Sandbox"
        assert "5d23...5cd" in bal["api_key_masked"]


class TestMultiAgentBrokerUpstoxRouting:
    """Verifies that MultiAgentBroker routes orders to Upstox Sandbox."""

    def test_multi_agent_broker_uses_upstox_sandbox(self):
        broker = MultiAgentBroker()
        assert isinstance(broker.broker_adapter, UpstoxSandboxAdapter)

    def test_execute_approved_trade_routes_to_upstox_sandbox(self):
        broker = MultiAgentBroker()
        proposal = ProposedTrade.create_simple(
            "ALPHA",
            "RELIANCE.NS",
            "BUY",
            10,
            2900.0,
            2800.0,
            3100.0,
            confidence=85,
        )
        success, msg, pos = broker.execute_approved_trade(proposal, fill_price=2900.0)
        assert success is True
        assert pos is not None

        # Verify order in broker
        order_key = next(k for k in broker.orders.keys() if "RELIANCE" in k or "TRD" in k or "ORD" in k)
        order = broker.orders[order_key]
        assert order.status == OrderStatus.FILLED
        assert order.execution_mode == ExecutionMode.BROKER_SANDBOX
        assert order.broker_adapter == "UPSTOX SANDBOX"
        assert "UPSTOX-SBX" in getattr(order, "broker_order_id", "")


class TestFrontendUpstoxSandboxPresentation:
    """Verifies UI and data bundles present Upstox Sandbox as the active broker."""

    def test_index_html_displays_upstox_sandbox_active(self):
        content = INDEX_HTML.read_text(encoding="utf-8")
        assert "Broker: UPSTOX SANDBOX ACTIVE" in content
        assert "API Key: 5d23...5cd" in content
        assert "Upstox Sandbox (Developer API v2 Active)" in content
        assert "Broker: INTERNAL PAPER" not in content

    def test_app_js_uses_upstox_sandbox_broker(self):
        content = APP_JS.read_text(encoding="utf-8")
        assert "broker_adapter: 'UPSTOX SANDBOX'" in content
        assert "Upstox Sandbox (Developer API v2 Active)" in content
        assert "INTERNAL PAPER BROKER" not in content

    def test_data_json_orders_use_broker_sandbox(self):
        data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
        orders = data.get("orders", [])
        assert len(orders) > 0
        for order in orders:
            assert order["execution_mode"] == "BROKER_SANDBOX"
            assert order["broker_adapter"] == "UPSTOX SANDBOX"
            assert "UPSTOX-SBX" in order["broker_order_id"]
        
        telemetry = data.get("execution_telemetry", {})
        assert telemetry.get("mode") == "UPSTOX_SANDBOX"
        assert telemetry.get("broker_adapter") == "UPSTOX SANDBOX"
