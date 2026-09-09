# =============================================================================
# event_agent/prediction/agent_independence.py — Agent Independence & Collinearity
# =============================================================================
"""
V3.5 Agent Independence Analysis Engine.
Quantifies whether the 5 agents (Alpha, Momentum, Macro, Defensive, Contrarian)
provide genuine independent information or exhibit collinear herd behavior.
Computes correlation matrices, pairwise agreement/disagreement rates, and
unique incremental alpha when diverging from consensus.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

AGENTS = ["Alpha", "Momentum", "Macro", "Defensive", "Contrarian"]


@dataclass
class IndependenceReport:
    agent_names: List[str]
    prediction_correlation_matrix: Dict[str, Dict[str, float]]
    agreement_matrix: Dict[str, Dict[str, float]]
    disagreement_matrix: Dict[str, Dict[str, float]]
    unique_contribution_scores: Dict[str, float]
    collinearity_warning: bool
    collinear_pairs: List[Tuple[str, str, float]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_names": self.agent_names,
            "prediction_correlation_matrix": self.prediction_correlation_matrix,
            "agreement_matrix": self.agreement_matrix,
            "disagreement_matrix": self.disagreement_matrix,
            "unique_contribution_scores": self.unique_contribution_scores,
            "collinearity_warning": self.collinearity_warning,
            "collinear_pairs": [
                {"agent_a": a, "agent_b": b, "correlation": round(c, 3)}
                for a, b, c in self.collinear_pairs
            ],
        }


class AgentIndependenceEngine:
    """
    Evaluates multi-agent voting records for statistical independence.
    """

    @classmethod
    def analyze_independence(
        cls,
        agent_prediction_series: Dict[str, List[Dict[str, Any]]],
        actual_outcomes: Optional[List[int]] = None,
    ) -> IndependenceReport:
        """
        agent_prediction_series: Dict mapping agent_name -> list of prediction dicts:
            [{"direction": "UP", "expected_return": 0.012, "confidence": 65}, ...]
        """
        names = [name for name in AGENTS if name in agent_prediction_series]
        if len(names) < 2:
            return IndependenceReport(
                agent_names=names,
                prediction_correlation_matrix={},
                agreement_matrix={},
                disagreement_matrix={},
                unique_contribution_scores={},
                collinearity_warning=False,
                collinear_pairs=[],
            )

        n_samples = len(agent_prediction_series[names[0]])

        # Convert directions to numeric signals: UP = +1, DOWN = -1, NEUTRAL = 0
        signals = {}
        for name in names:
            arr = []
            for p in agent_prediction_series[name][:n_samples]:
                d = str(p.get("direction", "NEUTRAL")).upper()
                arr.append(1.0 if d == "UP" else (-1.0 if d == "DOWN" else 0.0))
            signals[name] = np.array(arr)

        corr_matrix: Dict[str, Dict[str, float]] = {a: {} for a in names}
        agree_matrix: Dict[str, Dict[str, float]] = {a: {} for a in names}
        disagree_matrix: Dict[str, Dict[str, float]] = {a: {} for a in names}

        collinear_pairs = []

        for i, a1 in enumerate(names):
            for j, a2 in enumerate(names):
                s1 = signals[a1]
                s2 = signals[a2]

                if i == j:
                    corr = 1.0
                    agr = 1.0
                else:
                    std1 = np.std(s1)
                    std2 = np.std(s2)
                    if std1 > 1e-6 and std2 > 1e-6:
                        corr = float(np.corrcoef(s1, s2)[0, 1])
                    else:
                        corr = 0.0

                    agr = float(np.mean(s1 == s2))

                    if j > i and corr > 0.80:
                        collinear_pairs.append((a1, a2, round(corr, 3)))

                corr_matrix[a1][a2] = round(corr, 3)
                agree_matrix[a1][a2] = round(agr, 3)
                disagree_matrix[a1][a2] = round(1.0 - agr, 3)

        # Unique Contribution when dissenting
        unique_scores: Dict[str, float] = {}
        if actual_outcomes and len(actual_outcomes) == n_samples:
            outs = np.array(actual_outcomes)
            for name in names:
                my_sig = signals[name]
                # Consensus of other agents
                others = [signals[o] for o in names if o != name]
                consensus = np.sign(sum(others))

                # Identify divergence cases where this agent disagreed with consensus
                divergent_idx = np.where((my_sig != consensus) & (consensus != 0))[0]
                if len(divergent_idx) >= 5:
                    # How often was this agent right when dissenting?
                    wins = np.sum((my_sig[divergent_idx] > 0) == (outs[divergent_idx] == 1))
                    dissent_win_rate = float(wins / len(divergent_idx))
                else:
                    dissent_win_rate = 0.50
                unique_scores[name] = round(dissent_win_rate * 100, 1)
        else:
            unique_scores = {name: 50.0 for name in names}

        return IndependenceReport(
            agent_names=names,
            prediction_correlation_matrix=corr_matrix,
            agreement_matrix=agree_matrix,
            disagreement_matrix=disagree_matrix,
            unique_contribution_scores=unique_scores,
            collinearity_warning=(len(collinear_pairs) > 0),
            collinear_pairs=collinear_pairs,
        )
