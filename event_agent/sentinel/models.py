# =============================================================================
# event_agent/sentinel/models.py — V4.2.1 Event Sentinel Domain Models
# =============================================================================
"""
Core domain models for V4.2.1 Continuous Event Intelligence:
- 19 Standard Event Categories
- Multi-tier verdicts: STORE_ONLY, UPDATE_THESIS, TRIGGER_RE_EVALUATION, MARKET_SHOCK
- Full provenance ThesisRevision tracking with before/after state diffs
- Dual-denominator Event Coverage metrics
- Scheduled Economic Calendar stages (T-24h to T+30m)
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional


class EventCategory(str, Enum):
    FOMC = "FOMC"
    RBI = "RBI"
    ECB = "ECB"
    BOJ = "BOJ"
    INFLATION = "INFLATION"
    EMPLOYMENT = "EMPLOYMENT"
    GDP = "GDP"
    INTEREST_RATE = "INTEREST_RATE"
    BOND_YIELD = "BOND_YIELD"
    CURRENCY = "CURRENCY"
    COMMODITY = "COMMODITY"
    GEOPOLITICAL = "GEOPOLITICAL"
    GLOBAL_EQUITY = "GLOBAL_EQUITY"
    INDIA_MACRO = "INDIA_MACRO"
    CORPORATE = "CORPORATE"
    EARNINGS = "EARNINGS"
    REGULATORY = "REGULATORY"
    BLACK_SWAN = "BLACK_SWAN"
    MARKET_SHOCK = "MARKET_SHOCK"


class TriggerVerdict(str, Enum):
    STORE_ONLY = "STORE_ONLY"
    UPDATE_THESIS = "UPDATE_THESIS"
    TRIGGER_RE_EVALUATION = "TRIGGER_RE_EVALUATION"
    MARKET_SHOCK = "MARKET_SHOCK"


class ThesisRelation(str, Enum):
    CONFLICTS = "CONFLICTS"
    REINFORCES = "REINFORCES"
    NEUTRAL = "NEUTRAL"


class CalendarStage(str, Enum):
    SCHEDULED = "SCHEDULED"
    WATCHING_24H = "WATCHING_24H"
    MONITORING_1H = "MONITORING_1H"
    BASELINE_5M = "BASELINE_5M"
    RELEASED_T0 = "RELEASED_T0"
    REACTION_1M = "REACTION_1M"
    TRANSMISSION_5M = "TRANSMISSION_5M"
    REEVALUATION_15M = "REEVALUATION_15M"
    CONFIRMED_30M = "CONFIRMED_30M"
    COMPLETED = "COMPLETED"


class ThesisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


@dataclass
class SentinelEvent:
    event_id: str
    category: EventCategory
    source: str
    title: str
    description: str
    raw_payload_hash: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_data: Dict[str, Any] = field(default_factory=dict)
    is_scheduled_calendar: bool = False
    scheduled_event_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category": self.category.value if isinstance(self.category, EventCategory) else str(self.category),
            "source": self.source,
            "title": self.title,
            "description": self.description,
            "raw_payload_hash": self.raw_payload_hash,
            "timestamp": self.timestamp,
            "event_data": self.event_data,
            "is_scheduled_calendar": self.is_scheduled_calendar,
            "scheduled_event_code": self.scheduled_event_code,
        }

    @staticmethod
    def generate_hash(content: str) -> str:
        return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()


@dataclass
class EventImpactAssessment:
    event_id: str
    importance_score: float                # 0.0 to 100.0
    india_relevance: str                   # HIGH | MEDIUM | LOW
    novelty: str                           # HIGH | MEDIUM | LOW
    market_reaction_score: float           # 0.0 to 100.0
    thesis_relation: ThesisRelation
    verdict: TriggerVerdict
    reasoning: str
    assessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "importance_score": round(self.importance_score, 2),
            "india_relevance": self.india_relevance,
            "novelty": self.novelty,
            "market_reaction_score": round(self.market_reaction_score, 2),
            "thesis_relation": self.thesis_relation.value if isinstance(self.thesis_relation, ThesisRelation) else str(self.thesis_relation),
            "verdict": self.verdict.value if isinstance(self.verdict, TriggerVerdict) else str(self.verdict),
            "reasoning": self.reasoning,
            "assessed_at": self.assessed_at,
        }


@dataclass
class ThesisRevision:
    thesis_id: str
    thesis_revision: int
    parent_thesis_id: str
    event_id: str
    adjustment_reason: str
    confidence_delta: float
    expected_move_delta: float
    volatility_regime: str
    risk_multiplier: float
    stop_multiplier: float
    before_state: Dict[str, Any]
    after_state: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thesis_id": self.thesis_id,
            "thesis_revision": self.thesis_revision,
            "parent_thesis_id": self.parent_thesis_id,
            "event_id": self.event_id,
            "adjustment_reason": self.adjustment_reason,
            "confidence_delta": round(self.confidence_delta, 2),
            "expected_move_delta": round(self.expected_move_delta, 2),
            "volatility_regime": self.volatility_regime,
            "risk_multiplier": round(self.risk_multiplier, 3),
            "stop_multiplier": round(self.stop_multiplier, 3),
            "before_state": self.before_state,
            "after_state": self.after_state,
            "created_at": self.created_at,
        }


@dataclass
class ActiveThesis:
    thesis_id: str
    revision: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    bias: str = "NEUTRAL"                 # BULLISH | BEARISH | NEUTRAL
    confidence: float = 50.0
    expected_move: float = 0.0
    valid_until: str = ""
    invalidation_conditions: List[str] = field(default_factory=list)
    last_material_event_id: Optional[str] = None
    status: ThesisStatus = ThesisStatus.ACTIVE
    volatility_regime: str = "NORMAL"
    risk_multiplier: float = 1.0
    stop_multiplier: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thesis_id": self.thesis_id,
            "revision": self.revision,
            "created_at": self.created_at,
            "bias": self.bias,
            "confidence": round(self.confidence, 2),
            "expected_move": round(self.expected_move, 2),
            "valid_until": self.valid_until,
            "invalidation_conditions": self.invalidation_conditions,
            "last_material_event_id": self.last_material_event_id,
            "status": self.status.value if isinstance(self.status, ThesisStatus) else str(self.status),
            "volatility_regime": self.volatility_regime,
            "risk_multiplier": round(self.risk_multiplier, 3),
            "stop_multiplier": round(self.stop_multiplier, 3),
        }


@dataclass
class EventCoverageReport:
    date: str
    # 1. Scheduled High-Impact Coverage
    scheduled_expected: int
    scheduled_detected: int
    scheduled_coverage_pct: float
    # 2. Source Ingestion Coverage
    source_available: int
    source_processed: int
    source_coverage_pct: float
    # 3. Material Processing Coverage
    material_detected: int
    material_processed: int
    material_processing_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "scheduled_expected": self.scheduled_expected,
            "scheduled_detected": self.scheduled_detected,
            "scheduled_coverage_pct": round(self.scheduled_coverage_pct, 2),
            "source_available": self.source_available,
            "source_processed": self.source_processed,
            "source_coverage_pct": round(self.source_coverage_pct, 2),
            "material_detected": self.material_detected,
            "material_processed": self.material_processed,
            "material_processing_pct": round(self.material_processing_pct, 2),
        }


@dataclass
class SentinelInvocationRecord:
    scheduled_invocation_id: str
    sentinel_invocation_id: str
    started_at: str
    completed_at: str
    sources_checked: int
    events_seen: int
    events_new: int
    events_duplicate: int
    events_material: int
    events_triggered: int
    status: str                          # SUCCESS | DEGRADED | FAILED
    error: Optional[str] = None
    lineage: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

