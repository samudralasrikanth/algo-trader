# =============================================================================
# event_agent/arena/models.py — V3.2 Arena Domain Models & Data Structures
# =============================================================================
"""
Core domain models for the 5-Agent Nifty 50 AI Trading Arena:
- Instruments (Equity, Futures, Options) with simulation disclaimers
- Actions including NO_TRADE as a first-class citizen
- Immutable ProposedTrade with collision-proof deterministic Trade ID
- RiskEvaluation and AgentProfile with frozen strategy versioning
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from .asset_models import (
    AssetClass,
    StrategyType,
    LegSide,
    StrategyStatus,
    EquityInstrument,
    MutualFundInstrument,
    FutureInstrument,
    OptionInstrument,
    CommodityInstrument,
    StrategyLeg,
    MultiLegStrategy,
    OptionStrikeData,
    OptionChain,
)



class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    FUTURE = "FUTURE"
    OPTION = "OPTION"


class OptionType(str, Enum):
    CE = "CE"       # Call Option
    PE = "PE"       # Put Option
    NONE = "NONE"


class TradeDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderIntent(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class HedgeDecision(str, Enum):
    YES = "YES"
    NO = "NO"
    NO_HEDGE = "NO"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


@dataclass
class Instrument:
    """
    Financial instrument contract model.
    Derivatives are explicitly flagged with is_simulated_price for transparency.
    """
    underlying: str
    instrument_type: InstrumentType
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: OptionType = OptionType.NONE
    contract_name: Optional[str] = None
    lot_size: int = 1
    option_premium: Optional[float] = None
    is_simulated_price: bool = False
    pricing_model: str = "MARKET"

    is_valid_contract: bool = True

    def __post_init__(self):
        if not self.contract_name:
            if self.instrument_type == InstrumentType.EQUITY:
                self.contract_name = f"{self.underlying}-EQ"
            elif self.instrument_type == InstrumentType.FUTURE:
                self.contract_name = f"{self.underlying}-FUT-{self.expiry or 'NEAR'}"
                self.is_simulated_price = True
                self.pricing_model = "COST_OF_CARRY"
            elif self.instrument_type == InstrumentType.OPTION:
                if self.strike and self.option_type != OptionType.NONE:
                    self.contract_name = f"{self.underlying}-OPT-{self.strike}-{self.option_type.value}-{self.expiry or 'NEAR'}"
                else:
                    self.contract_name = f"{self.underlying}-OPT-MALFORMED"
                self.is_simulated_price = True
                self.pricing_model = "BLACK_SCHOLES_VIX_PROXY"

        if self.instrument_type == InstrumentType.OPTION:
            is_valid, _ = self.validate_option_contract()
            self.is_valid_contract = is_valid

    def validate_option_contract(self) -> Tuple[bool, List[str]]:
        """
        Validates that an OPTION instrument possesses all mandatory contract metadata:
        underlying_symbol, strike, expiry, call_put (option_type), and contract_name.
        """
        errors = []
        if not self.underlying:
            errors.append("underlying_symbol is missing")
        if self.strike is None or self.strike <= 0:
            errors.append("strike is missing or <= 0")
        if not self.expiry or str(self.expiry).strip() in ("", "None"):
            errors.append("expiry is missing")
        if not self.option_type or self.option_type in (OptionType.NONE, "NONE"):
            errors.append("option_type (call_put) is missing")
        if not self.contract_name or "MALFORMED" in self.contract_name:
            errors.append("option_symbol / contract identifier is missing")
        return len(errors) == 0, errors

    @property
    def is_trade_eligible(self) -> bool:
        """
        Checks whether the instrument is trade-eligible.
        Malformed OPTION records without contract metadata are strictly NOT trade-eligible.
        """
        if self.instrument_type == InstrumentType.OPTION:
            return self.is_valid_contract
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "underlying": self.underlying,
            "instrument_type": self.instrument_type.value,
            "expiry": self.expiry,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "contract_name": self.contract_name,
            "lot_size": self.lot_size,
            "option_premium": self.option_premium,
            "is_simulated_price": self.is_simulated_price,
            "pricing_model": self.pricing_model,
            "is_valid_contract": self.is_valid_contract,
            "is_trade_eligible": self.is_trade_eligible,
        }


@dataclass
class ProposedTrade:
    @classmethod
    def create_simple(
        cls,
        agent_id: str,
        symbol: str,
        action: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        target: float,
        confidence: float = 70.0,
        strategy_version: str = "V1",
        sequence: int = 1,
        instrument_type: InstrumentType = InstrumentType.EQUITY,
    ) -> "ProposedTrade":
        dir_val = TradeDirection.BUY if action.upper() == "BUY" else TradeDirection.SELL
        act_val = TradeAction.BUY if action.upper() == "BUY" else TradeAction.SELL
        inst = Instrument(underlying=symbol, instrument_type=instrument_type)
        return cls(
            agent_id=agent_id,
            strategy_version=strategy_version,
            symbol=symbol,
            action=act_val,
            instrument=inst,
            direction=dir_val,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            confidence=confidence,
            expected_move_pct=round(((target - entry_price) / entry_price) * 100.0, 2) if entry_price > 0 else 1.0,
            planned_risk_amount=abs(entry_price - stop_loss) * quantity,
            hedge_decision=HedgeDecision.NO_HEDGE,
            sequence=sequence,
        )

    """
    Structured proposal generated by an agent.
    Includes explicit strategy version, reason, optional hedge, and deterministic trade ID.
    """
    agent_id: str
    strategy_version: str
    symbol: str
    action: TradeAction
    instrument: Instrument
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    target: float
    confidence: float
    expected_move_pct: float
    planned_risk_amount: float
    hedge_decision: HedgeDecision
    hedge_instrument: Optional[str] = None
    decision_reason: str = ""
    snapshot_id: str = ""
    sequence: int = 1
    strategy: Optional[MultiLegStrategy] = None
    thesis: str = ""
    evidence: List[str] = field(default_factory=list)
    horizon: str = "1D"
    expected_return: float = 0.0
    position_side: PositionSide = PositionSide.LONG
    order_action: TradeAction = TradeAction.BUY
    order_intent: OrderIntent = OrderIntent.OPEN
    execution_edge: Optional[float] = None
    shadow_adjusted_edge: Optional[float] = None
    fundamental_adj: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.order_action == TradeAction.BUY and self.action != TradeAction.BUY:
            self.order_action = self.action
        if self.action == TradeAction.SELL and self.direction == TradeDirection.SELL:
            self.position_side = PositionSide.SHORT
            self.order_action = TradeAction.SELL
            self.order_intent = OrderIntent.OPEN

    def generate_trade_id(self, market_date: str) -> str:
        """
        Collision-proof deterministic Trade ID incorporating snapshot, sequence and hash.
        """
        payload = f"{self.snapshot_id}:{self.action.value}:{self.position_side.value}:{self.order_intent.value}:{self.sequence}:{self.symbol}:{self.instrument.instrument_type.value}".encode()
        h = hashlib.sha256(payload).hexdigest()[:8]
        sym_clean = self.symbol.replace(".NS", "").replace("^", "")
        return f"TRD-{market_date}-{self.agent_id}-{sym_clean}-{self.instrument.instrument_type.value}-{self.sequence}-{h}"

    @property
    def is_trade_eligible(self) -> bool:
        if self.action in (TradeAction.NO_TRADE, TradeAction.HOLD):
            return False
        if not self.instrument.is_trade_eligible:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "is_trade_eligible": self.is_trade_eligible,
            "agent_id": self.agent_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "action": self.action.value,
            "position_side": self.position_side.value,
            "order_action": self.order_action.value,
            "order_intent": self.order_intent.value,
            "instrument": self.instrument.to_dict(),
            "direction": self.direction.value,
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target": round(self.target, 2),
            "confidence": round(self.confidence, 1),
            "expected_move_pct": round(self.expected_move_pct, 2),
            "planned_risk_amount": round(self.planned_risk_amount, 2),
            "hedge_decision": self.hedge_decision.value,
            "hedge_instrument": self.hedge_instrument,
            "decision_reason": self.decision_reason,
            "snapshot_id": self.snapshot_id,
            "sequence": self.sequence,
            "strategy": self.strategy.to_dict() if self.strategy else None,
            "thesis": self.thesis or self.decision_reason,
            "evidence": self.evidence,
            "horizon": self.horizon,
            "expected_return": self.expected_return or self.expected_move_pct,
            "execution_edge": round(self.execution_edge, 4) if self.execution_edge is not None else None,
            "shadow_adjusted_edge": round(self.shadow_adjusted_edge, 4) if self.shadow_adjusted_edge is not None else None,
            "fundamental_adj": round(self.fundamental_adj, 4),
            "timestamp": self.timestamp,
        }
        return d


@dataclass
class RiskEvaluation:
    """
    Evaluation output from Central Risk Engine.
    """
    is_approved: bool
    rejection_reason: str = "APPROVED"
    adjusted_quantity: int = 0
    max_loss: float = 0.0
    risk_reward_ratio: float = 0.0
    checks_passed: List[str] = field(default_factory=list)
    risk_score: float = 0.0

    @property
    def approved(self) -> bool:
        return self.is_approved

    @property
    def maximum_allowed_quantity(self) -> int:
        return self.adjusted_quantity

    @property
    def checks(self) -> List[str]:
        return self.checks_passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_approved": self.is_approved,
            "approved": self.is_approved,
            "rejection_reason": self.rejection_reason,
            "adjusted_quantity": self.adjusted_quantity,
            "maximum_allowed_quantity": self.adjusted_quantity,
            "max_loss": round(self.max_loss, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "checks_passed": self.checks_passed,
            "checks": self.checks_passed,
            "risk_score": round(self.risk_score, 2),
        }


@dataclass
class AgentProfile:
    """
    Agent metadata and strategy identity.
    """
    id: str
    name: str
    title: str
    personality_quote: str
    strategy_version: str
    strategy_description: str
    starting_capital: float = 20_00_000.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "personality_quote": self.personality_quote,
            "strategy_version": self.strategy_version,
            "strategy_description": self.strategy_description,
            "starting_capital": self.starting_capital,
        }
