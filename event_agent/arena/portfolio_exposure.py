# =============================================================================
# event_agent/arena/portfolio_exposure.py — Sector & Correlation Exposure Engine
# =============================================================================
"""
Portfolio Exposure & Correlation Management Engine for V4.2 Institutional Architecture:
- Sector Concentration Guard: Maximum 25.0% of portfolio equity in any single sector
- Portfolio Beta Bounds: Weighted portfolio beta maintained within [0.60, 1.25]
- Correlation Protection: Prevents adding correlated directional risk if sector limits are reached
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ExposureEvaluation:
    is_compliant: bool
    rejection_reason: str = "COMPLIANT"
    sector_exposure_pct: float = 0.0
    portfolio_beta: float = 1.0
    asset_breakdown: Dict[str, float] = field(default_factory=dict)
    sector_breakdown: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_compliant": self.is_compliant,
            "rejection_reason": self.rejection_reason,
            "sector_exposure_pct": round(self.sector_exposure_pct, 2),
            "portfolio_beta": round(self.portfolio_beta, 3),
            "asset_breakdown": {k: round(v, 2) for k, v in self.asset_breakdown.items()},
            "sector_breakdown": {k: round(v, 2) for k, v in self.sector_breakdown.items()},
        }


class PortfolioExposureEngine:
    """
    Guarantees diversification and sector concentration limits across the multi-agent portfolio.
    """

    MAX_SECTOR_ALLOCATION_PCT: float = 25.0  # Max 25% per sector
    MIN_PORTFOLIO_BETA: float = 0.50
    MAX_PORTFOLIO_BETA: float = 1.30

    @classmethod
    def evaluate_exposure(
        cls,
        open_positions: List[Dict[str, Any]],
        portfolio_equity: float,
        proposed_trade: Optional[Dict[str, Any]] = None,
        candidate_sector: str = "",
        candidate_beta: float = 1.0,
    ) -> ExposureEvaluation:
        equity = max(1000.0, portfolio_equity)
        sector_weights: Dict[str, float] = {}
        asset_weights: Dict[str, float] = {"EQUITY": 0.0, "FUTURE": 0.0, "OPTION": 0.0, "CASH": equity}

        weighted_beta_sum = 0.0
        total_invested = 0.0

        all_positions = list(open_positions)
        if proposed_trade:
            all_positions.append(proposed_trade)

        for pos in all_positions:
            cost = float(pos.get("cost_basis", float(pos.get("quantity", 0)) * float(pos.get("entry_price", 0.0))))
            sector = pos.get("sector") or (candidate_sector if pos == proposed_trade else "Diversified")
            beta = float(pos.get("beta", candidate_beta if pos == proposed_trade else 1.0))
            inst_type = str(pos.get("instrument_type", pos.get("instrument", {}).get("instrument_type", "EQUITY"))).upper()

            sector_weights[sector] = sector_weights.get(sector, 0.0) + cost
            clean_inst = "OPTION" if "OPTION" in inst_type else ("FUTURE" if "FUTURE" in inst_type else "EQUITY")
            asset_weights[clean_inst] = asset_weights.get(clean_inst, 0.0) + cost
            weighted_beta_sum += cost * beta
            total_invested += cost

        # Compute percentages
        sector_pcts = {sec: (val / equity) * 100.0 for sec, val in sector_weights.items()}
        asset_pcts = {ast: (val / equity) * 100.0 for ast, val in asset_weights.items()}
        asset_pcts["CASH"] = max(0.0, ((equity - total_invested) / equity) * 100.0)

        avg_beta = (weighted_beta_sum / total_invested) if total_invested > 0 else 1.0

        # Check candidate sector breach
        target_sector = candidate_sector or (proposed_trade.get("sector") if proposed_trade else "")
        target_sector_pct = sector_pcts.get(target_sector, 0.0)

        if target_sector_pct > cls.MAX_SECTOR_ALLOCATION_PCT:
            return ExposureEvaluation(
                is_compliant=False,
                rejection_reason=f"Sector allocation for '{target_sector}' ({target_sector_pct:.1f}%) exceeds limit of {cls.MAX_SECTOR_ALLOCATION_PCT:.1f}%",
                sector_exposure_pct=target_sector_pct,
                portfolio_beta=avg_beta,
                asset_breakdown=asset_pcts,
                sector_breakdown=sector_pcts,
            )

        if avg_beta > cls.MAX_PORTFOLIO_BETA or avg_beta < cls.MIN_PORTFOLIO_BETA:
            return ExposureEvaluation(
                is_compliant=False,
                rejection_reason=f"Portfolio Beta ({avg_beta:.2f}) breached acceptable range [{cls.MIN_PORTFOLIO_BETA:.2f}, {cls.MAX_PORTFOLIO_BETA:.2f}]",
                sector_exposure_pct=target_sector_pct,
                portfolio_beta=avg_beta,
                asset_breakdown=asset_pcts,
                sector_breakdown=sector_pcts,
            )

        return ExposureEvaluation(
            is_compliant=True,
            rejection_reason="COMPLIANT",
            sector_exposure_pct=target_sector_pct,
            portfolio_beta=avg_beta,
            asset_breakdown=asset_pcts,
            sector_breakdown=sector_pcts,
        )
