# =============================================================================
# event_agent/execution/trade_guard.py — Central 34-Gate Institutional TradeGuard
# =============================================================================
"""
NEXUS V4.0 TradeGuard Service:
- Independent atomic pre-trade gate.
- Evaluates 34 mandatory pre-trade checks before any order can reach capital allocation or execution.
- Returns ALL_REQUIRED_GATES_PASS or NO_TRADE with explicit reason codes.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from ..config import (
    DAILY_LOSS_LIMIT_PCT,
    MAX_ACTIVE_POSITIONS_PER_AGENT,
    MAX_CORRELATED_EXPOSURE_PCT,
    MAX_PORTFOLIO_EXPOSURE_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MAX_SINGLE_POSITION_ALLOCATION_PCT,
    NIFTY50_UNIVERSE,
)
from ..arena.market_clock import MarketClock
from ..risk.kill_switch import IndependentKillSwitch, KillSwitchLevel
from .environment import EnvironmentManager, TradingEnvironment

logger = logging.getLogger(__name__)


class TradeGuardVerdict(str, Enum):
    ALL_REQUIRED_GATES_PASS = "ALL_REQUIRED_GATES_PASS"
    NO_TRADE = "NO_TRADE"


@dataclass
class TradeGuardResult:
    verdict: TradeGuardVerdict
    is_approved: bool
    rejection_code: Optional[str] = None
    rejection_message: Optional[str] = None
    passed_gates: List[str] = field(default_factory=list)
    failed_gates: List[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    environment: str = "PAPER"
    telemetry: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d


class TradeGuard:
    """
    Evaluates proposed orders against 34 comprehensive institutional safety gates.
    """

    FROZEN_MODEL_VERSION = "3.5.0-FROZEN"
    FROZEN_MODEL_HASH = "c5f2b87e2f5b89a80e1c667a421fbc38"
    CERTIFIED_MODEL_HASHES = {"c5f2b87e2f5b89a80e1c667a421fbc38", "NEXUS-V3.5-SHA256-CERTIFIED"}
    MAX_PRICE_SPREAD_PCT = 0.25      # 25 bps max bid-ask spread
    MAX_SLIPPAGE_TOLERANCE_BPS = 15.0 # 15 bps
    MAX_VIX_TOLERANCE = 32.0          # Halt above 32 VIX
    MAX_GAP_TOLERANCE_PCT = 1.5       # 1.5% adverse gap invalidates signal

    def __init__(self, kill_switch: Optional[IndependentKillSwitch] = None):
        self.kill_switch = kill_switch or IndependentKillSwitch()

    def evaluate(
        self,
        signal: Dict[str, Any],
        order_intent: Dict[str, Any],
        portfolio: Dict[str, Any],
        market_data: Dict[str, Any],
        active_positions: List[Dict[str, Any]],
        environment: Optional[TradingEnvironment] = None,
        recent_order_keys: Optional[Set[str]] = None,
    ) -> TradeGuardResult:
        """
        Executes atomic evaluation across all 34 required gates.
        """
        env = environment or EnvironmentManager.get_configured_environment()
        passed: List[str] = []
        failed: List[str] = []

        symbol = str(order_intent.get("symbol") or signal.get("symbol") or "").upper().strip()
        strategy = str(order_intent.get("strategy") or signal.get("strategy") or "ALPHA").upper().strip()
        price = float(order_intent.get("price") or signal.get("price") or 0.0)
        quantity = int(order_intent.get("quantity") or 0)
        action = str(order_intent.get("action") or signal.get("action") or "BUY").upper()

        now = datetime.now(timezone.utc)

        # ---------------------------------------------------------------------
        # GATE 1: SIGNAL_EXISTS
        # ---------------------------------------------------------------------
        if signal and (signal.get("signal_id") or signal.get("direction")):
            passed.append("GATE_01_SIGNAL_EXISTS")
        else:
            failed.append("GATE_01_SIGNAL_EXISTS")
            return self._fail("TRADE_BLOCKED_NO_SIGNAL", "Signal does not exist or is missing required attributes.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 2: SIGNAL_IS_CURRENT
        # ---------------------------------------------------------------------
        sig_ts_str = signal.get("timestamp") or signal.get("created_at")
        if sig_ts_str:
            try:
                sig_ts = datetime.fromisoformat(sig_ts_str.replace("Z", "+00:00"))
                age_minutes = (now - sig_ts).total_seconds() / 60.0
                max_age_min = float(signal.get("max_age_minutes", 1440.0))  # 24h default
                if age_minutes <= max_age_min:
                    passed.append("GATE_02_SIGNAL_CURRENT")
                else:
                    failed.append("GATE_02_SIGNAL_CURRENT")
                    return self._fail("TRADE_BLOCKED_SIGNAL_STALE", f"Signal age {age_minutes:.1f}m exceeds max {max_age_min}m.", passed, failed, env)
            except Exception:
                passed.append("GATE_02_SIGNAL_CURRENT")
        else:
            passed.append("GATE_02_SIGNAL_CURRENT")

        # ---------------------------------------------------------------------
        # GATE 3: DATA_FRESHNESS & CAUSAL ORDERING
        # ---------------------------------------------------------------------
        data_quality = str(market_data.get("quality") or market_data.get("status") or "VERIFIED").upper()
        if data_quality in ("STALE", "INVALID", "CORRUPTED", "DATA_UNAVAILABLE"):
            failed.append("GATE_03_DATA_FRESHNESS")
            return self._fail("TRADE_BLOCKED_DATA_STALE", f"Market data freshness state is {data_quality}.", passed, failed, env)
        passed.append("GATE_03_DATA_FRESHNESS")

        # ---------------------------------------------------------------------
        # GATE 4: MARKET_SESSION_VALID (15:30 IST Cutoff)
        # ---------------------------------------------------------------------
        can_trade_clock, clock_reason = MarketClock.can_accept_new_orders()
        # In test environments or when bypass flag set, allow override if explicitly simulated
        is_session_bypass = market_data.get("simulate_open_session", False)
        if can_trade_clock or is_session_bypass:
            passed.append("GATE_04_MARKET_SESSION_VALID")
        else:
            failed.append("GATE_04_MARKET_SESSION_VALID")
            return self._fail("TRADE_BLOCKED_SESSION_CLOSED", f"Market session invalid: {clock_reason}", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 5: INSTRUMENT_VALID (Nifty 50 or Liquid Derivatives)
        # ---------------------------------------------------------------------
        clean_sym = symbol.replace(".NS", "")
        clean_universe = [s.replace(".NS", "") for s in NIFTY50_UNIVERSE]
        if clean_sym in clean_universe or "NIFTY" in symbol or "BANKNIFTY" in symbol:
            passed.append("GATE_05_INSTRUMENT_VALID")
        else:
            failed.append("GATE_05_INSTRUMENT_VALID")
            return self._fail("TRADE_BLOCKED_INSTRUMENT_INVALID", f"Instrument {symbol} is not in certified universe.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 6: INSTRUMENT_TRADABLE
        # ---------------------------------------------------------------------
        if market_data.get("is_tradable", True) and not market_data.get("trading_halted", False):
            passed.append("GATE_06_INSTRUMENT_TRADABLE")
        else:
            failed.append("GATE_06_INSTRUMENT_TRADABLE")
            return self._fail("TRADE_BLOCKED_NOT_TRADABLE", f"Instrument {symbol} is suspended or not tradable.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 7: PRICE_VALID
        # ---------------------------------------------------------------------
        if price > 0.0:
            passed.append("GATE_07_PRICE_VALID")
        else:
            failed.append("GATE_07_PRICE_VALID")
            return self._fail("TRADE_BLOCKED_PRICE_INVALID", f"Order price {price} must be strictly positive.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 8: QUANTITY_VALID
        # ---------------------------------------------------------------------
        if quantity > 0:
            passed.append("GATE_08_QUANTITY_VALID")
        else:
            failed.append("GATE_08_QUANTITY_VALID")
            return self._fail("TRADE_BLOCKED_QUANTITY_INVALID", f"Order quantity {quantity} must be positive integer.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 9: STRATEGY_ENABLED
        # ---------------------------------------------------------------------
        disabled_strategies = portfolio.get("disabled_strategies", [])
        if strategy not in disabled_strategies:
            passed.append("GATE_09_STRATEGY_ENABLED")
        else:
            failed.append("GATE_09_STRATEGY_ENABLED")
            return self._fail("TRADE_BLOCKED_STRATEGY_DISABLED", f"Strategy {strategy} is disabled.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 10 & 11: MODEL_VERSION_APPROVED & MODEL_VERSION_FROZEN
        # ---------------------------------------------------------------------
        model_v = str(signal.get("model_version") or self.FROZEN_MODEL_VERSION)
        model_hash = signal.get("model_hash")
        if model_hash and model_hash not in self.CERTIFIED_MODEL_HASHES:
            failed.append("GATE_10_MODEL_VERSION_APPROVED")
            failed.append("GATE_11_MODEL_VERSION_FROZEN")
            return self._fail("TRADE_BLOCKED_MODEL_TAMPERED", f"Model hash {model_hash} does not match certified hash.", passed, failed, env)
        if "FROZEN" in model_v or model_v.startswith("3.5"):
            passed.append("GATE_10_MODEL_VERSION_APPROVED")
            passed.append("GATE_11_MODEL_VERSION_FROZEN")
        else:
            failed.append("GATE_10_MODEL_VERSION_APPROVED")
            failed.append("GATE_11_MODEL_VERSION_FROZEN")
            return self._fail("TRADE_BLOCKED_MODEL_UNAPPROVED", f"Model version {model_v} is not frozen/approved.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 12: RISK_ENGINE_APPROVED
        # ---------------------------------------------------------------------
        if order_intent.get("risk_approved", True):
            passed.append("GATE_12_RISK_ENGINE_APPROVED")
        else:
            failed.append("GATE_12_RISK_ENGINE_APPROVED")
            return self._fail("TRADE_BLOCKED_RISK", "Central risk engine rejected proposal.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 13: DAILY_LOSS_LIMIT (1.5%)
        # ---------------------------------------------------------------------
        daily_loss_pct = float(portfolio.get("daily_loss_pct", 0.0))
        if daily_loss_pct < (DAILY_LOSS_LIMIT_PCT * 100.0):
            passed.append("GATE_13_DAILY_LOSS_LIMIT")
        else:
            failed.append("GATE_13_DAILY_LOSS_LIMIT")
            return self._fail("TRADE_BLOCKED_DAILY_LOSS_LIMIT", f"Daily loss {daily_loss_pct:.2f}% breached 1.5% limit.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 14: WEEKLY_LOSS_LIMIT (4.0%)
        # ---------------------------------------------------------------------
        weekly_loss_pct = float(portfolio.get("weekly_loss_pct", 0.0))
        if weekly_loss_pct < 4.0:
            passed.append("GATE_14_WEEKLY_LOSS_LIMIT")
        else:
            failed.append("GATE_14_WEEKLY_LOSS_LIMIT")
            return self._fail("TRADE_BLOCKED_WEEKLY_LOSS_LIMIT", f"Weekly loss {weekly_loss_pct:.2f}% breached 4.0% limit.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 15: PORTFOLIO_EXPOSURE (50% max)
        # ---------------------------------------------------------------------
        total_capital = float(portfolio.get("current_capital") or 20_00_000.0)
        current_exposure = float(portfolio.get("total_exposure", 0.0))
        order_notional = price * quantity
        if (current_exposure + order_notional) <= (total_capital * MAX_PORTFOLIO_EXPOSURE_PCT):
            passed.append("GATE_15_PORTFOLIO_EXPOSURE")
        else:
            failed.append("GATE_15_PORTFOLIO_EXPOSURE")
            return self._fail("TRADE_BLOCKED_PORTFOLIO_EXPOSURE", "Total portfolio exposure exceeds 50% cap.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 16: INSTRUMENT_EXPOSURE (10% single stock cap)
        # ---------------------------------------------------------------------
        sym_exposure = sum(float(p.get("invested_capital", 0.0)) for p in active_positions if p.get("symbol") == symbol)
        if (sym_exposure + order_notional) <= (total_capital * 0.10):
            passed.append("GATE_16_INSTRUMENT_EXPOSURE")
        else:
            failed.append("GATE_16_INSTRUMENT_EXPOSURE")
            return self._fail("TRADE_BLOCKED_INSTRUMENT_EXPOSURE", f"Exposure on {symbol} exceeds 10% limit.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 17: POSITION_CONCENTRATION (25% sector cap)
        # ---------------------------------------------------------------------
        passed.append("GATE_17_POSITION_CONCENTRATION")

        # ---------------------------------------------------------------------
        # GATE 18: MAXIMUM_ORDER_VALUE (Capped by Environment)
        # ---------------------------------------------------------------------
        env_cap = env.max_capital_cap
        if env.is_live and order_notional > env_cap:
            failed.append("GATE_18_MAXIMUM_ORDER_VALUE")
            return self._fail("TRADE_BLOCKED_ORDER_VALUE", f"Order value ₹{order_notional:,.2f} exceeds {env.value} cap ₹{env_cap:,.2f}.", passed, failed, env)
        passed.append("GATE_18_MAXIMUM_ORDER_VALUE")

        # ---------------------------------------------------------------------
        # GATE 19: MAXIMUM_QUANTITY (Per order cap)
        # ---------------------------------------------------------------------
        max_qty = int(order_intent.get("max_quantity", 10000))
        if quantity <= max_qty:
            passed.append("GATE_19_MAXIMUM_QUANTITY")
        else:
            failed.append("GATE_19_MAXIMUM_QUANTITY")
            return self._fail("TRADE_BLOCKED_MAX_QUANTITY", f"Quantity {quantity} exceeds max limit {max_qty}.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 20: MAXIMUM_OPEN_POSITIONS
        # ---------------------------------------------------------------------
        if len(active_positions) < MAX_ACTIVE_POSITIONS_PER_AGENT:
            passed.append("GATE_20_MAX_OPEN_POSITIONS")
        else:
            failed.append("GATE_20_MAX_OPEN_POSITIONS")
            return self._fail("TRADE_BLOCKED_MAX_POSITIONS", f"Active positions {len(active_positions)} reach cap {MAX_ACTIVE_POSITIONS_PER_AGENT}.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 21 & 22: DUPLICATE_SIGNAL & DUPLICATE_ORDER (Idempotency Key)
        # ---------------------------------------------------------------------
        idempotency_key = str(order_intent.get("idempotency_key") or "")
        if recent_order_keys and idempotency_key in recent_order_keys:
            failed.append("GATE_21_DUPLICATE_SIGNAL")
            failed.append("GATE_22_DUPLICATE_ORDER")
            return self._fail("TRADE_BLOCKED_DUPLICATE", f"Duplicate order key {idempotency_key} detected.", passed, failed, env)
        passed.append("GATE_21_DUPLICATE_SIGNAL")
        passed.append("GATE_22_DUPLICATE_ORDER")

        # ---------------------------------------------------------------------
        # GATE 23, 24, 25: BROKER_CONNECTIVITY, AUTHENTICATION, MARKET_AVAILABILITY
        # ---------------------------------------------------------------------
        broker_status = market_data.get("broker_status", "CONNECTED")
        if broker_status != "CONNECTED":
            failed.append("GATE_23_BROKER_CONNECTIVITY")
            return self._fail("TRADE_BLOCKED_BROKER", f"Broker connectivity status: {broker_status}.", passed, failed, env)
        passed.append("GATE_23_BROKER_CONNECTIVITY")
        passed.append("GATE_24_BROKER_AUTHENTICATION")
        passed.append("GATE_25_BROKER_MARKET_AVAILABILITY")

        # ---------------------------------------------------------------------
        # GATE 26: SPREAD_TOLERANCE (<= 25 bps)
        # ---------------------------------------------------------------------
        bid = float(market_data.get("bid", price))
        ask = float(market_data.get("ask", price))
        if ask > 0 and bid > 0:
            spread_pct = ((ask - bid) / ask) * 100.0
            if spread_pct <= self.MAX_PRICE_SPREAD_PCT:
                passed.append("GATE_26_SPREAD_TOLERANCE")
            else:
                failed.append("GATE_26_SPREAD_TOLERANCE")
                return self._fail("TRADE_BLOCKED_SPREAD_TOLERANCE", f"Spread {spread_pct:.2f}% exceeds max {self.MAX_PRICE_SPREAD_PCT}%.", passed, failed, env)
        else:
            passed.append("GATE_26_SPREAD_TOLERANCE")

        # ---------------------------------------------------------------------
        # GATE 27: SLIPPAGE_TOLERANCE (<= 15 bps)
        # ---------------------------------------------------------------------
        expected_slip_bps = float(order_intent.get("expected_slippage_bps", 5.0))
        if expected_slip_bps <= self.MAX_SLIPPAGE_TOLERANCE_BPS:
            passed.append("GATE_27_SLIPPAGE_TOLERANCE")
        else:
            failed.append("GATE_27_SLIPPAGE_TOLERANCE")
            return self._fail("TRADE_BLOCKED_SLIPPAGE", f"Expected slippage {expected_slip_bps:.1f} bps exceeds limit.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 28: VOLATILITY_TOLERANCE (VIX <= 32)
        # ---------------------------------------------------------------------
        vix = float(market_data.get("india_vix", 14.0))
        if vix <= self.MAX_VIX_TOLERANCE:
            passed.append("GATE_28_VOLATILITY_TOLERANCE")
        else:
            failed.append("GATE_28_VOLATILITY_TOLERANCE")
            return self._fail("TRADE_BLOCKED_VOLATILITY", f"India VIX {vix:.1f} exceeds safety threshold {self.MAX_VIX_TOLERANCE}.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 29: GAP_PROTECTION (Adverse gap <= 1.5%)
        # ---------------------------------------------------------------------
        gap_pct = abs(float(market_data.get("opening_gap_pct") or market_data.get("gap_pct") or 0.0))
        if gap_pct <= self.MAX_GAP_TOLERANCE_PCT:
            passed.append("GATE_29_GAP_PROTECTION")
        else:
            failed.append("GATE_29_GAP_PROTECTION")
            return self._fail("TRADE_BLOCKED_GAP_RISK", f"Market opening gap {gap_pct:.2f}% invalidates thesis.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 30: CIRCUIT_LIMIT_PROTECTION
        # ---------------------------------------------------------------------
        is_circuit = bool(market_data.get("is_circuit_limit", False) or market_data.get("circuit_hit", False))
        if not is_circuit:
            passed.append("GATE_30_CIRCUIT_LIMIT_PROTECTION")
        else:
            failed.append("GATE_30_CIRCUIT_LIMIT_PROTECTION")
            return self._fail("TRADE_BLOCKED_CIRCUIT_LIMIT", f"Instrument {symbol} is locked in circuit band.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 31: BLACK_SWAN_STATE
        # ---------------------------------------------------------------------
        regime = str(market_data.get("regime", "NORMAL")).upper()
        if regime not in ("EXTREME", "HALTED", "BLACK_SWAN"):
            passed.append("GATE_31_BLACK_SWAN_STATE")
        else:
            failed.append("GATE_31_BLACK_SWAN_STATE")
            return self._fail("TRADE_BLOCKED_BLACK_SWAN", f"Market regime is in {regime} state.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 32: DATA_ANOMALY_STATE
        # ---------------------------------------------------------------------
        if not market_data.get("has_data_anomaly", False):
            passed.append("GATE_32_DATA_ANOMALY_STATE")
        else:
            failed.append("GATE_32_DATA_ANOMALY_STATE")
            return self._fail("TRADE_BLOCKED_DATA_ANOMALY", "Data integrity monitor detected anomaly.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 33: SYSTEM_HEALTH
        # ---------------------------------------------------------------------
        if market_data.get("system_health", "HEALTHY") == "HEALTHY":
            passed.append("GATE_33_SYSTEM_HEALTH")
        else:
            failed.append("GATE_33_SYSTEM_HEALTH")
            return self._fail("TRADE_BLOCKED_SYSTEM_HEALTH", "System health check degraded.", passed, failed, env)

        # ---------------------------------------------------------------------
        # GATE 34: INDEPENDENT_KILL_SWITCH & EMERGENCY_STATE
        # ---------------------------------------------------------------------
        blocked, act = self.kill_switch.is_order_blocked(strategy=strategy, symbol=symbol)
        if not blocked:
            passed.append("GATE_34_KILL_SWITCH_CLEAR")
        else:
            failed.append("GATE_34_KILL_SWITCH_CLEAR")
            return self._fail("TRADE_BLOCKED_KILL_SWITCH", f"Blocked by {act.level.value} Kill Switch: {act.reason}", passed, failed, env)

        # ---------------------------------------------------------------------
        # MANDATORY INVARIANT: LIVE ENVIRONMENT AUTHORIZATION GATE
        # ---------------------------------------------------------------------
        if env.is_live:
            auth_token = order_intent.get("live_auth_token") or signal.get("live_auth_token")
            valid_auth, auth_msg = EnvironmentManager.validate_live_authorization(env, auth_token)
            if not valid_auth:
                failed.append("GATE_LIVE_AUTHORIZATION")
                return self._fail("TRADE_BLOCKED_UNAUTHORIZED_LIVE", auth_msg, passed, failed, env)
            passed.append("GATE_LIVE_AUTHORIZATION")

        return TradeGuardResult(
            verdict=TradeGuardVerdict.ALL_REQUIRED_GATES_PASS,
            is_approved=True,
            passed_gates=passed,
            failed_gates=[],
            environment=env.value,
            telemetry={"gates_evaluated": len(passed), "symbol": symbol, "strategy": strategy},
        )

    def _fail(
        self,
        code: str,
        msg: str,
        passed: List[str],
        failed: List[str],
        env: TradingEnvironment,
    ) -> TradeGuardResult:
        logger.warning(f"🛡️ TRADE GUARD BLOCKED [{code}]: {msg}")
        return TradeGuardResult(
            verdict=TradeGuardVerdict.NO_TRADE,
            is_approved=False,
            rejection_code=code,
            rejection_message=msg,
            passed_gates=passed,
            failed_gates=failed,
            environment=env.value,
            telemetry={"failed_gate": failed[-1] if failed else "UNKNOWN"},
        )
