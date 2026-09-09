# =============================================================================
# event_agent/broker/position_tracker.py — Position & Portfolio State Tracker
# =============================================================================
"""
Maintains position state, lifecycle tracking, and comprehensive portfolio statistics.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents a trade position from initiation to closure."""
    position_id: str
    prediction_id: str
    symbol: str
    side: str                        # "LONG" | "SHORT"
    quantity: int
    entry_price: float
    target_price: float
    stop_loss: float
    entry_time: str
    status: str = "OPEN"             # "OPEN" | "CLOSED"
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    is_ambiguous: bool = False
    ambiguity_note: str = ""
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    total_friction_costs: float = 0.0
    cost_details: Dict[str, Any] = field(default_factory=dict)
    execution_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PositionTracker:
    """
    Manages active positions, closed book, and computes real-time portfolio statistics.
    """

    def __init__(self, initial_capital: float = 10_00_000.0):
        self.initial_capital = initial_capital
        self.open_positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        self._peak_capital = initial_capital

    def open_position(
        self,
        prediction_id: str,
        symbol: str,
        side: str,
        quantity: int,
        entry_price: float,
        target_price: float,
        stop_loss: float,
        entry_time: Optional[str] = None,
        execution_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Position:
        """Create and track a new open position."""
        now_iso = entry_time or datetime.now(timezone.utc).isoformat()
        pos_id = f"POS-{symbol.replace('.NS','')}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:17]}"

        pos = Position(
            position_id=pos_id,
            prediction_id=prediction_id,
            symbol=symbol,
            side=side.upper(),
            quantity=quantity,
            entry_price=entry_price,
            target_price=target_price,
            stop_loss=stop_loss,
            entry_time=now_iso,
            status="OPEN",
            execution_snapshot=execution_snapshot or {},
        )
        self.open_positions[pos_id] = pos
        return pos

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
        exit_time: Optional[str] = None,
        is_ambiguous: bool = False,
        ambiguity_note: str = "",
        cost_details: Optional[Dict[str, Any]] = None,
        execution_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Position:
        """Close an existing position and calculate P&L net of all costs."""
        pos = self.open_positions.pop(position_id, None)
        if not pos:
            raise KeyError(f"Position {position_id} not found in open book.")

        now_iso = exit_time or datetime.now(timezone.utc).isoformat()
        costs = cost_details or {}
        friction = costs.get("total_friction_cost", 0.0)

        # Gross P&L
        if pos.side == "LONG":
            gross_pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            gross_pnl = (pos.entry_price - exit_price) * pos.quantity

        net_pnl = gross_pnl - friction

        pos.status = "CLOSED"
        pos.exit_time = now_iso
        pos.exit_price = round(exit_price, 2)
        pos.exit_reason = exit_reason
        pos.is_ambiguous = is_ambiguous
        pos.ambiguity_note = ambiguity_note
        pos.gross_pnl = round(gross_pnl, 2)
        pos.net_pnl = round(net_pnl, 2)
        pos.total_friction_costs = round(friction, 2)
        pos.cost_details = costs
        if execution_snapshot:
            pos.execution_snapshot = execution_snapshot

        self.closed_positions.append(pos)
        return pos

    def get_open_positions(self) -> List[Position]:
        return list(self.open_positions.values())

    def get_closed_positions(self) -> List[Position]:
        return list(self.closed_positions)

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Compute performance, drawdowns, and audit transparency metrics."""
        closed = self.closed_positions
        total_closed = len(closed)

        total_gross_pnl = sum(p.gross_pnl for p in closed)
        total_costs = sum(p.total_friction_costs for p in closed)
        total_net_pnl = sum(p.net_pnl for p in closed)

        current_capital = self.initial_capital + total_net_pnl
        if current_capital > self._peak_capital:
            self._peak_capital = current_capital

        drawdown_rupees = max(0.0, self._peak_capital - current_capital)
        drawdown_pct = round((drawdown_rupees / self._peak_capital) * 100, 2) if self._peak_capital > 0 else 0.0

        # Win rate & Profit factor
        wins = [p for p in closed if p.net_pnl > 0]
        losses = [p for p in closed if p.net_pnl <= 0]
        win_rate = round((len(wins) / total_closed) * 100, 2) if total_closed > 0 else 0.0

        gross_wins = sum(p.gross_pnl for p in wins)
        gross_losses = abs(sum(p.gross_pnl for p in losses))
        profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 1.0)

        # Ambiguous fills count
        ambiguous_count = sum(1 for p in closed if p.is_ambiguous)
        ambiguous_pct = round((ambiguous_count / total_closed) * 100, 2) if total_closed > 0 else 0.0

        # Current open exposure
        open_exposure = sum(p.entry_price * p.quantity for p in self.open_positions.values())
        exposure_pct = round((open_exposure / current_capital) * 100, 2) if current_capital > 0 else 0.0

        return {
            "initial_capital": self.initial_capital,
            "current_capital": round(current_capital, 2),
            "peak_capital": round(self._peak_capital, 2),
            "total_net_pnl": round(total_net_pnl, 2),
            "total_gross_pnl": round(total_gross_pnl, 2),
            "total_friction_costs": round(total_costs, 2),
            "return_pct": round((total_net_pnl / self.initial_capital) * 100, 2),
            "drawdown_pct": drawdown_pct,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "total_closed_trades": total_closed,
            "open_positions_count": len(self.open_positions),
            "open_exposure_rupees": round(open_exposure, 2),
            "open_exposure_pct": exposure_pct,
            "ambiguous_fills_count": ambiguous_count,
            "ambiguous_fills_pct": ambiguous_pct,
        }
