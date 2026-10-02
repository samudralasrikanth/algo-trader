# =============================================================================
# event_agent/arena/asset_models.py — Universal Multi-Asset & Strategy Models
# =============================================================================
"""
V3.3 Universal Asset & Strategy Models:
- AssetClass taxonomy: EQUITY, MUTUAL_FUND, FUTURE, OPTION, COMMODITY
- Base Instrument and specialized subclasses:
  EquityInstrument, MutualFundInstrument, FutureInstrument,
  OptionInstrument, CommodityInstrument
- MultiLegStrategy and StrategyLeg models
- OptionChain and OptionStrikeData models
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    MUTUAL_FUND = "MUTUAL_FUND"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    COMMODITY = "COMMODITY"


class StrategyType(str, Enum):
    EQUITY_DIRECTIONAL = "EQUITY_DIRECTIONAL"
    LONG_CALL = "LONG_CALL"
    LONG_PUT = "LONG_PUT"
    BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
    BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
    BULL_PUT_SPREAD = "BULL_PUT_SPREAD"
    BEAR_CALL_SPREAD = "BEAR_CALL_SPREAD"
    LONG_STRADDLE = "LONG_STRADDLE"
    LONG_STRANGLE = "LONG_STRANGLE"
    PROTECTIVE_PUT = "PROTECTIVE_PUT"
    FUTURES_DIRECTIONAL = "FUTURES_DIRECTIONAL"
    COMMODITY_DIRECTIONAL = "COMMODITY_DIRECTIONAL"


class OptionType(str, Enum):
    CE = "CE"       # Call European
    PE = "PE"       # Put European
    NONE = "NONE"


class LegSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class StrategyStatus(str, Enum):
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRY_DAY = "EXPIRY_DAY"
    STOPPED_OUT = "STOPPED_OUT"
    TARGET_REACHED = "TARGET_REACHED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


@dataclass
class InstrumentBase:
    """Base financial instrument across all asset classes."""
    instrument_id: str
    asset_class: AssetClass
    symbol: str
    name: str
    exchange: str = "NSE"
    currency: str = "INR"
    is_simulated_price: bool = False
    price_source: str = "MARKET"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "asset_class": self.asset_class.value,
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "currency": self.currency,
            "is_simulated_price": self.is_simulated_price,
            "price_source": self.price_source,
        }


@dataclass
class EquityInstrument(InstrumentBase):
    """Direct equity share."""
    sector: str = "General"
    beta: float = 1.0

    def __init__(self, symbol: str, name: str = "", sector: str = "General", beta: float = 1.0):
        inst_id = f"EQ-{symbol.replace('.NS', '')}"
        super().__init__(
            instrument_id=inst_id,
            asset_class=AssetClass.EQUITY,
            symbol=symbol,
            name=name or symbol.replace(".NS", ""),
            exchange="NSE",
            currency="INR",
            is_simulated_price=False,
            price_source="MARKET",
        )
        self.sector = sector
        self.beta = beta

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({"sector": self.sector, "beta": round(self.beta, 2)})
        return d


@dataclass
class MutualFundInstrument(InstrumentBase):
    """
    Mutual fund scheme model.
    V3.3 Architecture & UI ready. No autonomous trading until approved NAV feed exists.
    """
    scheme_code: str = ""
    amc: str = ""
    category: str = "Large Cap"
    nav: float = 0.0
    aum_cr: float = 0.0
    expense_ratio: float = 0.0
    benchmark: str = "NIFTY 50 TRI"
    risk_level: str = "VERY_HIGH"
    status_label: str = "Coming Soon — Architecture Ready"

    def __init__(
        self,
        scheme_code: str,
        name: str,
        amc: str = "",
        category: str = "Large Cap",
        benchmark: str = "NIFTY 50 TRI",
    ):
        super().__init__(
            instrument_id=f"MF-{scheme_code}",
            asset_class=AssetClass.MUTUAL_FUND,
            symbol=scheme_code,
            name=name,
            exchange="AMFI",
            currency="INR",
            is_simulated_price=False,
            price_source="NOT_YET_ENABLED",
        )
        self.scheme_code = scheme_code
        self.amc = amc
        self.category = category
        self.benchmark = benchmark

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "scheme_code": self.scheme_code,
            "amc": self.amc,
            "category": self.category,
            "benchmark": self.benchmark,
            "status_label": self.status_label,
            "is_enabled": False,
        })
        return d


@dataclass
class FutureInstrument(InstrumentBase):
    """Index or stock future contract."""
    underlying: str = ""
    expiry: str = ""
    lot_size: int = 50
    margin_pct: float = 12.5

    def __init__(self, underlying: str, expiry: str = "NEAR", lot_size: int = 50):
        clean_und = underlying.replace(".NS", "").replace("^", "")
        inst_id = f"FUT-{clean_und}-{expiry}"
        super().__init__(
            instrument_id=inst_id,
            asset_class=AssetClass.FUTURE,
            symbol=f"{clean_und}-FUT",
            name=f"{clean_und} Futures {expiry}",
            exchange="NSE",
            currency="INR",
            is_simulated_price=True,
            price_source="MODELLED_COST_OF_CARRY",
        )
        self.underlying = underlying
        self.expiry = expiry
        self.lot_size = lot_size

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "underlying": self.underlying,
            "expiry": self.expiry,
            "lot_size": self.lot_size,
            "margin_pct": self.margin_pct,
        })
        return d


@dataclass
class OptionInstrument(InstrumentBase):
    """
    Standard European option contract.
    Values are analytically calculated via Black-Scholes using India VIX.
    """
    underlying: str = ""
    expiry: str = ""
    strike: float = 0.0
    option_type: OptionType = OptionType.CE
    lot_size: int = 50
    contract_multiplier: int = 1
    bid: float = 0.0
    ask: float = 0.0
    model_price: float = 0.0
    implied_volatility: float = 0.15
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    liquidity_score: float = 1.0

    def __init__(
        self,
        underlying: str,
        strike: float,
        option_type: OptionType,
        expiry: str = "NEAR",
        lot_size: int = 50,
        model_price: float = 0.0,
        implied_volatility: float = 0.15,
        delta: float = 0.0,
        gamma: float = 0.0,
        theta: float = 0.0,
        vega: float = 0.0,
    ):
        clean_und = underlying.replace(".NS", "").replace("^", "")
        opt_str = option_type.value if isinstance(option_type, OptionType) else str(option_type)
        inst_id = f"OPT-{clean_und}-{int(strike)}-{opt_str}-{expiry}"
        super().__init__(
            instrument_id=inst_id,
            asset_class=AssetClass.OPTION,
            symbol=f"{clean_und}-{int(strike)}-{opt_str}",
            name=f"{clean_und} {int(strike)} {opt_str} ({expiry})",
            exchange="NSE",
            currency="INR",
            is_simulated_price=True,
            price_source="MODELLED_BLACK_SCHOLES",
        )
        self.underlying = underlying
        self.strike = strike
        self.option_type = option_type if isinstance(option_type, OptionType) else OptionType(option_type)
        self.expiry = expiry
        self.lot_size = lot_size
        self.model_price = model_price
        self.bid = max(0.05, round(model_price * 0.995, 2))
        self.ask = max(0.10, round(model_price * 1.005, 2))
        self.implied_volatility = implied_volatility
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega
        self.liquidity_score = 1.0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "underlying": self.underlying,
            "expiry": self.expiry,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "lot_size": self.lot_size,
            "contract_multiplier": self.contract_multiplier,
            "bid": round(self.bid, 2),
            "ask": round(self.ask, 2),
            "model_price": round(self.model_price, 2),
            "implied_volatility": round(self.implied_volatility, 4),
            "delta": round(self.delta, 4),
            "gamma": round(self.gamma, 6),
            "theta": round(self.theta, 4),
            "vega": round(self.vega, 4),
            "liquidity_score": self.liquidity_score,
        })
        return d


@dataclass
class CommodityInstrument(InstrumentBase):
    """
    Commodity contract model (Gold, Silver, Crude Oil, Natural Gas).
    V3.3 Architecture & UI ready. No fabricated live trades.
    """
    commodity_type: str = "GOLD"
    contract_size: str = "1 kg"
    margin_pct: float = 10.0
    status_label: str = "Coming Soon — Architecture Ready"

    def __init__(self, commodity_type: str = "GOLD", name: str = ""):
        inst_id = f"CMD-{commodity_type}"
        super().__init__(
            instrument_id=inst_id,
            asset_class=AssetClass.COMMODITY,
            symbol=commodity_type,
            name=name or f"{commodity_type.title()} Spot/Futures",
            exchange="MCX",
            currency="INR",
            is_simulated_price=True,
            price_source="NOT_YET_ENABLED",
        )
        self.commodity_type = commodity_type

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "commodity_type": self.commodity_type,
            "contract_size": self.contract_size,
            "status_label": self.status_label,
            "is_enabled": False,
        })
        return d


@dataclass
class StrategyLeg:
    """Individual leg within a multi-leg options or hedged strategy."""
    leg_id: str
    instrument: OptionInstrument
    side: LegSide
    ratio: int = 1
    quantity: int = 50
    entry_price: float = 0.0
    current_price: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leg_id": self.leg_id,
            "instrument": self.instrument.to_dict(),
            "side": self.side.value,
            "ratio": self.ratio,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 2),
            "current_price": round(self.current_price, 2),
        }


@dataclass
class MultiLegStrategy:
    """
    Deterministic multi-leg options strategy container:
    - Long Call / Long Put
    - Bull Call Spread / Bear Put Spread
    - Long Straddle / Long Strangle
    - Protective Put
    """
    strategy_id: str
    strategy_type: StrategyType
    underlying: str
    expiry: str
    legs: List[StrategyLeg]
    net_debit: float
    max_profit: float
    max_loss: float
    breakeven: List[float]
    risk_reward_ratio: float
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    agent_id: str = "ALPHA"
    status: StrategyStatus = StrategyStatus.PROPOSED
    entry_underlying_price: float = 0.0
    current_underlying_price: float = 0.0
    current_strategy_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    stop_loss_amount: float = 0.0
    target_profit_amount: float = 0.0
    snapshot_id: str = ""
    strategy_version: str = "OPT-1.0"
    pricing_model: str = "BLACK_SCHOLES_VIX"
    pricing_version: str = "BS-1.0"
    entry_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    closed_time: Optional[str] = None
    exit_reason: str = ""
    net_credit: float = 0.0
    margin_required: float = 0.0
    spread_width: float = 0.0

    def calculate_payoff_at(self, spot_price: float) -> float:
        """
        Calculate total strategy payoff (₹) at a given underlying price at expiry.
        """
        total_payoff = 0.0
        for leg in self.legs:
            mult = 1 if leg.side == LegSide.BUY else -1
            opt_type = leg.instrument.option_type
            strike = leg.instrument.strike
            qty = leg.quantity
            entry_prem = leg.entry_price

            if opt_type == OptionType.CE:
                intrinsic = max(0.0, spot_price - strike)
            else:
                intrinsic = max(0.0, strike - spot_price)

            pnl_per_share = mult * (intrinsic - entry_prem)
            total_payoff += pnl_per_share * qty

        return round(total_payoff, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_type": self.strategy_type.value,
            "underlying": self.underlying,
            "expiry": self.expiry,
            "legs": [leg.to_dict() for leg in self.legs],
            "net_debit": round(self.net_debit, 2),
            "max_profit": round(self.max_profit, 2),
            "max_loss": round(self.max_loss, 2),
            "breakeven": [round(b, 2) for b in self.breakeven],
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "net_delta": round(self.net_delta, 4),
            "net_gamma": round(self.net_gamma, 6),
            "net_theta": round(self.net_theta, 4),
            "net_vega": round(self.net_vega, 4),
            "agent_id": self.agent_id,
            "status": self.status.value,
            "entry_underlying_price": round(self.entry_underlying_price, 2),
            "current_underlying_price": round(self.current_underlying_price, 2),
            "current_strategy_value": round(self.current_strategy_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "stop_loss_amount": round(self.stop_loss_amount, 2),
            "target_profit_amount": round(self.target_profit_amount, 2),
            "snapshot_id": self.snapshot_id,
            "strategy_version": self.strategy_version,
            "pricing_model": self.pricing_model,
            "pricing_version": self.pricing_version,
            "entry_time": self.entry_time,
            "closed_time": self.closed_time,
            "exit_reason": self.exit_reason,
            "net_credit": round(self.net_credit, 2),
            "margin_required": round(self.margin_required, 2),
            "spread_width": round(self.spread_width, 2),
        }


@dataclass
class OptionStrikeData:
    """Strike row containing Call and Put options data."""
    strike: float
    call: OptionInstrument
    put: OptionInstrument
    is_atm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strike": self.strike,
            "is_atm": self.is_atm,
            "call": self.call.to_dict(),
            "put": self.put.to_dict(),
        }


@dataclass
class OptionChain:
    """Full option chain for an underlying index/stock."""
    underlying: str
    underlying_price: float
    atm_strike: float
    expiry: str
    strikes: List[OptionStrikeData]
    implied_volatility_pct: float
    price_source: str = "MODELLED_BLACK_SCHOLES"
    as_of: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_modelled_data(self) -> bool:
        return self.price_source == "MODELLED_BLACK_SCHOLES"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "underlying": self.underlying,
            "underlying_price": round(self.underlying_price, 2),
            "atm_strike": self.atm_strike,
            "expiry": self.expiry,
            "strikes": [s.to_dict() for s in self.strikes],
            "implied_volatility_pct": round(self.implied_volatility_pct, 2),
            "price_source": self.price_source,
            "as_of": self.as_of,
        }
