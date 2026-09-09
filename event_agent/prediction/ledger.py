# =============================================================================
# event_agent/prediction/ledger.py — Immutable Prediction Record Ledger
# =============================================================================
"""
V3.5 Permanent Immutable Prediction Record Ledger.
Every prediction made by NEXUS is stored with full point-in-time snapshot references,
explicit horizon classification, individual agent signals, ensemble voting,
and cryptographic provenance hash.
"""

import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

HORIZONS_INTRADAY = ["15m", "30m", "60m"]
HORIZONS_SHORT_TERM = ["1D", "3D", "5D"]
HORIZONS_MEDIUM_TERM = ["10D", "20D"]
HORIZONS_SUPPORTED = HORIZONS_INTRADAY + HORIZONS_SHORT_TERM + HORIZONS_MEDIUM_TERM

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "event_predictions.db"


def classify_horizon_type(horizon: str) -> str:
    if horizon in HORIZONS_INTRADAY:
        return "INTRADAY"
    elif horizon in HORIZONS_SHORT_TERM:
        return "SHORT_TERM"
    elif horizon in HORIZONS_MEDIUM_TERM:
        return "MEDIUM_TERM"
    else:
        raise ValueError(f"Unsupported prediction horizon: {horizon}. Must be one of {HORIZONS_SUPPORTED}")


@dataclass
class AgentSignal:
    agent_name: str
    direction: str                     # UP, DOWN, NEUTRAL
    probability_up: float              # 0.0 to 1.0
    expected_return: float             # e.g. 0.015 for +1.5%
    confidence: float                  # 0 to 100
    weight: float = 1.0


