# =============================================================================
# event_agent/sentinel/event_deduplicator.py — Event Deduplication Engine
# =============================================================================
"""
V4.2.1 Event Deduplication Engine:
- Uses SHA-256 canonical hashing + token Jaccard similarity.
- 24-hour sliding window prevents duplicate news echoes from re-triggering intelligence.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import re
from typing import Dict, List, Optional, Set, Tuple


class EventDeduplicator:
    """
    Maintains seen event hashes and detects semantic duplicate echoes.
    """

    def __init__(self, jaccard_threshold: float = 0.70, window_hours: int = 24, similarity_threshold: Optional[float] = None):
        self.seen_hashes: Dict[str, datetime] = {}  # hash -> first_seen
        self.seen_token_sets: List[Tuple[Set[str], datetime]] = []
        self.jaccard_threshold = similarity_threshold if similarity_threshold is not None else jaccard_threshold
        self.window_hours = window_hours

    @staticmethod
    def canonical_hash(title: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", title.lower())
        tokens = " ".join(sorted(clean.split()))
        return hashlib.sha256(tokens.encode("utf-8")).hexdigest()

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        t = text.lower()
        t = re.sub(r"\bfederal\s+reserve\b", "fed", t)
        t = re.sub(r"\bbasis\s+points\b", "bps", t)
        t = re.sub(r"\binterest\s+rates?\b", "rate", t)
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", t)
        return {w for w in clean.split() if len(w) > 2}

    def is_duplicate(self, title: str, timestamp: Optional[datetime] = None) -> bool:
        now = timestamp or datetime.now(timezone.utc)
        self._prune_old(now)

        h = self.canonical_hash(title)
        if h in self.seen_hashes:
            return True

        tokens = self._tokenize(title)
        for seen_set, _ in self.seen_token_sets:
            if not seen_set or not tokens:
                continue
            intersection = len(tokens.intersection(seen_set))
            union = len(tokens.union(seen_set))
            if union > 0 and (intersection / union) >= self.jaccard_threshold:
                return True

        # Register as new seen event
        self.seen_hashes[h] = now
        self.seen_token_sets.append((tokens, now))
        return False

    def _prune_old(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=24)
        self.seen_hashes = {k: v for k, v in self.seen_hashes.items() if v >= cutoff}
        self.seen_token_sets = [item for item in self.seen_token_sets if item[1] >= cutoff]
