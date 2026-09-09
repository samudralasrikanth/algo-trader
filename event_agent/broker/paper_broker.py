# =============================================================================
# event_agent/broker/paper_broker.py — Risk-Based Paper Trading Broker
# =============================================================================
"""
Autonomous Paper Trading Broker enforcing risk-based position sizing,
portfolio exposure limits, drawdown circuit breakers, and 5-min execution simulation.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from .cost_model import CostModel
from .execution_simulator import Candle5M, ExecutionSimulator, Fill
from .position_tracker import Position, PositionTracker

logger = logging.getLogger(__name__)

PORTFOLIO_CONFIG: Dict[str, Any] = {
    "initial_capital": 10_00_000,          # ₹10 Lakhs paper capital
    "risk_per_trade_pct": 0.5,            # Max 0.5% capital risked per trade (₹5,000)
    "max_trade_capital_pct": 10.0,        # Max 10% capital deployed in one stock
    "max_portfolio_exposure_pct": 50.0,   # Max 50% total exposure
    "max_correlated_exposure_pct": 25.0,  # Max 25% exposure per sector
    "min_confidence_to_trade": 55.0,      # Minimum calibrated conviction
    "max_daily_loss_pct": 1.5,            # Circuit breaker: stop trading for day if -1.5%
    "drawdown_warning_pct": 20.0,         # Alert threshold
    "drawdown_suspend_pct": 30.0,         # Trading halt threshold
}


class PaperBroker:
    """
    Automated risk-aware broker handling position lifecycle, capital governance,
    execution simulation, and post-trade accounting.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        cost_model: Optional[CostModel] = None,
        execution_simulator: Optional[ExecutionSimulator] = None,
    ):
        self.config = dict(PORTFOLIO_CONFIG)
        if config:
            self.config.update(config)

        self.cost_model = cost_model or CostModel(default_schedule="equity_intraday")
        self.simulator = execution_simulator or ExecutionSimulator(conservative_ambiguity=True)
        self.tracker = PositionTracker(initial_capital=self.config["initial_capital"])
        self.daily_starting_capital = self.config["initial_capital"]

    @property
    def current_capital(self) -> float:
        return self.tracker.get_portfolio_summary()["current_capital"]

    def calculate_position_size(
        self,
        entry: float,
        stop: float,
        portfolio_value: Optional[float] = None,
    ) -> int:
        """
        Risk-based sizing: Exactly 0.5% portfolio risk per trade.
        Quantity = Risk_Amount / Stop_Distance
        """
        cap = portfolio_value if portfolio_value is not None else self.current_capital
        risk_amount = cap * (self.config["risk_per_trade_pct"] / 100.0)

        stop_distance = abs(entry - stop)
        if stop_distance <= 0 or entry <= 0:
            return 0

        raw_quantity = int(risk_amount / stop_distance)

        # Single trade capital cap (10%)
        max_trade_capital = cap * (self.config["max_trade_capital_pct"] / 100.0)
        if raw_quantity * entry > max_trade_capital:
            raw_quantity = int(max_trade_capital / entry)

        return max(0, raw_quantity)

    def can_enter_trade(
        self,
        symbol: str,
        confidence: float,
        entry_price: float,
        quantity: int,
        sector: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Checks all risk rules, circuit breakers, and exposure ceilings.
        """
        summary = self.tracker.get_portfolio_summary()

        # 1. Drawdown suspension circuit breaker (30%)
        if summary["drawdown_pct"] >= self.config["drawdown_suspend_pct"]:
            return False, f"CIRCUIT_BREAKER: Portfolio in severe drawdown ({summary['drawdown_pct']:.1f}% >= {self.config['drawdown_suspend_pct']}%)"

        # 2. Daily loss limit (1.5%)
        daily_loss = self.daily_starting_capital - summary["current_capital"]
        daily_loss_pct = (daily_loss / self.daily_starting_capital) * 100 if self.daily_starting_capital > 0 else 0
        if daily_loss_pct >= self.config["max_daily_loss_pct"]:
            return False, f"CIRCUIT_BREAKER: Daily loss limit hit ({daily_loss_pct:.2f}% >= {self.config['max_daily_loss_pct']}%)"

        # 3. Minimum conviction requirement
        if confidence < self.config["min_confidence_to_trade"]:
            return False, f"LOW_CONFIDENCE: Calibrated conviction {confidence:.1f} < {self.config['min_confidence_to_trade']}"

        # 4. Total portfolio exposure check (50%)
        new_trade_capital = entry_price * quantity
        if new_trade_capital <= 0:
            return False, "INVALID_SIZE: Quantity or price is zero"

        projected_exposure = summary["open_exposure_rupees"] + new_trade_capital
        max_allowed_exposure = summary["current_capital"] * (self.config["max_portfolio_exposure_pct"] / 100.0)
        if projected_exposure > max_allowed_exposure:
            return False, f"EXPOSURE_LIMIT: Total exposure would exceed {self.config['max_portfolio_exposure_pct']}%"

        # 5. Sector concentration limit (25%)
        if sector:
            sector_exposure = sum(
                p.entry_price * p.quantity for p in self.tracker.get_open_positions()
                if getattr(p, "sector", "") == sector
            ) + new_trade_capital
            max_sector_exposure = summary["current_capital"] * (self.config["max_correlated_exposure_pct"] / 100.0)
            if sector_exposure > max_sector_exposure:
                return False, f"SECTOR_LIMIT: Sector exposure to {sector} would exceed {self.config['max_correlated_exposure_pct']}%"

        return True, "OK"

    def execute_prediction(
        self,
        prediction: Dict[str, Any],
        intraday_candles: Optional[Union[List[Candle5M], pd.DataFrame]] = None,
        execution_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[Position]:
        """
        Evaluate prediction and process execution if candles are provided.
        """
        action = prediction.get("action", "HOLD")
        if action not in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
            return None

        side = "LONG" if "BUY" in action else "SHORT"
        entry_price = float(prediction.get("entry_price", prediction.get("base_price", 0.0)))
        target_price = float(prediction.get("target_price", prediction.get("target_1d", entry_price)))
        stop_loss = float(prediction.get("stop_loss", entry_price * 0.98))
        symbol = prediction.get("symbol", "")
        confidence = float(prediction.get("conviction", 50.0))
        sector = prediction.get("sector")

        # Size position
        quantity = self.calculate_position_size(entry_price, stop_loss)
        if quantity <= 0:
            return None

        # Check risk permission
        allowed, reason = self.can_enter_trade(symbol, confidence, entry_price, quantity, sector)
        if not allowed:
            logger.info(f"Trade rejected for {symbol}: {reason}")
            return None

        # Open position
        pos = self.tracker.open_position(
            prediction_id=prediction.get("prediction_id", "UNKNOWN"),
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            target_price=target_price,
            stop_loss=stop_loss,
            execution_snapshot=execution_snapshot,
        )

        # If intraday candles provided, simulate fill immediately
        if intraday_candles is not None:
            fill = self.simulator.simulate_fill(
                side=side,
                entry_price=entry_price,
                target_price=target_price,
                stop_price=stop_loss,
                candles=intraday_candles,
                symbol=symbol,
                execution_snapshot=execution_snapshot,
            )

            # Round-trip cost modeling
            costs = self.cost_model.calculate_total_trade_costs(
                entry_price=entry_price,
                exit_price=fill.fill_price,
                quantity=quantity,
                position_side=side,
                instrument_type="equity_intraday",
            )

            # Close position
            pos = self.tracker.close_position(
                position_id=pos.position_id,
                exit_price=fill.fill_price,
                exit_reason=fill.reason,
                exit_time=fill.candle_time,
                is_ambiguous=fill.is_ambiguous,
                ambiguity_note=fill.ambiguity_note,
                cost_details=costs,
                execution_snapshot=fill.execution_snapshot,
            )

        return pos

    def get_portfolio_summary(self) -> Dict[str, Any]:
        return self.tracker.get_portfolio_summary()