@dataclass
class PredictionRecord:
    prediction_id: str
    timestamp: str
    decision_timestamp: str
    symbol: str
    exchange: str
    price_at_prediction: float

    # Snapshot provenance
    market_snapshot_id: str
    data_snapshot_id: str
    event_snapshot_id: str
    regime_snapshot_id: str

    # Prediction core
    direction: str                     # UP, DOWN, NEUTRAL
    probability_up: float              # 0.0 to 1.0
    probability_down: float            # 0.0 to 1.0
    expected_return: float             # e.g. 0.012 for +1.2%
    target: float
    stop: float
    horizon: str                       # e.g. "1D", "5D", "15m"
    confidence: float                  # 0.0 to 100.0
    prediction_type: str               # INTRADAY, SHORT_TERM, MEDIUM_TERM

    # 5 Agents signals
    alpha_prediction: Dict[str, Any]
    momentum_prediction: Dict[str, Any]
    macro_prediction: Dict[str, Any]
    defensive_prediction: Dict[str, Any]
    contrarian_prediction: Dict[str, Any]

    # Ensemble breakdown
    ensemble_direction: str
    ensemble_probability: float
    ensemble_score: float
    no_trade_status: bool
    no_trade_reason: Optional[str] = None

    # Versioning & hash
    model_version: str = "3.5.0"
    weights_version: str = "W1.0"
    config_version: str = "CONF-V35"
    snapshot_hash: str = ""

    def __post_init__(self):
        if self.horizon not in HORIZONS_SUPPORTED:
            raise ValueError(f"Invalid horizon '{self.horizon}'. Supported: {HORIZONS_SUPPORTED}")
        self.prediction_type = classify_horizon_type(self.horizon)
        if not self.snapshot_hash:
            self.snapshot_hash = self.generate_hash()

    def generate_hash(self) -> str:
        payload = (
            f"{self.symbol}:{self.decision_timestamp}:{self.price_at_prediction}:"
            f"{self.direction}:{self.horizon}:{self.market_snapshot_id}:{self.data_snapshot_id}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PredictionLedger:
    """
    Manages persistent, immutable storage of all NEXUS predictions.
    Guarantees no records can be overwritten or deleted.
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
                CREATE TABLE IF NOT EXISTS prediction_ledger_v35 (
                    prediction_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    decision_timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    price_at_prediction REAL NOT NULL,
                    market_snapshot_id TEXT NOT NULL,
                    data_snapshot_id TEXT NOT NULL,
                    event_snapshot_id TEXT NOT NULL,
                    regime_snapshot_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    probability_up REAL NOT NULL,
                    probability_down REAL NOT NULL,
                    expected_return REAL NOT NULL,
                    target REAL NOT NULL,
                    stop REAL NOT NULL,
                    horizon TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    prediction_type TEXT NOT NULL,
                    alpha_prediction_json TEXT NOT NULL,
                    momentum_prediction_json TEXT NOT NULL,
                    macro_prediction_json TEXT NOT NULL,
                    defensive_prediction_json TEXT NOT NULL,
                    contrarian_prediction_json TEXT NOT NULL,
                    ensemble_direction TEXT NOT NULL,
                    ensemble_probability REAL NOT NULL,
                    ensemble_score REAL NOT NULL,
                    no_trade_status INTEGER NOT NULL,
                    no_trade_reason TEXT,
                    model_version TEXT NOT NULL,
                    weights_version TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_v35_symbol ON prediction_ledger_v35(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_v35_horizon ON prediction_ledger_v35(horizon)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_v35_ts ON prediction_ledger_v35(decision_timestamp)")
            conn.commit()

    def record_prediction(self, record: PredictionRecord) -> str:
        """Store an immutable prediction record. Errors if prediction_id already exists."""
        created_at = datetime.now(timezone.utc).isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO prediction_ledger_v35 (
                    prediction_id, timestamp, decision_timestamp, symbol, exchange,
                    price_at_prediction, market_snapshot_id, data_snapshot_id,
                    event_snapshot_id, regime_snapshot_id, direction, probability_up,
                    probability_down, expected_return, target, stop, horizon,
                    confidence, prediction_type, alpha_prediction_json,
                    momentum_prediction_json, macro_prediction_json,
                    defensive_prediction_json, contrarian_prediction_json,
                    ensemble_direction, ensemble_probability, ensemble_score,
                    no_trade_status, no_trade_reason, model_version,
                    weights_version, config_version, snapshot_hash, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                record.prediction_id,
                record.timestamp,
                record.decision_timestamp,
                record.symbol,
                record.exchange,
                record.price_at_prediction,
                record.market_snapshot_id,
                record.data_snapshot_id,
                record.event_snapshot_id,
                record.regime_snapshot_id,
                record.direction,
                record.probability_up,
                record.probability_down,
                record.expected_return,
                record.target,
                record.stop,
                record.horizon,
                record.confidence,
                record.prediction_type,
                json.dumps(record.alpha_prediction),
                json.dumps(record.momentum_prediction),
                json.dumps(record.macro_prediction),
                json.dumps(record.defensive_prediction),
                json.dumps(record.contrarian_prediction),
                record.ensemble_direction,
                record.ensemble_probability,
                record.ensemble_score,
                1 if record.no_trade_status else 0,
                record.no_trade_reason,
                record.model_version,
                record.weights_version,
                record.config_version,
                record.snapshot_hash,
                created_at,
            ))
            conn.commit()

        logger.info("Recorded immutable prediction %s for %s (%s)", record.prediction_id, record.symbol, record.horizon)
        return record.prediction_id

    def get_prediction(self, prediction_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve prediction by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM prediction_ledger_v35 WHERE prediction_id = ?",
                (prediction_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def list_predictions(
        self,
        symbol: Optional[str] = None,
        horizon: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List predictions filtered by symbol and/or horizon."""
        query = "SELECT * FROM prediction_ledger_v35 WHERE 1=1"
        params: List[Any] = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if horizon:
            query += " AND horizon = ?"
            params.append(horizon)

        query += " ORDER BY decision_timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["no_trade_status"] = bool(d["no_trade_status"])
        d["alpha_prediction"] = json.loads(d.pop("alpha_prediction_json", "{}"))
        d["momentum_prediction"] = json.loads(d.pop("momentum_prediction_json", "{}"))
        d["macro_prediction"] = json.loads(d.pop("macro_prediction_json", "{}"))
        d["defensive_prediction"] = json.loads(d.pop("defensive_prediction_json", "{}"))
        d["contrarian_prediction"] = json.loads(d.pop("contrarian_prediction_json", "{}"))
        return d
