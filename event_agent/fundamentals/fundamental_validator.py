# =============================================================================
# event_agent/fundamentals/fundamental_validator.py — Causal & Freshness Validator
# =============================================================================
"""
Enforces deterministic causal ordering and point-in-time freshness for fundamentals:
1. Invariant: fundamental_as_of <= decision_timestamp (strictly no future data).
2. Freshness categorization: FRESH (<=90d), ACCEPTABLE (91-180d), STALE (>180d), EXPIRED (>365d).
3. Data integrity validation: Checks for corrupted numbers, NaN/Inf, and provenance hash verification.
"""

from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from .fundamental_snapshot import FundamentalFreshness, FundamentalSnapshot

logger = logging.getLogger(__name__)


class FundamentalValidator:
    """
    Validates point-in-time causality, freshness, and structural integrity.
    """

    MAX_FRESH_DAYS: int = 90
    MAX_ACCEPTABLE_DAYS: int = 180
    MAX_STALE_DAYS: int = 365

    @classmethod
    def validate_snapshot(
        cls,
        snapshot: FundamentalSnapshot,
        decision_timestamp: Optional[datetime] = None,
    ) -> Tuple[bool, List[str], FundamentalSnapshot]:
        """
        Validates a FundamentalSnapshot against decision_timestamp.
        Returns: (is_valid, error_list, updated_snapshot)
        """
        errors: List[str] = []

        if not snapshot.is_available:
            return True, [], snapshot

        dec_ts = decision_timestamp or datetime.now(timezone.utc)
        as_of_ts = snapshot.as_of

        # Timezone harmonization
        if as_of_ts.tzinfo is None and dec_ts.tzinfo is not None:
            as_of_ts = as_of_ts.replace(tzinfo=timezone.utc)
        elif as_of_ts.tzinfo is not None and dec_ts.tzinfo is None:
            dec_ts = dec_ts.replace(tzinfo=timezone.utc)

        # 1. Causal Invariant Check: as_of <= decision_timestamp
        if as_of_ts > dec_ts:
            msg = f"CAUSAL_VIOLATION: Fundamental as_of ({as_of_ts.isoformat()}) is in future of decision_timestamp ({dec_ts.isoformat()})."
            errors.append(msg)
            logger.error(f"❌ {snapshot.symbol}: {msg}")
            # Mark unavailable/stale to prevent contaminated usage
            snapshot.freshness = FundamentalFreshness.EXPIRED.value
            return False, errors, snapshot

        # 2. Freshness Check
        age_days = (dec_ts - as_of_ts).total_seconds() / 86400.0
        if age_days <= cls.MAX_FRESH_DAYS:
            freshness = FundamentalFreshness.FRESH.value
        elif age_days <= cls.MAX_ACCEPTABLE_DAYS:
            freshness = FundamentalFreshness.ACCEPTABLE.value
        elif age_days <= cls.MAX_STALE_DAYS:
            freshness = FundamentalFreshness.STALE.value
        else:
            freshness = FundamentalFreshness.EXPIRED.value

        snapshot.freshness = freshness

        # 3. Numeric Sanity Check
        for category_name, cat_dict in [
            ("valuation", snapshot.valuation),
            ("profitability", snapshot.profitability),
            ("growth", snapshot.growth),
            ("leverage", snapshot.leverage),
            ("ownership", snapshot.ownership),
        ]:
            for k, val in cat_dict.items():
                if val is None or math.isnan(val) or math.isinf(val):
                    errors.append(f"Malformed numeric in {category_name}.{k}: {val}")

        # 4. Provenance Hash Integrity
        recomputed_hash = snapshot.compute_provenance_hash()
        if snapshot.provenance_hash and snapshot.provenance_hash != recomputed_hash:
            errors.append(f"PROVENANCE_MISMATCH: stored hash {snapshot.provenance_hash[:8]} != recomputed {recomputed_hash[:8]}")

        is_valid = (len(errors) == 0)
        return is_valid, errors, snapshot
