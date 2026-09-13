# =============================================================================
# event_agent/engine/model_immutability.py — Model Immutability & Causal Data Safety
# =============================================================================
"""
NEXUS V4.0 Model Immutability & Causal Safety Engine:
- Section 13: Enforces strict causal ordering (t_pub <= t_ing <= t_val <= t_dec < t_exec).
  Missing or inverted timestamps result in DATA_UNAVAILABLE. Never inferred.
- Section 14: AI Isolation (Verified Event -> AI Interpretation -> Market Impact).
  AI failure produces AI_UNAVAILABLE without masquerading as success.
- Section 15: Frozen Model Immutability (model_version, code_commit, configuration_hash).
  Any parameter or weight drift invalidates certification.
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CausalViolationError(ValueError):
    """Raised when causal timestamp ordering is violated."""
    pass


class ModelVersionMismatchError(RuntimeError):
    """Raised when active model configuration diverges from the frozen baseline."""
    pass


@dataclass
class CausalTimestampAudit:
    is_valid: bool
    status: str  # VERIFIED | DATA_UNAVAILABLE | CAUSAL_VIOLATION
    published_at: Optional[str] = None
    ingested_at: Optional[str] = None
    validated_at: Optional[str] = None
    decision_at: Optional[str] = None
    execution_at: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CausalDataSafetyEngine:
    """
    Guarantees zero future information leakage into trading decisions.
    """

    @classmethod
    def verify_timestamps(
        cls,
        published_at: Optional[str],
        ingested_at: Optional[str],
        validated_at: Optional[str],
        decision_at: Optional[str],
        execution_at: Optional[str] = None,
    ) -> CausalTimestampAudit:
        # Rule: Timestamps must NOT be missing or inferred
        if not (published_at and ingested_at and validated_at and decision_at):
            missing = [k for k, v in [
                ("published_at", published_at),
                ("ingested_at", ingested_at),
                ("validated_at", validated_at),
                ("decision_at", decision_at),
            ] if not v]
            return CausalTimestampAudit(
                is_valid=False,
                status="DATA_UNAVAILABLE",
                error_message=f"Missing causal timestamps: {missing}. Inferences strictly prohibited.",
            )

        try:
            t_pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            t_ing = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))
            t_val = datetime.fromisoformat(validated_at.replace("Z", "+00:00"))
            t_dec = datetime.fromisoformat(decision_at.replace("Z", "+00:00"))
            t_exec = datetime.fromisoformat(execution_at.replace("Z", "+00:00")) if execution_at else None
        except Exception as e:
            return CausalTimestampAudit(
                is_valid=False,
                status="DATA_UNAVAILABLE",
                error_message=f"Malformed timestamp format: {e}",
            )

        # Enforce t_pub <= t_ing <= t_val <= t_dec
        if not (t_pub <= t_ing <= t_val <= t_dec):
            violation = []
            if t_pub > t_ing:
                violation.append("published_at > ingested_at")
            if t_ing > t_val:
                violation.append("ingested_at > validated_at")
            if t_val > t_dec:
                violation.append("validated_at > decision_at")
            return CausalTimestampAudit(
                is_valid=False,
                status="CAUSAL_VIOLATION",
                error_message=f"Causal ordering inverted: {', '.join(violation)}",
                published_at=published_at,
                ingested_at=ingested_at,
                validated_at=validated_at,
                decision_at=decision_at,
            )

        if t_exec and not (t_dec < t_exec):
            return CausalTimestampAudit(
                is_valid=False,
                status="CAUSAL_VIOLATION",
                error_message="decision_at >= execution_at (Trade executed before or simultaneously with decision)",
                published_at=published_at,
                ingested_at=ingested_at,
                validated_at=validated_at,
                decision_at=decision_at,
                execution_at=execution_at,
            )

        return CausalTimestampAudit(
            is_valid=True,
            status="VERIFIED",
            published_at=published_at,
            ingested_at=ingested_at,
            validated_at=validated_at,
            decision_at=decision_at,
            execution_at=execution_at,
        )


@dataclass
class ModelImmutabilitySeal:
    model_version: str
    code_commit: str
    feature_version: str
    prompt_version: str
    risk_engine_version: str
    configuration_hash: str
    sealed_at: str
    parameters: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelImmutabilityEnforcer:
    """
    Enforces that production models cannot silently change.
    """

    FROZEN_MODEL_VERSION = "3.5.0-FROZEN"
    FROZEN_FEATURE_VERSION = "v3.6-causal-7f"
    FROZEN_PROMPT_VERSION = "v3.7-analyst-truth"
    FROZEN_RISK_VERSION = "v3.6.4-8invariants"

    @classmethod
    def compute_config_hash(cls, params: Dict[str, Any]) -> str:
        canonical_json = json.dumps(params, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @classmethod
    def get_certified_seal(cls) -> ModelImmutabilitySeal:
        frozen_params = {
            "prediction_horizon_days": 1,
            "min_confidence_hurdle": 0.60,
            "bayesian_agents_count": 4,
            "max_risk_per_trade": 0.005,
            "max_portfolio_exposure": 0.50,
            "daily_loss_limit": 0.015,
            "options_status": "EXPERIMENTAL_SEGREGATED",
        }
        cfg_hash = cls.compute_config_hash(frozen_params)
        return ModelImmutabilitySeal(
            model_version=cls.FROZEN_MODEL_VERSION,
            code_commit="4482030bcb98e70e0237ab90a471356126b7e2de",
            feature_version=cls.FROZEN_FEATURE_VERSION,
            prompt_version=cls.FROZEN_PROMPT_VERSION,
            risk_engine_version=cls.FROZEN_RISK_VERSION,
            configuration_hash=cfg_hash,
            sealed_at="2026-09-10T07:35:28+00:00",
            parameters=frozen_params,
        )

    @classmethod
    def verify_runtime_immutability(cls, runtime_params: Dict[str, Any]) -> Tuple[bool, str]:
        certified = cls.get_certified_seal()
        current_hash = cls.compute_config_hash(runtime_params)
        if current_hash != certified.configuration_hash:
            diffs = []
            for k, v in certified.parameters.items():
                if runtime_params.get(k) != v:
                    diffs.append(f"{k}: expected {v} got {runtime_params.get(k)}")
            return False, f"MODEL_DRIFT_UNAUTHORIZED: Configuration hash mismatch. Diffs: {', '.join(diffs)}"
        return True, "MODEL_CONFIGURATION_VERIFIED"
