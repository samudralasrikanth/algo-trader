# =============================================================================
# event_agent/arena/greeks_engine.py — Portfolio Greeks & Risk Limits Engine
# =============================================================================
"""
Portfolio Greeks Engine for V4.2 Institutional Derivatives Risk Management:
- Tracks both Raw Greeks and Normalized Portfolio Metrics
- Net Delta limit: Normalized Net Delta must remain within [-0.30, +0.30]
- Theta Decay limit: Daily theta cost capped at <= 0.5% of total portfolio value
- Margin Utilization: Margin used must remain < 60% of total capital
- Aggregates Delta, Gamma, Theta, Vega across all multi-leg & single-leg positions
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class PortfolioGreeks:
    raw_delta: float = 0.0
    normalized_delta: float = 0.0
    total_gamma: float = 0.0
    daily_theta: float = 0.0
    daily_theta_pct: float = 0.0
    total_vega: float = 0.0
    margin_used: float = 0.0
    margin_utilization_pct: float = 0.0
    is_delta_compliant: bool = True
    is_theta_compliant: bool = True
    is_margin_compliant: bool = True
    breaches: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_delta": round(self.raw_delta, 2),
            "normalized_delta": round(self.normalized_delta, 4),
            "total_gamma": round(self.total_gamma, 6),
            "daily_theta": round(self.daily_theta, 2),
            "daily_theta_pct": round(self.daily_theta_pct, 3),
            "total_vega": round(self.total_vega, 2),
            "margin_used": round(self.margin_used, 2),
            "margin_utilization_pct": round(self.margin_utilization_pct, 2),
            "is_delta_compliant": self.is_delta_compliant,
            "is_theta_compliant": self.is_theta_compliant,
            "is_margin_compliant": self.is_margin_compliant,
            "breaches": self.breaches,
        }


class PortfolioGreeksEngine:
    """
    Computes and audits aggregated portfolio Greeks and margin boundaries.
    """

    MAX_NORMALIZED_DELTA: float = 0.30      # [-0.30, +0.30]
    MAX_DAILY_THETA_PCT: float = 0.50       # Max 0.5% portfolio decay / day
    MAX_MARGIN_UTILIZATION_PCT: float = 60.0  # Max 60% margin utilization

    @classmethod
    def calculate_portfolio_greeks(
        cls,
        open_positions: List[Dict[str, Any]],
        portfolio_equity: float,
        proposed_trade: Optional[Dict[str, Any]] = None,
    ) -> PortfolioGreeks:
        """
        Aggregates Greeks across existing positions plus optional proposed trade.
        """
        equity = max(1000.0, portfolio_equity)
        raw_delta = 0.0
        total_gamma = 0.0
        daily_theta = 0.0
        total_vega = 0.0
        margin_used = 0.0

        all_items = list(open_positions)
        if proposed_trade:
            all_items.append(proposed_trade)

        for pos in all_items:
            qty = float(pos.get("quantity", 0))
            price = float(pos.get("current_price", pos.get("entry_price", 0.0)))
            inst_type = str(pos.get("instrument_type", pos.get("instrument", {}).get("instrument_type", "EQUITY"))).upper()
            pos_side = str(pos.get("position_side", "LONG")).upper()
            sign = 1.0 if pos_side == "LONG" else -1.0

            if "EQUITY" in inst_type:
                # Delta of 1.0 per share * price
                pos_delta = sign * qty * price
                raw_delta += pos_delta
                # Cash margin
                margin_used += qty * price
            elif "FUTURE" in inst_type:
                pos_delta = sign * qty * price
                raw_delta += pos_delta
                # Futures margin ~20% of contract value
                margin_used += qty * price * 0.20
            elif "OPTION" in inst_type:
                # Option delta
                delta_val = float(pos.get("delta", 0.40))
                gamma_val = float(pos.get("gamma", 0.0))
                theta_val = float(pos.get("theta", -15.0))
                vega_val = float(pos.get("vega", 10.0))

                raw_delta += sign * delta_val * qty * price
                total_gamma += gamma_val * qty
                daily_theta += theta_val * qty
                total_vega += vega_val * qty

                # Option premium paid or margin required
                premium = float(pos.get("entry_price", price))
                margin_used += qty * premium

        norm_delta = raw_delta / equity
        theta_pct = (abs(daily_theta) / equity) * 100.0
        margin_pct = (margin_used / equity) * 100.0

        breaches = []
        is_delta_ok = abs(norm_delta) <= cls.MAX_NORMALIZED_DELTA
        if not is_delta_ok:
            breaches.append(f"Normalized Delta {norm_delta:+.3f} exceeds threshold +/-{cls.MAX_NORMALIZED_DELTA:.2f}")

        is_theta_ok = theta_pct <= cls.MAX_DAILY_THETA_PCT
        if not is_theta_ok:
            breaches.append(f"Daily Theta decay {theta_pct:.2f}% exceeds ceiling {cls.MAX_DAILY_THETA_PCT:.2f}%")

        is_margin_ok = margin_pct <= cls.MAX_MARGIN_UTILIZATION_PCT
        if not is_margin_ok:
            breaches.append(f"Margin utilization {margin_pct:.1f}% exceeds limit {cls.MAX_MARGIN_UTILIZATION_PCT:.0f}%")

        return PortfolioGreeks(
            raw_delta=raw_delta,
            normalized_delta=norm_delta,
            total_gamma=total_gamma,
            daily_theta=daily_theta,
            daily_theta_pct=theta_pct,
            total_vega=total_vega,
            margin_used=margin_used,
            margin_utilization_pct=margin_pct,
            is_delta_compliant=is_delta_ok,
            is_theta_compliant=is_theta_ok,
            is_margin_compliant=is_margin_ok,
            breaches=breaches,
        )
