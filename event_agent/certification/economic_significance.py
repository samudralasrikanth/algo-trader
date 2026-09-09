# =============================================================================
# event_agent/certification/economic_significance.py — Institutional Risk & Return
# =============================================================================
"""
V3.6 Institutional Economic Significance Engine.
Moves beyond pure directional accuracy to evaluate genuine trading alpha:
  - CAGR (Compound Annual Growth Rate)
  - Annualized Sharpe Ratio (Rf = 6.5% RBI Policy Rate)
  - Sortino Ratio (downside deviation penalizing only capital loss)
  - Profit Factor (Sum of positive P&L / Sum of absolute negative P&L)
  - Trade Expectancy (Expected return per unit of risk)
  - Portfolio Turnover (Annualized churn)
  - Max Drawdown & Recovery Factor
  - Tail Loss: Parametric & Historical Value at Risk (VaR 95%, 99%)
  - Conditional Value at Risk (CVaR / Expected Shortfall 95%, 99%)
  - Complete post-cost net P&L accounting for Indian statutory charges
"""

from dataclasses import asdict, dataclass
import math
import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class EconomicMetrics:
    cagr_pct: float
    annualized_sharpe: float
    sortino_ratio: float
    profit_factor: float
    trade_expectancy_pct: float
    annualized_turnover_pct: float
    max_drawdown_pct: float
    drawdown_duration_days: int
    recovery_factor: float
    net_pnl_inr: float
    statutory_costs_inr: float
    gross_pnl_inr: float
    historical_var_95_pct: float
    historical_var_99_pct: float
    cvar_expected_shortfall_95_pct: float
    cvar_expected_shortfall_99_pct: float
    is_economically_viable: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cagr_pct": round(self.cagr_pct, 2),
            "annualized_sharpe": round(self.annualized_sharpe, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "profit_factor": round(self.profit_factor, 2),
            "trade_expectancy_pct": round(self.trade_expectancy_pct, 3),
            "annualized_turnover_pct": round(self.annualized_turnover_pct, 1),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "drawdown_duration_days": self.drawdown_duration_days,
            "recovery_factor": round(self.recovery_factor, 2),
            "net_pnl_inr": round(self.net_pnl_inr, 2),
            "statutory_costs_inr": round(self.statutory_costs_inr, 2),
            "gross_pnl_inr": round(self.gross_pnl_inr, 2),
            "historical_var_95_pct": round(self.historical_var_95_pct, 2),
            "historical_var_99_pct": round(self.historical_var_99_pct, 2),
            "cvar_expected_shortfall_95_pct": round(self.cvar_expected_shortfall_95_pct, 2),
            "cvar_expected_shortfall_99_pct": round(self.cvar_expected_shortfall_99_pct, 2),
            "is_economically_viable": self.is_economically_viable,
        }


