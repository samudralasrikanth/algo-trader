# =============================================================================
# event_agent/prediction/outcome_engine.py — Automated Prediction Resolution Engine
# =============================================================================
"""
V3.5 Automated Prediction Outcome Resolution Engine.
Resolves each prediction upon horizon expiry against actual market data.
Measures direction accuracy, return error, target/stop hits, and interval calibration.
Stores permanent outcome records linked to prediction_id.
"""

import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .ledger import DB_PATH

logger = logging.getLogger(__name__)


@dataclass
class PredictionOutcome:
    outcome_id: str
    prediction_id: str
    symbol: str
    horizon: str
    entry_price: float
    closing_price: float
    actual_return: float               # e.g. 0.0172 for +1.72%
    predicted_return: float            # e.g. 0.0110 for +1.10%
    predicted_direction: str           # UP, DOWN, NEUTRAL
    actual_direction: str              # UP, DOWN, NEUTRAL
    direction_correct: bool
    target_price: float
    stop_price: float
    target_hit: bool
    stop_hit: bool
    signed_error: float                # actual_return - predicted_return
    absolute_error: float              # abs(signed_error)
    covered_50_pct: bool
    covered_80_pct: bool
    resolved_at: str


class OutcomeEngine:
    """
    Automated evaluation and resolution engine for prediction outcomes.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prediction_outcomes_v35 (
                    outcome_id TEXT PRIMARY KEY,
                    prediction_id TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    closing_price REAL NOT NULL,
                    actual_return REAL NOT NULL,
                    predicted_return REAL NOT NULL,
                    predicted_direction TEXT NOT NULL,
                    actual_direction TEXT NOT NULL,
                    direction_correct INTEGER NOT NULL,
                    target_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    target_hit INTEGER NOT NULL,
                    stop_hit INTEGER NOT NULL,
                    signed_error REAL NOT NULL,
                    absolute_error REAL NOT NULL,
                    covered_50_pct INTEGER NOT NULL,
                    covered_80_pct INTEGER NOT NULL,
                    resolved_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_v35_pred_id ON prediction_outcomes_v35(prediction_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_v35_symbol ON prediction_outcomes_v35(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_v35_horizon ON prediction_outcomes_v35(horizon)")
            conn.commit()

    def resolve_prediction(
        self,
        prediction: Dict[str, Any],
        closing_price: float,
        high_price: Optional[float] = None,
        low_price: Optional[float] = None,
        intervals: Optional[Dict[str, tuple]] = None,
        resolved_at: Optional[str] = None,
    ) -> PredictionOutcome:
        """
        Evaluate and resolve a prediction record against actual market outcome.
        """
        pred_id = prediction["prediction_id"]
        symbol = prediction["symbol"]
        horizon = prediction["horizon"]
        entry_p = float(prediction["price_at_prediction"])
        pred_ret = float(prediction.get("expected_return", 0.0))
        pred_dir = str(prediction.get("direction", "NEUTRAL")).upper()
        target_p = float(prediction.get("target", entry_p * (1.0 + pred_ret)))
        stop_p = float(prediction.get("stop", entry_p * (1.0 - pred_ret)))

        if entry_p <= 0:
            raise ValueError(f"Invalid entry price for prediction {pred_id}: {entry_p}")

        actual_ret = round((closing_price - entry_p) / entry_p, 5)

        if actual_ret > 0.001:
            actual_dir = "UP"
        elif actual_ret < -0.001:
            actual_dir = "DOWN"
        else:
            actual_dir = "NEUTRAL"

        direction_correct = (pred_dir == actual_dir)

        # High/low checks for target/stop
        hi = high_price if high_price is not None else max(entry_p, closing_price)
        lo = low_price if low_price is not None else min(entry_p, closing_price)

        if pred_dir == "UP":
            target_hit = hi >= target_p
            stop_hit = lo <= stop_p
        elif pred_dir == "DOWN":
            target_hit = lo <= target_p
            stop_hit = hi >= stop_p
        else:
            target_hit = False
            stop_hit = False

        signed_err = round(actual_ret - pred_ret, 5)
        abs_err = round(abs(signed_err), 5)

        # Credible intervals coverage
        covered_50 = False
        covered_80 = False
        if intervals:
            int_50 = intervals.get("interval_50")
            if int_50 and len(int_50) == 2:
                covered_50 = (int_50[0] <= actual_ret <= int_50[1])
            int_80 = intervals.get("interval_80")
            if int_80 and len(int_80) == 2:
                covered_80 = (int_80[0] <= actual_ret <= int_80[1])

        res_time = resolved_at or datetime.now(timezone.utc).isoformat()
        outcome_id = hashlib.sha256(f"{pred_id}:{res_time}:{closing_price}".encode("utf-8")).hexdigest()[:24]

        outcome = PredictionOutcome(
            outcome_id=outcome_id,
            prediction_id=pred_id,
            symbol=symbol,
            horizon=horizon,
            entry_price=entry_p,
            closing_price=closing_price,
            actual_return=actual_ret,
            predicted_return=pred_ret,
            predicted_direction=pred_dir,
            actual_direction=actual_dir,
            direction_correct=direction_correct,
            target_price=target_p,
            stop_price=stop_p,
            target_hit=target_hit,
            stop_hit=stop_hit,
            signed_error=signed_err,
            absolute_error=abs_err,
            covered_50_pct=covered_50,
            covered_80_pct=covered_80,
            resolved_at=res_time,
        )

        self._store_outcome(outcome)
        return outcome

    def _store_outcome(self, outcome: PredictionOutcome) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO prediction_outcomes_v35 (
                    outcome_id, prediction_id, symbol, horizon, entry_price,
                    closing_price, actual_return, predicted_return,
                    predicted_direction, actual_direction, direction_correct,
                    target_price, stop_price, target_hit, stop_hit,
                    signed_error, absolute_error, covered_50_pct,
                    covered_80_pct, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                outcome.outcome_id,
                outcome.prediction_id,
                outcome.symbol,
                outcome.horizon,
                outcome.entry_price,
                outcome.closing_price,
                outcome.actual_return,
                outcome.predicted_return,
                outcome.predicted_direction,
                outcome.actual_direction,
                1 if outcome.direction_correct else 0,
                outcome.target_price,
                outcome.stop_price,
                1 if outcome.target_hit else 0,
                1 if outcome.stop_hit else 0,
                outcome.signed_error,
                outcome.absolute_error,
                1 if outcome.covered_50_pct else 0,
                1 if outcome.covered_80_pct else 0,
                outcome.resolved_at,
            ))
            conn.commit()
        logger.info("Resolved prediction %s: return=%+.2f%%, correct=%s", outcome.prediction_id, outcome.actual_return * 100, outcome.direction_correct)

    def get_outcome(self, prediction_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM prediction_outcomes_v35 WHERE prediction_id = ?", (prediction_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["direction_correct"] = bool(d["direction_correct"])
            d["target_hit"] = bool(d["target_hit"])
            d["stop_hit"] = bool(d["stop_hit"])
            d["covered_50_pct"] = bool(d["covered_50_pct"])
            d["covered_80_pct"] = bool(d["covered_80_pct"])
            return d

    def list_outcomes(self, horizon: Optional[str] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        query = "SELECT * FROM prediction_outcomes_v35 WHERE 1=1"
        params: List[Any] = []
        if horizon:
            query += " AND horizon = ?"
            params.append(horizon)
        query += " ORDER BY resolved_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["direction_correct"] = bool(d["direction_correct"])
                d["target_hit"] = bool(d["target_hit"])
                d["stop_hit"] = bool(d["stop_hit"])
                d["covered_50_pct"] = bool(d["covered_50_pct"])
                d["covered_80_pct"] = bool(d["covered_80_pct"])
                results.append(d)
            return results
