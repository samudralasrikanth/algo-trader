# =============================================================================
# event_agent/research/model_versioning.py — Model Versioning & Governance
# =============================================================================
"""
Manages model versioning, feature versions, regime versions, calibration versions,
and weights governance with a strict approval gate.

Crucial Rule (Review Point #13 & #5):
- Live production weights and model versions are NEVER auto-updated by the learning loop.
- Updates must traverse: Candidate -> Walk-Forward OOS Validation -> Approval Gate -> Production.
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BASELINE VERSION RECORD (Frozen Production Baseline V3.0)
# ---------------------------------------------------------------------------
VERSION_RECORD: Dict[str, Any] = {
    "model_version": "3.0.0",
    "feature_version": "F1",
    "regime_version": "R1",
    "calibration_version": "C1",
    "weights_version": "W1.0",
    "data_snapshot_id": "SNAP-20260909-2030",
    "created_at": "2026-09-09T20:30:00+05:30",
    "description": "Initial v3 release with 8-dim regime + normalized surprises",
}


class ApprovalGateError(PermissionError):
    """Raised when an automated script attempts to update model weights without human approval."""
    pass


@dataclass(frozen=True)
class ModelVersion:
    """Immutable model version descriptor."""
    model_version: str = "3.0.0"
    feature_version: str = "F1"
    regime_version: str = "R1"
    calibration_version: str = "C1"
    weights_version: str = "W1.0"
    data_snapshot_id: str = "SNAP-20260909-2030"
    created_at: str = "2026-09-09T20:30:00+05:30"
    description: str = "Initial v3 release with 8-dim regime + normalized surprises"
    is_production: bool = True
    approved_by: Optional[str] = "SYSTEM_INITIAL_V3"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def version_hash(self) -> str:
        """Deterministic cryptographic hash representing this configuration."""
        canonical = json.dumps(
            {
                "model_version": self.model_version,
                "feature_version": self.feature_version,
                "regime_version": self.regime_version,
                "calibration_version": self.calibration_version,
                "weights_version": self.weights_version,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# Singleton default active version
CURRENT_VERSION = ModelVersion()


class ModelVersionManager:
    """
    Manages active version tracking, snapshot ID generation,
    and enforces the learning loop approval gate.
    """

    _active_version: ModelVersion = CURRENT_VERSION
    _pending_proposals: Dict[str, Dict[str, Any]] = {}
    _version_history: List[Dict[str, Any]] = [VERSION_RECORD]

    @classmethod
    def get_current_version(cls) -> ModelVersion:
        return cls._active_version

    @classmethod
    def get_current_version_record(cls) -> Dict[str, Any]:
        rec = cls._active_version.to_dict()
        rec["version_hash"] = cls._active_version.version_hash
        return rec

    @classmethod
    def get_model_version(cls) -> str:
        return cls._active_version.model_version

    @classmethod
    def generate_snapshot_id(cls, prefix: str = "SNAP") -> str:
        """
        Generate a unique point-in-time snapshot ID.
        Format: SNAP-YYYYMMDD-HHMMSS
        """
        now = datetime.now(timezone.utc)
        return f"{prefix}-{now.strftime('%Y%m%d-%H%M%S')}"

    @classmethod
    def is_learning_loop_auto_update_allowed(cls) -> bool:
        """
        KILL SWITCH: Under no circumstances does the automated system
        auto-update production weights or version numbers without human gate.
        """
        return False

    @classmethod
    def propose_candidate_version(
        cls,
        candidate_weights: Dict[str, Any],
        oos_validation_results: Dict[str, Any],
        proposer: str = "LEARNING_LOOP",
        description: str = "",
    ) -> str:
        """
        Submit a new candidate weights/version for review after walk-forward validation.
        Does NOT update production! Returns a proposal_id.
        """
        proposal_id = f"PROP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        cls._pending_proposals[proposal_id] = {
            "proposal_id": proposal_id,
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "proposer": proposer,
            "description": description,
            "candidate_weights": candidate_weights,
            "oos_validation_results": oos_validation_results,
            "status": "PENDING_APPROVAL",
        }
        logger.info(f"Candidate version proposed: {proposal_id}. Awaiting human approval gate.")
        return proposal_id

    @classmethod
    def approve_candidate_version(
        cls,
        proposal_id: str,
        approver_token: str,
        approved_by: str,
        new_model_version: Optional[str] = None,
        new_weights_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Human approval gate. Requires explicit non-empty approver credentials.
        """
        if not approver_token or not approved_by or approved_by == "LEARNING_LOOP":
            raise ApprovalGateError(
                "Approval gate violation: Production model updates require explicit human approval."
            )

        proposal = cls._pending_proposals.get(proposal_id)
        if not proposal:
            raise KeyError(f"Proposal {proposal_id} not found.")

        # Version bump logic
        prev = cls._active_version
        now_iso = datetime.now(timezone.utc).isoformat()
        
        new_v = ModelVersion(
            model_version=new_model_version or prev.model_version,
            feature_version=prev.feature_version,
            regime_version=prev.regime_version,
            calibration_version=prev.calibration_version,
            weights_version=new_weights_version or f"W{float(prev.weights_version.replace('W','')) + 0.1:.1f}",
            data_snapshot_id=cls.generate_snapshot_id(),
            created_at=now_iso,
            description=f"Approved proposal {proposal_id}: {proposal['description']}",
            is_production=True,
            approved_by=approved_by,
        )

        cls._active_version = new_v
        proposal["status"] = "APPROVED"
        proposal["approved_by"] = approved_by
        proposal["approved_at"] = now_iso

        cls._version_history.append(new_v.to_dict())
        logger.warning(
            f"PRODUCTION MODEL VERSION BUMPED to {new_v.model_version} "
            f"(weights {new_v.weights_version}) by {approved_by}"
        )
        return new_v.to_dict()


def get_current_version_record() -> Dict[str, Any]:
    """Convenience accessor for current version record."""
    return ModelVersionManager.get_current_version_record()


def get_model_version() -> str:
    """Convenience accessor for model version string."""
    return ModelVersionManager.get_model_version()
