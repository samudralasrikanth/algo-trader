# =============================================================================
# event_agent/arena/agents/__init__.py — Strategy Agents Package
# =============================================================================

from typing import Dict
from .base_agent import BaseAgent
from .agent_alpha import AgentAlpha
from .agent_momentum import AgentMomentum
from .agent_macro import AgentMacro
from .agent_defensive import AgentDefensive
from .agent_contrarian import AgentContrarian

ALL_AGENT_CLASSES = [
    AgentAlpha,
    AgentMomentum,
    AgentMacro,
    AgentDefensive,
    AgentContrarian,
]


def create_all_agents() -> Dict[str, BaseAgent]:
    """Instantiate and return all 5 arena agents keyed by agent_id."""
    return {
        "ALPHA": AgentAlpha(),
        "MOMENTUM": AgentMomentum(),
        "MACRO": AgentMacro(),
        "DEFENSIVE": AgentDefensive(),
        "CONTRARIAN": AgentContrarian(),
    }
