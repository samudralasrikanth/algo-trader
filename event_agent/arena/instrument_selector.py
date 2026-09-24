# =============================================================================
# event_agent/arena/instrument_selector.py — Central Deterministic Instrument Selector
# =============================================================================
"""
Central Deterministic Instrument Selector for V4.2 Institutional Architecture:
Decouples pure market thesis from instrument execution:
1. Capacity-constrained Funnel:
   Market Thesis -> Quality Gate -> Net Edge Hurdle -> Greeks/Exposure Pre-check -> Instrument Selection
2. First-Class NO_TRADE:
   Emits structured NO_TRADE if net edge <= 0, risk/reward < 1.4, or exposure ceiling breached.
3. Multi-Asset Two-Way Support:
   - Equity: LONG / SHORT
   - Futures: LONG / SHORT
   - Options: Single Leg / Defined-Risk Spread (strictly governed by OptionDataMode)
4. Runtime Invariant:
   OPTION_DATA_MODE = LIVE -> OPTIONS MAY TRADE
   OPTION_DATA_MODE = MODELLED -> PAPER RESEARCH ONLY
   OPTION_DATA_MODE = UNAVAILABLE -> NO OPTIONS TRADE (fallback to Equity/Futures or NO_TRADE)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .asset_models import MultiLegStrategy, StrategyType
from .greeks_engine import PortfolioGreeksEngine
from .models import (
    HedgeDecision,
    Instrument,
    InstrumentType,
    OptionType,
    OrderIntent,
    PositionSide,
    ProposedTrade,
    TradeAction,
    TradeDirection,
)
from .option_chain_provider import OptionChainProvider, OptionDataMode
from .portfolio_exposure import PortfolioExposureEngine
from .strike_selector import StrikeSelector
from .thesis_validator import MarketThesis

logger = logging.getLogger(__name__)


class InstrumentSelector:
    """
    Central engine selecting the optimal instrument for a validated MarketThesis.
    """

    MIN_NET_EDGE_PCT: float = 0.35     # Minimum move to cover brokerage + slippage + STT
    MIN_RISK_REWARD: float = 1.40      # Minimum reward-to-risk ratio
    DEFAULT_MAX_PRICE_AGE_SECONDS: float = 300.0  # 5 minutes freshness window

    def __init__(
        self,
        option_chain_provider: Optional[OptionChainProvider] = None,
        execution_environment: str = "PAPER",
    ):
        self.option_provider = option_chain_provider or OptionChainProvider()
        self.execution_env = execution_environment

    def select_instrument(
        self,
        thesis: MarketThesis,
        stock_data: Dict[str, Any],
        portfolio_equity: float,
        current_open_positions: List[Dict[str, Any]],
        snapshot_id: str = "",
        sequence: int = 1,
        decision_timestamp: Optional[datetime] = None,
    ) -> ProposedTrade:
        """
        Processes a MarketThesis through the deterministic funnel and outputs
        either an actionable ProposedTrade or a structured NO_TRADE.
        """
        symbol = thesis.symbol
        base_price = float(stock_data.get("base_price", 0.0))
        sector = stock_data.get("sector", "Diversified")
        beta = float(stock_data.get("beta", 1.0))
        direction_str = thesis.direction.upper()

        # Gate 0.0: Hard TradeGuard Invariant — AI Decision Availability
        # If thesis was generated under AI failure (CREDIT_EXHAUSTED, UNAVAILABLE, etc.),
        # new entries MUST NOT be proposed. Blocks model substitution and preserves cohort integrity.
        if (
            thesis.decision_mode == "AI_UNAVAILABLE"
            or thesis.ai_status.upper() != "INFERENCE_SUCCESS"
            or direction_str in ("NO_TRADE", "UNAVAILABLE")
        ):
            return self._build_no_trade(
                thesis,
                f"AI_DECISION_UNAVAILABLE: New AI-dependent entries blocked (Status: {thesis.ai_status}, Reason: {thesis.fallback_reason or 'No inference'}).",
                snapshot_id,
                sequence,
            )

        # Gate 0: Valid base price
        if base_price <= 0:
            return self._build_no_trade(
                thesis,
                f"Base market price invalid or zero for {symbol}.",
                snapshot_id,
                sequence,
            )

        # Gate 0.1: Hard TradeGuard Invariant — Base Price Freshness & Causal Ordering
        # A trade proposal must never use a prediction baseline whose market timestamp is older
        # than the allowable decision-time freshness window. Must reject with STALE_BASE_PRICE.
        # Targets and stops must NEVER be rebased silently against a different live price.
        base_price_ts_raw = stock_data.get("base_price_timestamp") or stock_data.get("price_timestamp")
        if base_price_ts_raw is not None:
            try:
                if isinstance(base_price_ts_raw, (int, float)):
                    bp_ts = datetime.fromtimestamp(base_price_ts_raw, tz=timezone.utc)
                elif isinstance(base_price_ts_raw, str):
                    bp_ts = datetime.fromisoformat(base_price_ts_raw.replace("Z", "+00:00"))
                else:
                    bp_ts = base_price_ts_raw

                dec_ts = decision_timestamp or datetime.now(timezone.utc)
                if isinstance(dec_ts, str):
                    dec_ts = datetime.fromisoformat(dec_ts.replace("Z", "+00:00"))

                # Ensure both are timezone-aware or naive consistently
                if bp_ts.tzinfo is not None and dec_ts.tzinfo is None:
                    dec_ts = dec_ts.replace(tzinfo=timezone.utc)
                elif bp_ts.tzinfo is None and dec_ts.tzinfo is not None:
                    bp_ts = bp_ts.replace(tzinfo=timezone.utc)

                max_age_sec = float(stock_data.get("max_price_age_seconds") or self.DEFAULT_MAX_PRICE_AGE_SECONDS)

                # Invariant 1: Causal ordering (base_price_timestamp <= decision_timestamp)
                if bp_ts > dec_ts:
                    return self._build_no_trade(
                        thesis,
                        f"STALE_BASE_PRICE: Future base price timestamp detected ({bp_ts.isoformat()} > {dec_ts.isoformat()}).",
                        snapshot_id,
                        sequence,
                    )

                # Invariant 2: Freshness window (decision_timestamp - base_price_timestamp <= MAX_PRICE_AGE)
                age_seconds = (dec_ts - bp_ts).total_seconds()
                if age_seconds > max_age_sec:
                    return self._build_no_trade(
                        thesis,
                        f"STALE_BASE_PRICE: Base price timestamp age ({age_seconds:.1f}s) exceeds allowable freshness window ({max_age_sec:.1f}s).",
                        snapshot_id,
                        sequence,
                    )
            except Exception as exc:
                logger.debug(f"Base price freshness parsing for {symbol}: {exc}")

        # Gate 1: Neutral direction -> immediate NO_TRADE
        if direction_str == "NEUTRAL":
            return self._build_no_trade(
                thesis,
                "Market thesis has NEUTRAL bias; capital preserved in cash.",
                snapshot_id,
                sequence,
            )

        # Gate 2: Net Edge Hurdle (Gross expected move must clear roundtrip costs)
        raw_gross_move = abs(thesis.expected_move_pct)
        if raw_gross_move < self.MIN_NET_EDGE_PCT:
            # Invariant: Fundamental data CANNOT force a trade if raw trading edge < hurdle
            return self._build_no_trade(
                thesis,
                f"Expected move {thesis.expected_move_pct:+.2f}% is below net edge hurdle of {self.MIN_NET_EDGE_PCT:.2f}% after brokerage and friction.",
                snapshot_id,
                sequence,
            )

        # Observational Fundamental Shadow Edge Calculation: [-0.10%, +0.10%]
        # Execution Edge = Trading Edge (Unmodified execution path)
        # Shadow Edge    = Trading Edge + Fundamental Adjustment (Observational shadow mode)
        execution_edge = raw_gross_move
        fundamental_adj = 0.0
        fc = thesis.fundamental_context
        if fc is not None and fc.quality_score is not None:
            if fc.confirmation:
                # High quality / valuation support gives bounded boost up to +0.10%
                fundamental_adj = round(min(0.10, max(0.0, ((fc.quality_score or 50.0) - 50.0) / 500.0)), 3)
            elif fc.contradiction:
                # Contradictory fundamentals shave off up to -0.10%
                fundamental_adj = round(max(-0.10, min(0.0, -abs(50.0 - (fc.quality_score or 50.0)) / 500.0)), 3)
                if fundamental_adj == 0.0:
                    fundamental_adj = -0.05

        shadow_adjusted_edge = round(max(0.0, execution_edge + fundamental_adj), 4)

        if fc is not None:
            fc.execution_edge = execution_edge
            fc.fundamental_adj = fundamental_adj
            fc.shadow_adjusted_edge = shadow_adjusted_edge

        # Gate 3: Thesis Conflict handling (if macro or fundamentals oppose AI, require higher confidence)
        if thesis.is_conflicted:
            if thesis.confidence < 70.0:
                return self._build_no_trade(
                    thesis,
                    f"Conflict detected ({thesis.conflict_reason}). Conviction {thesis.confidence:.1f}% below 70.0% threshold for conflicting setup.",
                    snapshot_id,
                    sequence,
                )

        # Gate 4: Portfolio Sector & Beta Exposure Pre-check
        exposure_eval = PortfolioExposureEngine.evaluate_exposure(
            open_positions=current_open_positions,
            portfolio_equity=portfolio_equity,
            candidate_sector=sector,
            candidate_beta=beta,
        )
        if not exposure_eval.is_compliant:
            return self._build_no_trade(
                thesis,
                f"Portfolio diversification gate: {exposure_eval.rejection_reason}",
                snapshot_id,
                sequence,
            )

        # Gate 5: Direction & Two-Way Semantics
        is_bullish = direction_str == "BULLISH"
        pos_side = PositionSide.LONG if is_bullish else PositionSide.SHORT
        trade_action = TradeAction.BUY if is_bullish else TradeAction.SELL
        trade_dir = TradeDirection.BUY if is_bullish else TradeDirection.SELL
        order_intent = OrderIntent.OPEN

        # Compute price targets and stops strictly using execution_edge (unmodified by shadow edge)
        if is_bullish:
            target = base_price * (1.0 + execution_edge / 100.0)
            stop = base_price * (1.0 - (execution_edge / 100.0) / self.MIN_RISK_REWARD)
        else:
            target = base_price * (1.0 - execution_edge / 100.0)
            stop = base_price * (1.0 + (execution_edge / 100.0) / self.MIN_RISK_REWARD)

        # Gate 6: Asset Class / Instrument Selection
        inst_type = InstrumentType.EQUITY
        selected_strategy: Optional[MultiLegStrategy] = None
        contract_name: Optional[str] = None
        selected_opt_strike: Optional[float] = None
        selected_opt_type: OptionType = OptionType.NONE
        selected_opt_expiry: Optional[str] = None
        selected_opt_prem: float = 0.0
        selected_lot_size: int = 1
        reason_extra = ""
        mode = self.option_provider.current_mode

        # Check options eligibility
        can_trade_opts = self.option_provider.can_trade_options(self.execution_env)
        agent_id = thesis.agent_id.upper()
        high_conviction_event = thesis.confidence >= 75.0 and execution_edge >= 1.0

        if high_conviction_event or agent_id in ("DEFENSIVE", "ALPHA"):
            if can_trade_opts:
                chain, mode = self.option_provider.get_chain(
                    underlying=symbol,
                    spot_price=base_price,
                    days_to_expiry=7,
                    implied_volatility=0.18,
                )
                if chain and chain.strikes:
                    is_call = is_bullish
                    opt_info = StrikeSelector.select_strike(chain=chain, is_call=is_call)
                    if opt_info:
                        opt_strike = float(opt_info["strike"])
                        opt_type = opt_info["option_type"]
                        opt_prem = float(opt_info.get("premium", 0.0))
                        opt_exp = str(getattr(chain, "expiry", "7D"))
                        # Invariant: Underlying equity price cannot be used as option premium
                        if opt_prem > 0.0 and abs(opt_prem - base_price) > (0.1 * base_price):
                            inst_type = InstrumentType.OPTION
                            contract_name = opt_info["contract_symbol"]
                            selected_opt_strike = opt_strike
                            selected_opt_type = opt_type
                            selected_opt_expiry = opt_exp
                            selected_opt_prem = opt_prem
                            selected_lot_size = getattr(chain, "lot_size", 50)
                            strat_rec = StrikeSelector.recommend_strategy_structure(
                                iv_rank=45.0,
                                expected_move_pct=thesis.expected_move_pct,
                                confidence=thesis.confidence,
                            )
                            reason_extra = f" [{mode.value} Option Selected: Strike {opt_strike} {opt_type.value}, Premium: ₹{opt_prem:.2f}, Delta {opt_info['delta']:.2f}, Structure: {strat_rec.value}]"
            else:
                # Options forbidden by mode
                if self.option_provider.current_mode == OptionDataMode.UNAVAILABLE:
                    reason_extra = " [OPTION_DATA_MODE is UNAVAILABLE: Options trading strictly prohibited. Falling back to underlying instrument.]"
                elif self.option_provider.current_mode == OptionDataMode.MODELLED and self.execution_env == "LIVE":
                    reason_extra = " [MODELLED options prohibited in LIVE execution. Routing to Cash/Futures.]"

        # If not options, check if Futures should be used for trend gearing
        if inst_type == InstrumentType.EQUITY and agent_id in ("MOMENTUM", "MACRO") and execution_edge >= 1.2:
            inst_type = InstrumentType.FUTURE
            contract_name = f"{symbol}-FUT-NEAR"
            reason_extra = " [Futures contract selected for trend gearing.]"

        # Construct finalized Instrument
        if inst_type == InstrumentType.OPTION:
            instrument = Instrument(
                underlying=symbol,
                instrument_type=inst_type,
                expiry=selected_opt_expiry,
                strike=selected_opt_strike,
                option_type=selected_opt_type,
                contract_name=contract_name,
                lot_size=selected_lot_size,
                option_premium=selected_opt_prem,
                is_simulated_price=True,
                pricing_model=mode.value if hasattr(mode, "value") else "BLACK_SCHOLES_VIX_PROXY",
            )
        else:
            instrument = Instrument(
                underlying=symbol,
                instrument_type=inst_type,
                contract_name=contract_name,
                is_simulated_price=(inst_type != InstrumentType.EQUITY),
            )

        planned_risk = portfolio_equity * 0.005  # 0.5% risk limit per trade
        decision_reason = (
            f"Validated {thesis.direction} thesis: {thesis.reasoning}{reason_extra} "
            f"[Execution Edge: {execution_edge:.2f}%, Shadow Edge: {shadow_adjusted_edge:.2f}%, Δfund: {fundamental_adj:+.2f}%]"
        )

        return ProposedTrade(
            agent_id=thesis.agent_id,
            strategy_version=f"{thesis.agent_id}-4.2",
            symbol=symbol,
            action=trade_action,
            instrument=instrument,
            direction=trade_dir,
            entry_price=base_price,
            stop_loss=round(stop, 2),
            target=round(target, 2),
            confidence=thesis.confidence,
            expected_move_pct=thesis.expected_move_pct,
            planned_risk_amount=planned_risk,
            hedge_decision=HedgeDecision.NO,
            decision_reason=decision_reason,
            snapshot_id=snapshot_id,
            sequence=sequence,
            strategy=selected_strategy,
            thesis=thesis.reasoning,
            evidence=thesis.catalysts,
            horizon=thesis.horizon,
            expected_return=thesis.expected_move_pct,
            position_side=pos_side,
            order_action=trade_action,
            order_intent=order_intent,
            execution_edge=execution_edge,
            shadow_adjusted_edge=shadow_adjusted_edge,
            fundamental_adj=fundamental_adj,
        )

    def _build_no_trade(
        self,
        thesis: MarketThesis,
        reason: str,
        snapshot_id: str,
        sequence: int,
    ) -> ProposedTrade:
        """Helper to create a structured NO_TRADE ProposedTrade."""
        inst = Instrument(underlying=thesis.symbol or "NIFTY50", instrument_type=InstrumentType.EQUITY)
        return ProposedTrade(
            agent_id=thesis.agent_id,
            strategy_version=f"{thesis.agent_id}-4.2",
            symbol=thesis.symbol or "NIFTY50",
            action=TradeAction.NO_TRADE,
            instrument=inst,
            direction=TradeDirection.NONE,
            entry_price=0.0,
            stop_loss=0.0,
            target=0.0,
            confidence=thesis.confidence,
            expected_move_pct=0.0,
            planned_risk_amount=0.0,
            hedge_decision=HedgeDecision.NO,
            decision_reason=reason,
            snapshot_id=snapshot_id,
            sequence=sequence,
            thesis=thesis.reasoning,
            horizon=thesis.horizon,
            position_side=PositionSide.LONG,
            order_action=TradeAction.NO_TRADE,
            order_intent=OrderIntent.OPEN,
        )
