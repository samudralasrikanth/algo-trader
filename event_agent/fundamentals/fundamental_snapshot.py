# =============================================================================
# event_agent/fundamentals/fundamental_snapshot.py — Core Fundamental Snapshot & Context
# =============================================================================
"""
Core data objects and schema contracts for the NEXUS V4.2.2 Fundamental Intelligence Layer:
- FundamentalSnapshot: Point-in-time fundamental profile with cryptographic provenance.
- FundamentalContext: Standardized context object embedded inside MarketThesis.
- Enums: FundamentalRole, FundamentalRegime, FundamentalFreshness.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Dict, List, Optional


class FundamentalRole(str, Enum):
    """How fundamentals are used by screening or strategy agents."""
    QUALITY_FILTER = "QUALITY_FILTER"
    VALUATION_CONTEXT = "VALUATION_CONTEXT"
    GROWTH_CONTEXT = "GROWTH_CONTEXT"
    RISK_CONTEXT = "RISK_CONTEXT"
    NO_SIGNAL = "NO_SIGNAL"


class FundamentalRegime(str, Enum):
    """Aggregate market-level or stock-level fundamental regime."""
    HEALTHY = "HEALTHY"
    MIXED = "MIXED"
    STRETCHED = "STRETCHED"
    WEAKENING = "WEAKENING"
    STRESSED = "STRESSED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FundamentalFreshness(str, Enum):
    """Point-in-time freshness classification."""
    FRESH = "FRESH"             # <= 90 days (current quarter)
    ACCEPTABLE = "ACCEPTABLE"   # 91 to 180 days (prior quarter, still usable)
    STALE = "STALE"             # > 180 days (outdated financials)
    EXPIRED = "EXPIRED"         # > 365 days
    UNAVAILABLE = "UNAVAILABLE" # No fundamental data present


@dataclass
class FundamentalSnapshot:
    """
    Point-in-time immutable fundamental snapshot for a single equity.
    Enforces runtime truth: if data is absent, quality_score is None, not 0 or fabricated.
    """
    symbol: str
    as_of: datetime
    source: str = "FUNDAMENTALS_UNAVAILABLE"
    data_mode: str = "PAPER"           # LIVE, PAPER, REFERENCE_ONLY
    financial_period: str = ""         # e.g. "Q1 FY27", "Q4 FY26"
    trade_eligible: bool = True        # False if source == "REFERENCE_DATASET" or data_mode == "REFERENCE_ONLY"
    valuation: Dict[str, float] = field(default_factory=dict)
    profitability: Dict[str, float] = field(default_factory=dict)
    growth: Dict[str, float] = field(default_factory=dict)
    leverage: Dict[str, float] = field(default_factory=dict)
    ownership: Dict[str, float] = field(default_factory=dict)
    quality_score: Optional[float] = None
    valuation_score: Optional[float] = None
    growth_score: Optional[float] = None
    balance_sheet_score: Optional[float] = None
    fundamental_regime: str = FundamentalRegime.INSUFFICIENT_DATA.value
    freshness: str = FundamentalFreshness.UNAVAILABLE.value
    provenance_hash: str = ""

    def __post_init__(self):
        # Enforce non-trading safety for reference datasets
        if self.source == "REFERENCE_DATASET" or self.data_mode == "REFERENCE_ONLY":
            self.trade_eligible = False
            self.data_mode = "REFERENCE_ONLY"
        if not self.provenance_hash:
            self.provenance_hash = self.compute_provenance_hash()

    @property
    def is_available(self) -> bool:
        return self.source != "FUNDAMENTALS_UNAVAILABLE"

    @property
    def is_fresh(self) -> bool:
        return self.is_available and self.freshness in (FundamentalFreshness.FRESH.value, FundamentalFreshness.ACCEPTABLE.value)

    def compute_provenance_hash(self) -> str:
        """Computes deterministic SHA-256 hash of point-in-time state."""
        as_of_iso = self.as_of.isoformat() if isinstance(self.as_of, datetime) else str(self.as_of)

        def _fmt(val: Any) -> Any:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    return str(val)
                return round(val, 4)
            return val

        payload = {
            "symbol": self.symbol,
            "as_of": as_of_iso,
            "source": self.source,
            "data_mode": self.data_mode,
            "financial_period": self.financial_period,
            "trade_eligible": self.trade_eligible,
            "valuation": {k: _fmt(v) for k, v in sorted(self.valuation.items())},
            "profitability": {k: _fmt(v) for k, v in sorted(self.profitability.items())},
            "growth": {k: _fmt(v) for k, v in sorted(self.growth.items())},
            "leverage": {k: _fmt(v) for k, v in sorted(self.leverage.items())},
            "ownership": {k: _fmt(v) for k, v in sorted(self.ownership.items())},
            "quality_score": _fmt(self.quality_score) if self.quality_score is not None else None,
            "valuation_score": _fmt(self.valuation_score) if self.valuation_score is not None else None,
            "growth_score": _fmt(self.growth_score) if self.growth_score is not None else None,
            "balance_sheet_score": _fmt(self.balance_sheet_score) if self.balance_sheet_score is not None else None,
            "fundamental_regime": self.fundamental_regime,
        }
        raw_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        as_of_iso = self.as_of.isoformat() if isinstance(self.as_of, datetime) else str(self.as_of)
        return {
            "symbol": self.symbol,
            "as_of": as_of_iso,
            "source": self.source,
            "data_mode": self.data_mode,
            "financial_period": self.financial_period,
            "trade_eligible": self.trade_eligible,
            "valuation": self.valuation,
            "profitability": self.profitability,
            "growth": self.growth,
            "leverage": self.leverage,
            "ownership": self.ownership,
            "quality_score": self.quality_score,
            "valuation_score": self.valuation_score,
            "growth_score": self.growth_score,
            "balance_sheet_score": self.balance_sheet_score,
            "fundamental_regime": self.fundamental_regime,
            "freshness": self.freshness,
            "provenance_hash": self.provenance_hash,
            "is_available": self.is_available,
            "is_fresh": self.is_fresh,
        }


@dataclass
class FundamentalContext:
    """
    Standardized fundamental evidence attached directly to a MarketThesis.
    Guarantees the AI and downstream selectors only see deterministic scores.
    Maintains clean separation between execution_edge and shadow_adjusted_edge.
    """
    quality_score: Optional[float] = None
    valuation_score: Optional[float] = None
    growth_score: Optional[float] = None
    balance_sheet_score: Optional[float] = None
    fundamental_regime: str = FundamentalRegime.INSUFFICIENT_DATA.value
    confirmation: bool = False
    contradiction: bool = False
    data_as_of: Optional[str] = None
    source: str = "FUNDAMENTALS_UNAVAILABLE"
    data_mode: str = "PAPER"
    trade_eligible: bool = True
    role: str = FundamentalRole.NO_SIGNAL.value
    reasoning: str = ""
    # Observational shadow-mode edge fields
    fundamental_adj: float = 0.0
    execution_edge: Optional[float] = None
    shadow_adjusted_edge: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "valuation_score": self.valuation_score,
            "growth_score": self.growth_score,
            "balance_sheet_score": self.balance_sheet_score,
            "fundamental_regime": self.fundamental_regime,
            "confirmation": self.confirmation,
            "contradiction": self.contradiction,
            "data_as_of": self.data_as_of,
            "source": self.source,
            "data_mode": self.data_mode,
            "trade_eligible": self.trade_eligible,
            "role": self.role,
            "reasoning": self.reasoning,
            "fundamental_adj": self.fundamental_adj,
            "execution_edge": self.execution_edge,
            "shadow_adjusted_edge": self.shadow_adjusted_edge,
        }
