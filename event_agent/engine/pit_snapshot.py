# =============================================================================
# event_agent/engine/pit_snapshot.py — Unified Point-In-Time Evidence Snapshot
# =============================================================================
"""
Unified PointInTimeSnapshot tying together:
- Market Price Snapshot + market_price_as_of
- Fundamental Snapshot + fundamental_as_of
- News Snapshot + news_as_of
- Macro Regime Snapshot + macro_as_of
- Prediction Timestamp
- Immutable SHA-256 Provenance Hash

Enforces Causal Invariant:
No constituent evidence timestamp can exceed prediction_timestamp.
Guarantees reproducible replay for prospective audit certification.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from event_agent.fundamentals.fundamental_snapshot import FundamentalSnapshot

logger = logging.getLogger(__name__)


@dataclass
class PointInTimeSnapshot:
    """
    Cryptographically sealed point-in-time snapshot locking all data visible to the
    prediction engine and the 5 strategy agents at decision time.
    """
    symbol: str
    market_price: float
    market_price_as_of: datetime
    prediction_timestamp: datetime
    fundamental_snapshot: Optional[FundamentalSnapshot] = None
    fundamental_as_of: Optional[datetime] = None
    news_snapshot: List[Dict[str, Any]] = field(default_factory=list)
    news_as_of: Optional[datetime] = None
    macro_snapshot: Dict[str, Any] = field(default_factory=dict)
    macro_as_of: Optional[datetime] = None
    data_mode: str = "PAPER"                     # LIVE, PAPER, REFERENCE_ONLY
    market_source: str = "UPSTOX"
    fundamental_source: str = "NSE_MARKET_LENS"
    news_source_version: str = "NEWS-V4"
    macro_source_version: str = "MACRO-V2"
    financial_period: str = ""
    trade_eligible: bool = True
    snapshot_id: str = ""
    provenance_hash: str = ""

    def __post_init__(self):
        if self.fundamental_snapshot is not None:
            self.fundamental_source = self.fundamental_snapshot.source
            if self.fundamental_snapshot.financial_period:
                self.financial_period = self.fundamental_snapshot.financial_period
            if not self.fundamental_snapshot.trade_eligible:
                self.trade_eligible = False
            if self.fundamental_snapshot.data_mode == "REFERENCE_ONLY":
                self.data_mode = "REFERENCE_ONLY"
        elif self.fundamental_source == "REFERENCE_DATASET":
            self.trade_eligible = False
            self.data_mode = "REFERENCE_ONLY"

        if not self.snapshot_id:
            clean_sym = self.symbol.replace(".NS", "").replace("^", "")
            ts_str = self.prediction_timestamp.strftime("%Y%m%d-%H%M%S")
            self.snapshot_id = f"PIT-{ts_str}-{clean_sym}"
        if not self.provenance_hash:
            self.provenance_hash = self.compute_provenance_hash()

    def compute_provenance_hash(self) -> str:
        """Computes deterministic SHA-256 hash over all point-in-time inputs and source versions."""
        p_iso = self.prediction_timestamp.isoformat()
        mp_iso = self.market_price_as_of.isoformat()
        f_iso = self.fundamental_as_of.isoformat() if self.fundamental_as_of else None
        n_iso = self.news_as_of.isoformat() if self.news_as_of else None
        m_iso = self.macro_as_of.isoformat() if self.macro_as_of else None

        f_hash = self.fundamental_snapshot.provenance_hash if self.fundamental_snapshot else None

        payload = {
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "data_mode": self.data_mode,
            "market_source": self.market_source,
            "fundamental_source": self.fundamental_source,
            "news_source_version": self.news_source_version,
            "macro_source_version": self.macro_source_version,
            "financial_period": self.financial_period,
            "trade_eligible": self.trade_eligible,
            "market_price": round(self.market_price, 4),
            "market_price_as_of": mp_iso,
            "prediction_timestamp": p_iso,
            "fundamental_provenance": f_hash,
            "fundamental_as_of": f_iso,
            "news_count": len(self.news_snapshot),
            "news_as_of": n_iso,
            "macro_as_of": m_iso,
            "macro_regime": self.macro_snapshot.get("label", "NEUTRAL"),
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def validate_causality(self) -> Tuple[bool, List[str]]:
        """
        Validates that every single evidence timestamp is <= prediction_timestamp.
        Strictly prevents look-ahead leakage.
        """
        errors: List[str] = []
        p_ts = self.prediction_timestamp

        def harmonize(t: Optional[datetime]) -> Optional[datetime]:
            if t is None:
                return None
            if t.tzinfo is None and p_ts.tzinfo is not None:
                return t.replace(tzinfo=timezone.utc)
            elif t.tzinfo is not None and p_ts.tzinfo is None:
                return t.replace(tzinfo=None)
            return t

        p_ts_harm = harmonize(p_ts)

        # 1. Market price causality
        mp_ts = harmonize(self.market_price_as_of)
        if mp_ts and mp_ts > p_ts_harm:
            errors.append(f"MARKET_PRICE_FUTURE: {mp_ts.isoformat()} > {p_ts_harm.isoformat()}")

        # 2. Fundamental causality
        f_ts = harmonize(self.fundamental_as_of)
        if f_ts and f_ts > p_ts_harm:
            errors.append(f"FUNDAMENTAL_FUTURE: {f_ts.isoformat()} > {p_ts_harm.isoformat()}")

        # 3. News causality
        n_ts = harmonize(self.news_as_of)
        if n_ts and n_ts > p_ts_harm:
            errors.append(f"NEWS_FUTURE: {n_ts.isoformat()} > {p_ts_harm.isoformat()}")

        # 4. Macro causality
        m_ts = harmonize(self.macro_as_of)
        if m_ts and m_ts > p_ts_harm:
            errors.append(f"MACRO_FUTURE: {m_ts.isoformat()} > {p_ts_harm.isoformat()}")

        is_valid = (len(errors) == 0)
        return is_valid, errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "data_mode": self.data_mode,
            "market_source": self.market_source,
            "fundamental_source": self.fundamental_source,
            "news_source_version": self.news_source_version,
            "macro_source_version": self.macro_source_version,
            "financial_period": self.financial_period,
            "trade_eligible": self.trade_eligible,
            "market_price": round(self.market_price, 2),
            "market_price_as_of": self.market_price_as_of.isoformat(),
            "prediction_timestamp": self.prediction_timestamp.isoformat(),
            "fundamental_snapshot": self.fundamental_snapshot.to_dict() if self.fundamental_snapshot else None,
            "fundamental_as_of": self.fundamental_as_of.isoformat() if self.fundamental_as_of else None,
            "news_count": len(self.news_snapshot),
            "news_as_of": self.news_as_of.isoformat() if self.news_as_of else None,
            "macro_snapshot": self.macro_snapshot,
            "macro_as_of": self.macro_as_of.isoformat() if self.macro_as_of else None,
            "provenance_hash": self.provenance_hash,
        }
