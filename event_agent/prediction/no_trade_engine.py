# =============================================================================
# event_agent/prediction/no_trade_engine.py — First-Class NO_TRADE & Edge Engine
# =============================================================================
"""
V3.5 First-Class NO_TRADE & Expected Net Edge Engine.
Calculates Expected Value after slippage and statutory transaction costs:
    Expected Gross Return - Expected Slippage - Transaction Costs = Expected Net Return
    Expected Net Return / Expected Risk = Expected Risk-Adjusted Edge
Enforces 11 strict abstention gates to prevent negative-EV trades.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ExpectedValueCalculation:
    gross_return_pct: float
    expected_slippage_pct: float
    transaction_cost_pct: float
    net_return_pct: float
    expected_risk_pct: float
    risk_adjusted_edge: float          # net_return / expected_risk
    is_positive_edge: bool


@dataclass
class NoTradeDecision:
    is_no_trade: bool
    reason_code: Optional[str]         # One of the 11 codes or None
    detailed_reason: str
    expected_value: ExpectedValueCalculation
    passed_gates: List[str]
    failed_gate: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_no_trade": self.is_no_trade,
            "reason_code": self.reason_code,
            "detailed_reason": self.detailed_reason,
            "passed_gates_count": len(self.passed_gates),
            "failed_gate": self.failed_gate,
            "net_edge_pct": round(self.expected_value.net_return_pct, 3),
            "risk_adjusted_edge": round(self.expected_value.risk_adjusted_edge, 3),
        }


class NoTradeEngine:
    """
    Evaluates proposed trades against 11 quantitative gate criteria and net edge thresholds.
    """

    REASONS = [
        "INSUFFICIENT_DATA",
        "STALE_DATA",
        "CONFLICTING_AGENTS",
        "LOW_EXPECTED_EDGE",
        "EXCESSIVE_VOLATILITY",
        "POOR_LIQUIDITY",
        "EXCESSIVE_TRANSACTION_COSTS",
        "WEAK_HISTORICAL_ANALOGUE",
        "INSUFFICIENT_CONFIDENCE",
        "RISK_LIMITS_EXCEEDED",
        "MARKET_UNCERTAINTY",
    ]

    # Minimal edge hurdle: Net edge must exceed 0.25% after costs
    MIN_NET_EDGE_PCT = 0.25
    MIN_CONFIDENCE_THRESHOLD = 54.0

    @classmethod
    def calculate_expected_value(
        cls,
        expected_gross_pct: float,
        daily_volatility: float,
        slippage_pct: float = 0.10,    # 10 bps default slippage
        transaction_cost_pct: float = 0.08, # Brokerage, STT, turnover charges ~8 bps
    ) -> ExpectedValueCalculation:
        """
        Gross Return - Slippage - Transaction Costs = Net Return
        """
        net_pct = expected_gross_pct - slippage_pct - transaction_cost_pct
        risk_pct = max(0.5, daily_volatility * 100.0 * 1.5)
        edge = (net_pct / risk_pct) if risk_pct > 0 else 0.0

        return ExpectedValueCalculation(
            gross_return_pct=round(expected_gross_pct, 4),
            expected_slippage_pct=round(slippage_pct, 4),
            transaction_cost_pct=round(transaction_cost_pct, 4),
            net_return_pct=round(net_pct, 4),
            expected_risk_pct=round(risk_pct, 4),
            risk_adjusted_edge=round(edge, 4),
            is_positive_edge=(net_pct >= cls.MIN_NET_EDGE_PCT),
        )

    @classmethod
    def evaluate(
        cls,
        symbol: str,
        expected_gross_pct: float,
        confidence: float,
        daily_volatility: float,
        data_available: bool = True,
        data_age_hours: float = 0.5,
        agent_agreement_pct: float = 65.0, # % of agents agreeing on direction
        analogue_count: int = 25,
        vix_regime: str = "NORMAL",
        spread_bps: float = 4.0,
        risk_engine_blocked: bool = False,
        regime_uncertainty_score: float = 0.35,
    ) -> NoTradeDecision:
        """
        Evaluate all 11 NO_TRADE rejection conditions.
        """
        ev = cls.calculate_expected_value(
            expected_gross_pct=expected_gross_pct,
            daily_volatility=daily_volatility,
        )

        passed = []

        # Gate 1: Insufficient Data
        if not data_available:
            return NoTradeDecision(True, "INSUFFICIENT_DATA", f"Missing price or event inputs for {symbol}.", ev, passed, "INSUFFICIENT_DATA")
        passed.append("DATA_AVAILABLE")

        # Gate 2: Stale Data
        if data_age_hours > 24.0:
            return NoTradeDecision(True, "STALE_DATA", f"Data feed is {data_age_hours:.1f}h old (stale threshold: 24h).", ev, passed, "STALE_DATA")
        passed.append("FRESH_DATA")

        # Gate 3: Conflicting Agents
        if agent_agreement_pct < 50.0:
            return NoTradeDecision(True, "CONFLICTING_AGENTS", f"Agent consensus split ({agent_agreement_pct:.1f}% agreement).", ev, passed, "CONFLICTING_AGENTS")
        passed.append("AGENT_CONSENSUS")

        # Gate 4: Insufficient Confidence
        if confidence < cls.MIN_CONFIDENCE_THRESHOLD:
            return NoTradeDecision(True, "INSUFFICIENT_CONFIDENCE", f"Calibrated confidence {confidence:.1f}% below minimum {cls.MIN_CONFIDENCE_THRESHOLD}%.", ev, passed, "INSUFFICIENT_CONFIDENCE")
        passed.append("CONFIDENCE_ADEQUATE")

        # Gate 5: Low Expected Edge
        if not ev.is_positive_edge:
            return NoTradeDecision(True, "LOW_EXPECTED_EDGE", f"Net expected return ({ev.net_return_pct:.2f}%) below minimum edge hurdle {cls.MIN_NET_EDGE_PCT}%.", ev, passed, "LOW_EXPECTED_EDGE")
        passed.append("POSITIVE_EDGE")

        # Gate 6: Excessive Volatility
        if vix_regime == "EXTREME" or daily_volatility > 0.045:
            return NoTradeDecision(True, "EXCESSIVE_VOLATILITY", f"Volatility extreme (VIX regime: {vix_regime}, sigma={daily_volatility*100:.1f}%).", ev, passed, "EXCESSIVE_VOLATILITY")
        passed.append("VOLATILITY_SAFE")

        # Gate 7: Poor Liquidity
        if spread_bps > 25.0:
            return NoTradeDecision(True, "POOR_LIQUIDITY", f"Bid-ask spread ({spread_bps:.1f} bps) exceeds liquid threshold (25 bps).", ev, passed, "POOR_LIQUIDITY")
        passed.append("LIQUIDITY_SAFE")

        # Gate 8: Excessive Transaction Costs
        if (ev.expected_slippage_pct + ev.transaction_cost_pct) >= expected_gross_pct * 0.75:
            return NoTradeDecision(True, "EXCESSIVE_TRANSACTION_COSTS", "Execution drag consumes >75% of expected gross move.", ev, passed, "EXCESSIVE_TRANSACTION_COSTS")
        passed.append("COSTS_MANAGEABLE")

        # Gate 9: Weak Historical Analogue
        if analogue_count < 5:
            return NoTradeDecision(True, "WEAK_HISTORICAL_ANALOGUE", f"Only {analogue_count} matching historical analogues found (minimum: 5).", ev, passed, "WEAK_HISTORICAL_ANALOGUE")
        passed.append("ANALOGUE_SUFFICIENT")

        # Gate 10: Risk Limits Exceeded
        if risk_engine_blocked:
            return NoTradeDecision(True, "RISK_LIMITS_EXCEEDED", "Central Risk Engine exposure cap or circuit breaker triggered.", ev, passed, "RISK_LIMITS_EXCEEDED")
        passed.append("RISK_LIMITS_CLEARED")

        # Gate 11: Market Uncertainty
        if regime_uncertainty_score > 0.85:
            return NoTradeDecision(True, "MARKET_UNCERTAINTY", f"Macro uncertainty score {regime_uncertainty_score:.2f} indicates unquantifiable tail risk.", ev, passed, "MARKET_UNCERTAINTY")
        passed.append("MARKET_STABLE")

        # All 11 gates passed!
        return NoTradeDecision(
            is_no_trade=False,
            reason_code=None,
            detailed_reason="All 11 quantitative validation gates passed with positive net edge.",
            expected_value=ev,
            passed_gates=passed,
            failed_gate=None,
        )