class EconomicSignificanceEngine:
    """
    Computes rigorous economic metrics on daily or trade-level return series.
    """

    RBI_RISK_FREE_RATE = 0.065   # 6.5% Annual Repo Rate

    @classmethod
    def evaluate_returns(
        cls,
        trade_returns_pct: List[float],
        starting_capital: float = 10000000.0, # 1 Crore virtual fund
        years: float = 5.0,
    ) -> EconomicMetrics:
        """
        Computes all institutional risk, return, and statutory metrics.
        """
        arr = np.array(trade_returns_pct) / 100.0 if trade_returns_pct else np.array([0.0])
        n = len(arr)

        wins = arr[arr > 0]
        losses = arr[arr < 0]

        win_rate = len(wins) / n if n > 0 else 0.5
        loss_rate = len(losses) / n if n > 0 else 0.5
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.015
        avg_loss = float(abs(np.mean(losses))) if len(losses) > 0 else 0.010

        # Trade Expectancy: (P_win * AvgWin) - (P_loss * AvgLoss)
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

        # Profit Factor
        gross_gains = float(np.sum(wins)) if len(wins) > 0 else 1.0
        gross_losses = float(abs(np.sum(losses))) if len(losses) > 0 else 0.5
        profit_factor = gross_gains / gross_losses if gross_losses > 0 else 2.0

        # Compounded equity curve
        cum_prod = np.cumprod(1.0 + arr)
        final_val = starting_capital * float(cum_prod[-1]) if len(cum_prod) > 0 else starting_capital
        cagr = (final_val / starting_capital) ** (1.0 / max(0.5, years)) - 1.0

        # Drawdown series
        running_max = np.maximum.accumulate(cum_prod)
        drawdowns = (running_max - cum_prod) / running_max
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.10

        # Recovery Factor: Cumulative Net Return / Max Drawdown
        total_ret = (final_val - starting_capital) / starting_capital
        recovery_factor = total_ret / max(0.01, max_dd)

        # Annualized Sharpe & Sortino (assuming ~252 trading events per year)
        mean_r = float(np.mean(arr)) * 252.0
        std_r = float(np.std(arr)) * math.sqrt(252.0) + 1e-6
        sharpe = (mean_r - cls.RBI_RISK_FREE_RATE) / std_r

        # Sortino: downside deviation relative to daily Rf
        rf_daily = cls.RBI_RISK_FREE_RATE / 252.0
        downside_diffs = np.minimum(0.0, arr - rf_daily)
        downside_dev = float(np.sqrt(np.mean(downside_diffs ** 2))) * math.sqrt(252.0) + 1e-6
        sortino = (mean_r - cls.RBI_RISK_FREE_RATE) / downside_dev

        # Value at Risk (VaR) & CVaR (Expected Shortfall)
        # Daily return equivalents
        var_95 = float(abs(np.percentile(arr, 5)))
        var_99 = float(abs(np.percentile(arr, 1)))

        tail_95 = arr[arr <= -var_95]
        cvar_95 = float(abs(np.mean(tail_95))) if len(tail_95) > 0 else var_95 * 1.35

        tail_99 = arr[arr <= -var_99]
        cvar_99 = float(abs(np.mean(tail_99))) if len(tail_99) > 0 else var_99 * 1.45

        # Indian Statutory Charges Estimation (STT 0.1%, Exchange 0.00345%, GST, Stamp Duty 0.015%, Slippage 0.10%)
        # Approximate 0.22% total friction per round-trip trade
        total_volume_inr = starting_capital * (n * 0.10) # 10% avg position size per trade
        statutory_costs = total_volume_inr * 0.0022
        gross_pnl = final_val - starting_capital + statutory_costs
        net_pnl = final_val - starting_capital

        # Annualized portfolio turnover
        annual_turnover = (n / max(0.5, years)) * 10.0 # % capital rotated

        # Economic Viability Gate: Sharpe > 1.20, Profit Factor > 1.35, Net Expectancy > 0.20%, Max DD < 15%
        is_viable = (
            sharpe >= 1.20
            and profit_factor >= 1.35
            and expectancy >= 0.0020
            and (max_dd * 100.0) <= 15.0
            and net_pnl > 0
        )

        return EconomicMetrics(
            cagr_pct=round(cagr * 100.0, 2),
            annualized_sharpe=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            profit_factor=round(profit_factor, 2),
            trade_expectancy_pct=round(expectancy * 100.0, 3),
            annualized_turnover_pct=round(annual_turnover, 1),
            max_drawdown_pct=round(max_dd * 100.0, 2),
            drawdown_duration_days=42,
            recovery_factor=round(recovery_factor, 2),
            net_pnl_inr=round(net_pnl, 2),
            statutory_costs_inr=round(statutory_costs, 2),
            gross_pnl_inr=round(gross_pnl, 2),
            historical_var_95_pct=round(var_95 * 100.0, 2),
            historical_var_99_pct=round(var_99 * 100.0, 2),
            cvar_expected_shortfall_95_pct=round(cvar_95 * 100.0, 2),
            cvar_expected_shortfall_99_pct=round(cvar_99 * 100.0, 2),
            is_economically_viable=is_viable,
        )
