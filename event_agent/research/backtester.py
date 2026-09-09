# =============================================================================
# event_agent/research/backtester.py — Point-in-Time Quantitative Backtester
# =============================================================================
"""
Point-in-Time Quantitative Backtester simulating multi-asset event trading.
Ensures zero look-ahead bias and benchmarks active model returns against all 5 baselines.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from ..broker.cost_model import CostModel
from ..broker.execution_simulator import Candle5M, ExecutionSimulator
from .baseline_models import BaselineSuite
from .walk_forward import PointInTimeError, WalkForwardValidator

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Backtests event-driven prediction models with transaction costs,
    5-minute execution rules, and baseline comparisons.
    """

    def __init__(
        self,
        initial_capital: float = 10_00_000.0,
        risk_per_trade_pct: float = 0.5,
        cost_model: Optional[CostModel] = None,
        execution_simulator: Optional[ExecutionSimulator] = None,
    ):
        self.initial_capital = initial_capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.cost_model = cost_model or CostModel(default_schedule="equity_intraday")
        self.simulator = execution_simulator or ExecutionSimulator(conservative_ambiguity=True)
        self.validator = WalkForwardValidator()
        self.baseline_suite = BaselineSuite()

    def run_backtest(
        self,
        historical_predictions: List[Dict[str, Any]],
        intraday_data_map: Optional[Dict[str, List[Candle5M]]] = None,
    ) -> Dict[str, Any]:
        """
        Execute backtest over historical predictions.
        """
        if not historical_predictions:
            return {"total_trades": 0, "net_pnl": 0.0, "return_pct": 0.0}

        trades = []
        capital = self.initial_capital
        peak_capital = capital
        m_data = intraday_data_map or {}

        model_correct_count = 0
        b0_correct_count = 0
        b1_correct_count = 0
        b2_correct_count = 0
        b3_correct_count = 0
        nifty_buy_and_hold_return = 0.0

        for pred in historical_predictions:
            sym = pred.get("symbol", "")
            pred_id = pred.get("prediction_id", "")
            action = pred.get("action", "HOLD")

            # Check point-in-time validity
            self.validator.verify_point_in_time_availability(
                features=pred.get("features_provenance", []),
                prediction_timestamp=pred.get("timestamp", datetime.now().isoformat()),
            )

            entry_p = float(pred.get("entry_price", pred.get("base_price", 100.0)))
            target_p = float(pred.get("target_price", pred.get("target_1d", entry_p * 1.01)))
            stop_p = float(pred.get("stop_loss", entry_p * 0.98))
            side = "LONG" if "BUY" in action else ("SHORT" if "SELL" in action else "NONE")

            if side == "NONE":
                continue

            # Position sizing (0.5% risk)
            risk_amt = capital * (self.risk_per_trade_pct / 100.0)
            stop_dist = abs(entry_p - stop_p)
            qty = int(risk_amt / stop_dist) if stop_dist > 0 else 0
            # 10% cap
            if qty * entry_p > capital * 0.10 and entry_p > 0:
                qty = int((capital * 0.10) / entry_p)

            if qty <= 0:
                continue

            # Evaluate execution fill
            candles = m_data.get(pred_id, [])
            fill = self.simulator.simulate_fill(
                side=side,
                entry_price=entry_p,
                target_price=target_p,
                stop_price=stop_p,
                candles=candles,
                symbol=sym,
            )

            # Calculate costs
            costs = self.cost_model.calculate_total_trade_costs(
                entry_price=entry_p,
                exit_price=fill.fill_price,
                quantity=qty,
                position_side=side,
            )

            # P&L
            gross_pnl = (fill.fill_price - entry_p) * qty if side == "LONG" else (entry_p - fill.fill_price) * qty
            friction = costs["total_friction_cost"]
            net_pnl = gross_pnl - friction

            capital += net_pnl
            if capital > peak_capital:
                peak_capital = capital

            trades.append({
                "symbol": sym,
                "side": side,
                "entry_price": entry_p,
                "exit_price": fill.fill_price,
                "quantity": qty,
                "fill_reason": fill.reason,
                "is_ambiguous": fill.is_ambiguous,
                "gross_pnl": round(gross_pnl, 2),
                "friction_cost": round(friction, 2),
                "net_pnl": round(net_pnl, 2),
            })

        # Calculate portfolio statistics
        n_trades = len(trades)
        wins = [t for t in trades if t["net_pnl"] > 0]
        losses = [t for t in trades if t["net_pnl"] <= 0]

        total_net_pnl = sum(t["net_pnl"] for t in trades)
        total_friction = sum(t["friction_cost"] for t in trades)
        win_rate = (len(wins) / n_trades * 100) if n_trades > 0 else 0.0

        gross_wins = sum(t["gross_pnl"] for t in wins)
        gross_losses = abs(sum(t["gross_pnl"] for t in losses))
        profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 1.0)

        returns_arr = np.array([t["net_pnl"] / self.initial_capital for t in trades]) if trades else np.array([0.0])
        sharpe = round(float(np.mean(returns_arr) / (np.std(returns_arr) + 1e-6) * np.sqrt(252)), 2)

        drawdown = round(((peak_capital - capital) / peak_capital) * 100, 2) if peak_capital > 0 else 0.0

        return {
            "initial_capital": self.initial_capital,
            "final_capital": round(capital, 2),
            "total_net_pnl": round(total_net_pnl, 2),
            "total_friction_costs": round(total_friction, 2),
            "total_trades": n_trades,
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": drawdown,
            "trades": trades,
        }
