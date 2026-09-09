# =============================================================================
# event_agent/engine/event_intelligence.py — Structured Event Ingestion & Deduplication
# =============================================================================
"""
Provides structured event classification, triple-timestamp tracking,
and duplicate headline detection for news feeds and corporate filings.
"""

import hashlib
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class StructuredEvent:
    """Normalized financial event data structure."""
    event_id: str
    source: str
    published_at: str
    ingested_at: str
    headline: str
    affected_symbols: List[str]
    event_type: str
    sentiment: float
    severity: str
    expected_horizon: str
    investment_thesis: str
    catalyst_vs_noise: str = "CATALYST"
    surprise_vs_priced_in: str = "SURPRISE"
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventIntelligenceEngine:
    def ingest_news(self, headline: str, source: str = "news", published_at: Optional[str] = None) -> Dict[str, Any]:
        evt = self.process_raw_article(headline, source=source, published_at=published_at)
        if not hasattr(self, "_source_tracking"):
            self._source_tracking = {}
        target_id = evt.duplicate_of if evt.is_duplicate and evt.duplicate_of else evt.event_id
        if target_id not in self._source_tracking:
            self._source_tracking[target_id] = []
        if source not in self._source_tracking[target_id]:
            self._source_tracking[target_id].append(source)
        return {
            "event_id": target_id,
            "is_duplicate": evt.is_duplicate,
            "sources": self._source_tracking[target_id],
            "headline": evt.headline,
            "sentiment": evt.sentiment,
        }

    """
    Processes raw headlines, normalizes timestamps, detects duplicate news,
    and maps them to affected Nifty 50 symbols.
    """

    def __init__(self, similarity_threshold: float = 0.75):
        self.similarity_threshold = similarity_threshold
        self._seen_fingerprints: Dict[str, str] = {}  # token_set -> event_id
        self.processed_events: List[StructuredEvent] = []

    def _tokenize(self, text: str) -> Set[str]:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
        tokens = set(cleaned.split())
        stopwords = {"in", "on", "at", "to", "for", "of", "and", "the", "a", "an", "is", "by", "from", "nse", "stock", "share"}
        return tokens - stopwords

    def _jaccard_similarity(self, s1: Set[str], s2: Set[str]) -> float:
        if not s1 or not s2:
            return 0.0
        return len(s1.intersection(s2)) / len(s1.union(s2))

    def process_raw_article(
        self,
        headline: str,
        source: str = "Google News RSS",
        published_at: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> StructuredEvent:
        now_iso = datetime.now(timezone.utc).isoformat()
        pub_iso = published_at or now_iso

        tokens = self._tokenize(headline)
        is_dup = False
        dup_of = None

        for existing_id, existing_tokens in list(self._seen_fingerprints.items()):
            sim = self._jaccard_similarity(tokens, existing_tokens)
            if sim >= self.similarity_threshold:
                is_dup = True
                dup_of = existing_id
                break

        h_id = f"EVT-{hashlib.sha256(headline.encode('utf-8')).hexdigest()[:12]}"
        if not is_dup:
            self._seen_fingerprints[h_id] = tokens

        # Event classification rules
        hl_lower = headline.lower()
        if any(w in hl_lower for w in ["profit up", "surges", "jumps", "beat street", "beats estimate"]):
            ev_type = "EARNINGS_BEAT"
            sentiment = 0.65
            severity = "HIGH"
            thesis = "Earnings beat expected to drive multiple expansion."
        elif any(w in hl_lower for w in ["net loss", "drops", "slumps", "misses", "falls"]):
            ev_type = "EARNINGS_MISS"
            sentiment = -0.65
            severity = "HIGH"
            thesis = "Earnings miss expected to trigger margin and target downgrades."
        elif any(w in hl_lower for w in ["order win", "bags order", "secures deal", "wins contract"]):
            ev_type = "LARGE_ORDER_WIN"
            sentiment = 0.50
            severity = "MEDIUM"
            thesis = "Order inflow increases revenue visibility over multi-quarter horizon."
        elif any(w in hl_lower for w in ["sebi", "probe", "notice", "penalty", "fda", "warning letter"]):
            ev_type = "REGULATORY_ACTION"
            sentiment = -0.70
            severity = "CRITICAL"
            thesis = "Regulatory scrutiny raises governance and operational uncertainty."
        else:
            ev_type = "GENERAL_NEWS"
            sentiment = 0.10 if "buy" in hl_lower or "gain" in hl_lower else (-0.10 if "fall" in hl_lower else 0.0)
            severity = "LOW"
            thesis = "Routine corporate or market update."

        cat_noise = "NOISE" if severity == "LOW" else "CATALYST"
        affected = [symbol] if symbol else ["NIFTY50"]

        event = StructuredEvent(
            event_id=h_id,
            source=source,
            published_at=pub_iso,
            ingested_at=now_iso,
            headline=headline,
            affected_symbols=affected,
            event_type=ev_type,
            sentiment=round(sentiment, 2),
            severity=severity,
            expected_horizon="1_3_DAYS" if severity in ("HIGH", "CRITICAL") else "INTRADAY",
            investment_thesis=thesis,
            catalyst_vs_noise=cat_noise,
            surprise_vs_priced_in="SURPRISE",
            is_duplicate=is_dup,
            duplicate_of=dup_of,
        )
        self.processed_events.append(event)
        return event
