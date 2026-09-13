# =============================================================================
# event_agent/risk/market_anomaly_guard.py — Gap & Black-Swan Protection
# =============================================================================
"""
NEXUS V4.0 Gap Protection & Extreme Market / Black-Swan Detector:
- Section 11: Compares expected_open vs actual_open. If adverse gap exceeds threshold,
  aborts trade and records GAP_INVALIDATED_SIGNAL.
- Section 12: 5-State Abnormal Market Detector (NORMAL, ELEVATED, HIGH_RISK, EXTREME, HALTED).
  EXTREME and HALTED immediately prevent new automated positions.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .kill_switch import EmergencyPolicy, IndependentKillSwitch, KillSwitchLevel, KillSwitchTrigger

logger = logging.getLogger(__name__)


class MarketRegimeState(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH_RISK = "HIGH_RISK"
    EXTREME = "EXTREME"
    HALTED = "HALTED"


@dataclass
class GapProtectionEvaluation:
    symbol: str
    direction: str  # BUY | SELL
    expected_open: float
    actual_open: float
    gap_pct: float
    is_adverse: bool
    is_invalidated: bool
    status: str  # VALIDATED | GAP_INVALIDATED_SIGNAL
    reason: str
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MarketRegimeEvaluation:
    state: MarketRegimeState
    india_vix: float
    index_change_pct: float
    spread_bps: float
    is_circuit_active: bool
    data_anomaly_detected: bool
    allows_new_orders: bool
    risk_multiplier: float
    explanation: str
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


class MarketAnomalyGuard:
    """
    Evaluates pre-trade market opening conditions and systemic volatility.
    """

    DEFAULT_MAX_GAP_PCT = 1.50   # 1.5% adverse gap threshold

    def __init__(self, kill_switch: Optional[IndependentKillSwitch] = None):
        self.kill_switch = kill_switch or IndependentKillSwitch()

    def evaluate_gap(
        self,
        symbol: str,
        direction: str,
        expected_open: float,
        actual_open: float,
        threshold_pct: float = DEFAULT_MAX_GAP_PCT,
    ) -> GapProtectionEvaluation:
        """
        Verifies whether actual market open invalidates the overnight prediction thesis.
        If a BUY forecast gaps DOWN severely, or a SELL forecast gaps UP severely,
        the thesis is invalidated and trade is aborted.
        """
        if expected_open <= 0 or actual_open <= 0:
            return GapProtectionEvaluation(
                symbol=symbol,
                direction=direction,
                expected_open=expected_open,
                actual_open=actual_open,
                gap_pct=0.0,
                is_adverse=False,
                is_invalidated=False,
                status="VALIDATED",
                reason="Gap evaluation skipped (zero reference price).",
            )

        gap_pct = ((actual_open - expected_open) / expected_open) * 100.0
        is_buy = direction.upper() in ("BUY", "LONG")

        # Adverse gap: For BUY, opening significantly lower than expected indicates negative shock
        # For SELL, opening significantly higher indicates positive squeeze
        is_adverse = (is_buy and gap_pct < -threshold_pct) or (not is_buy and gap_pct > threshold_pct)

        if is_adverse:
            msg = (
                f"GAP_INVALIDATED_SIGNAL: {symbol} actual open ₹{actual_open:.2f} gapped {gap_pct:+.2f}% "
                f"against {direction} thesis (exceeds {threshold_pct:.2f}% threshold). Trade aborted."
            )
            logger.warning(f"⚠️ {msg}")
            return GapProtectionEvaluation(
                symbol=symbol,
                direction=direction,
                expected_open=expected_open,
                actual_open=actual_open,
                gap_pct=round(gap_pct, 2),
                is_adverse=True,
                is_invalidated=True,
                status="GAP_INVALIDATED_SIGNAL",
                reason=msg,
            )

        return GapProtectionEvaluation(
            symbol=symbol,
            direction=direction,
            expected_open=expected_open,
            actual_open=actual_open,
            gap_pct=round(gap_pct, 2),
            is_adverse=False,
            is_invalidated=False,
            status="VALIDATED",
            reason=f"Opening gap {gap_pct:+.2f}% within allowable tolerance ({threshold_pct:.2f}%).",
        )

    def evaluate_regime(
        self,
        india_vix: float = 13.5,
        index_change_pct: float = 0.0,
        spread_bps: float = 5.0,
        is_circuit_active: bool = False,
        data_anomaly_detected: bool = False,
        auto_kill_on_extreme: bool = True,
    ) -> MarketRegimeEvaluation:
        """
        Classifies current market conditions into 5 distinct operational regimes:
        NORMAL, ELEVATED, HIGH_RISK, EXTREME, HALTED.
        """
        abs_index_chg = abs(index_change_pct)

        if is_circuit_active:
            state = MarketRegimeState.HALTED
            explanation = "Market circuit breaker active or index locked in limit band."
        elif india_vix >= 35.0 or abs_index_chg >= 4.0 or (spread_bps > 50.0 and abs_index_chg > 2.5):
            state = MarketRegimeState.EXTREME
            explanation = f"Extreme black-swan market volatility (VIX={india_vix:.1f}, Index Chg={index_change_pct:+.2f}%)."
        elif india_vix >= 24.0 or abs_index_chg >= 2.0 or spread_bps > 30.0:
            state = MarketRegimeState.HIGH_RISK
            explanation = f"Elevated systemic risk (VIX={india_vix:.1f}, Index Chg={index_change_pct:+.2f}%)."
        elif india_vix >= 18.0 or abs_index_chg >= 1.2 or spread_bps > 15.0:
            state = MarketRegimeState.ELEVATED
            explanation = f"Moderate volatility (VIX={india_vix:.1f})."
        else:
            state = MarketRegimeState.NORMAL
            explanation = "Normal baseline market conditions."

        if data_anomaly_detected:
            state = MarketRegimeState.HIGH_RISK
            explanation += " [Data anomaly detected by feed validator]"

        allows_new = state not in (MarketRegimeState.EXTREME, MarketRegimeState.HALTED)
        risk_multiplier = 1.0
        if state == MarketRegimeState.ELEVATED:
            risk_multiplier = 0.75
        elif state == MarketRegimeState.HIGH_RISK:
            risk_multiplier = 0.50
        elif not allows_new:
            risk_multiplier = 0.0

        if not allows_new and auto_kill_on_extreme:
            self.kill_switch.activate(
                level=KillSwitchLevel.GLOBAL,
                trigger=KillSwitchTrigger.ABNORMAL_VOLATILITY,
                target="ALL",
                policy=EmergencyPolicy.STOP_NEW_ORDERS,
                reason=f"Extreme black-swan regime detected: {explanation}",
                activated_by="MarketAnomalyGuard",
                telemetry={"vix": india_vix, "index_chg": index_change_pct, "regime": state.value},
            )

        return MarketRegimeEvaluation(
            state=state,
            india_vix=india_vix,
            index_change_pct=index_change_pct,
            spread_bps=spread_bps,
            is_circuit_active=is_circuit_active,
            data_anomaly_detected=data_anomaly_detected,
            allows_new_orders=allows_new,
            risk_multiplier=risk_multiplier,
            explanation=explanation,
        )
