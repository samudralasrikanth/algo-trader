# =============================================================================
# event_agent/prediction/deterministic_replay.py — Deterministic Replay Validator
# =============================================================================
"""
V3.5 Deterministic Replay Engine.
Given historical snapshots (market state, event record, model version, and config),
proves that re-executing the prediction pipeline produces exact bitwise identical
decisions and cryptographic hash verification.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ReplayVerificationResult:
    prediction_id: str
    original_hash: str
    replayed_hash: str
    is_bitwise_identical: bool
    agent_decisions_match: bool
    ensemble_decision_matches: bool
    risk_decision_matches: bool
    discrepancies: List[str]


class DeterministicReplayValidator:
    """
    Validates bitwise reproducibility of historical predictions from locked snapshots.
    """

    @classmethod
    def compute_decision_hash(
        cls,
        market_snapshot: Dict[str, Any],
        event_snapshot: Dict[str, Any],
        model_version: str,
        config: Dict[str, Any],
        agent_decisions: Dict[str, Any],
        ensemble_decision: Dict[str, Any],
        risk_decision: Dict[str, Any],
    ) -> str:
        """
        Computes SHA-256 digest over all decision components.
        """
        canonical_str = (
            f"MODEL:{model_version}|"
            f"MKT:{json.dumps(market_snapshot, sort_keys=True)}|"
            f"EVT:{json.dumps(event_snapshot, sort_keys=True)}|"
            f"CFG:{json.dumps(config, sort_keys=True)}|"
            f"AGENTS:{json.dumps(agent_decisions, sort_keys=True)}|"
            f"ENS:{json.dumps(ensemble_decision, sort_keys=True)}|"
            f"RISK:{json.dumps(risk_decision, sort_keys=True)}"
        )
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    @classmethod
    def verify_replay(
        cls,
        prediction_id: str,
        original_hash: str,
        market_snapshot: Dict[str, Any],
        event_snapshot: Dict[str, Any],
        model_version: str,
        config: Dict[str, Any],
        replayed_agent_decisions: Dict[str, Any],
        replayed_ensemble_decision: Dict[str, Any],
        replayed_risk_decision: Dict[str, Any],
        original_agent_decisions: Dict[str, Any],
        original_ensemble_decision: Dict[str, Any],
        original_risk_decision: Dict[str, Any],
    ) -> ReplayVerificationResult:
        """
        Compare replayed decisions against original locked decisions.
        """
        replayed_hash = cls.compute_decision_hash(
            market_snapshot=market_snapshot,
            event_snapshot=event_snapshot,
            model_version=model_version,
            config=config,
            agent_decisions=replayed_agent_decisions,
            ensemble_decision=replayed_ensemble_decision,
            risk_decision=replayed_risk_decision,
        )

        discrepancies = []

        agents_match = (replayed_agent_decisions == original_agent_decisions)
        if not agents_match:
            discrepancies.append("Agent voting decisions diverged from original snapshot.")

        ens_match = (replayed_ensemble_decision == original_ensemble_decision)
        if not ens_match:
            discrepancies.append("Ensemble consensus diverged from original snapshot.")

        risk_match = (replayed_risk_decision == original_risk_decision)
        if not risk_match:
            discrepancies.append("Risk engine sizing/invariants diverged from original snapshot.")

        hash_match = (original_hash == replayed_hash)
        if not hash_match:
            discrepancies.append(f"Cryptographic hash mismatch (orig: {original_hash[:8]}, replayed: {replayed_hash[:8]}).")

        return ReplayVerificationResult(
            prediction_id=prediction_id,
            original_hash=original_hash,
            replayed_hash=replayed_hash,
            is_bitwise_identical=(len(discrepancies) == 0),
            agent_decisions_match=agents_match,
            ensemble_decision_matches=ens_match,
            risk_decision_matches=risk_match,
            discrepancies=discrepancies,
        )
