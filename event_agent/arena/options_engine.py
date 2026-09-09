# =============================================================================
# event_agent/arena/options_engine.py — Deterministic Black-Scholes & Strategy Engine
# =============================================================================
"""
Options Pricing, Greeks & Multi-Leg Strategy Engine for V3.3:
1. Exact Analytical Black-Scholes Valuation for European Call & Put Options
2. Analytical Greeks: Delta, Gamma, Theta (1-day), Vega (1% IV move)
3. Deterministic Option Chain Generator (ATM ± 5 strikes)
4. 7 Core Options Strategies:
   - Long Call
   - Long Put
   - Bull Call Spread
   - Bear Put Spread
   - Long Straddle
   - Long Strangle
   - Protective Put
5. Multi-leg strategy payoff curves across price spectrum
6. Expiry settlement engine (intrinsic settlement for ITM, zero for OTM)
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .asset_models import (
    AssetClass,
    LegSide,
    MultiLegStrategy,
    OptionChain,
    OptionInstrument,
    OptionStrikeData,
    OptionType,
    StrategyLeg,
    StrategyStatus,
    StrategyType,
)

# Standard market parameters for Indian options (NSE Nifty 50)
DEFAULT_RISK_FREE_RATE = 0.065   # 6.5% 91-day T-Bill rate
DEFAULT_DIVIDEND_YIELD = 0.012   # 1.2% Nifty 50 dividend yield
DEFAULT_LOT_SIZE = 50           # Nifty standard contract lot size


def norm_cdf(x: float) -> float:
    """Deterministic Cumulative Normal Distribution using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Deterministic Standard Normal Probability Density Function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


class OptionsPricingEngine:
    """
    Deterministic European option pricing and Greeks calculation engine.
    Modelled prices are explicitly labeled MODELLED_BLACK_SCHOLES.
    """

    @staticmethod
    def calculate_price_and_greeks(
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        volatility: float,
        is_call: bool = True,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        dividend_yield: float = DEFAULT_DIVIDEND_YIELD,
    ) -> Dict[str, float]:
        """
        Calculates option theoretical price, Delta, Gamma, Theta, and Vega.
        At expiry (T <= 0), price is exact intrinsic value and Greeks collapse to boundary states.
        """
        # Expiry or zero time boundary
        if time_to_expiry_years <= 0.0001:
            if is_call:
                price = max(0.0, spot - strike)
                delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
            else:
                price = max(0.0, strike - spot)
                delta = -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)
            return {
                "price": max(0.05, round(price, 2)),
                "delta": round(delta, 4),
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
            }

        # Guard against zero/negative inputs
        S = max(0.01, spot)
        K = max(0.01, strike)
        T = max(0.0001, time_to_expiry_years)
        sigma = max(0.01, volatility)
        r = risk_free_rate
        q = dividend_yield

        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        exp_qT = math.exp(-q * T)
        exp_rT = math.exp(-r * T)
        pdf_d1 = norm_pdf(d1)

        if is_call:
            price = S * exp_qT * norm_cdf(d1) - K * exp_rT * norm_cdf(d2)
            delta = exp_qT * norm_cdf(d1)
            # Theta for 1 calendar day
            theta_annual = (
                -(S * sigma * exp_qT * pdf_d1) / (2.0 * sqrt_T)
                - r * K * exp_rT * norm_cdf(d2)
                + q * S * exp_qT * norm_cdf(d1)
            )
        else:
            price = K * exp_rT * norm_cdf(-d2) - S * exp_qT * norm_cdf(-d1)
            delta = -exp_qT * norm_cdf(-d1)
            # Theta for 1 calendar day
            theta_annual = (
                -(S * sigma * exp_qT * pdf_d1) / (2.0 * sqrt_T)
                + r * K * exp_rT * norm_cdf(-d2)
                - q * S * exp_qT * norm_cdf(-d1)
            )

        theta_1d = theta_annual / 365.0
        gamma = (exp_qT * pdf_d1) / (S * sigma * sqrt_T)
        vega_1pct = (S * exp_qT * sqrt_T * pdf_d1) / 100.0  # ₹ move per 1% change in vol

        return {
            "price": max(0.05, round(price, 2)),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta_1d, 4),
            "vega": round(vega_1pct, 4),
        }

    @staticmethod
    def build_option_chain(
        underlying: str,
        spot_price: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        strike_step: float = 50.0,
        strikes_count: int = 5,
        lot_size: int = DEFAULT_LOT_SIZE,
    ) -> OptionChain:
        """
        Builds a comprehensive Option Chain centered on ATM strike:
        ATM ± strikes_count strikes with Calls & Puts pricing and analytical Greeks.
        """
        T_years = max(0.001, expiry_days / 365.0)
        atm_strike = round(spot_price / strike_step) * strike_step

        strikes_data: List[OptionStrikeData] = []
        start_strike = atm_strike - (strikes_count * strike_step)
        end_strike = atm_strike + (strikes_count * strike_step)

        curr_strike = start_strike
        while curr_strike <= end_strike:
            is_atm = abs(curr_strike - atm_strike) < (strike_step / 2.0)

            # Call
            call_calc = OptionsPricingEngine.calculate_price_and_greeks(
                spot=spot_price,
                strike=curr_strike,
                time_to_expiry_years=T_years,
                volatility=volatility,
                is_call=True,
            )
            call_inst = OptionInstrument(
                underlying=underlying,
                strike=curr_strike,
                option_type=OptionType.CE,
                expiry=f"{expiry_days}D",
                lot_size=lot_size,
                model_price=call_calc["price"],
                implied_volatility=volatility,
                delta=call_calc["delta"],
                gamma=call_calc["gamma"],
                theta=call_calc["theta"],
                vega=call_calc["vega"],
            )

            # Put
            put_calc = OptionsPricingEngine.calculate_price_and_greeks(
                spot=spot_price,
                strike=curr_strike,
                time_to_expiry_years=T_years,
                volatility=volatility,
                is_call=False,
            )
            put_inst = OptionInstrument(
                underlying=underlying,
                strike=curr_strike,
                option_type=OptionType.PE,
                expiry=f"{expiry_days}D",
                lot_size=lot_size,
                model_price=put_calc["price"],
                implied_volatility=volatility,
                delta=put_calc["delta"],
                gamma=put_calc["gamma"],
                theta=put_calc["theta"],
                vega=put_calc["vega"],
            )

            strikes_data.append(
                OptionStrikeData(
                    strike=curr_strike,
                    call=call_inst,
                    put=put_inst,
                    is_atm=is_atm,
                )
            )
            curr_strike += strike_step

        return OptionChain(
            underlying=underlying,
            underlying_price=spot_price,
            atm_strike=atm_strike,
            expiry=f"{expiry_days} Days",
            strikes=strikes_data,
            implied_volatility_pct=round(volatility * 100.0, 2),
            price_source="MODELLED_BLACK_SCHOLES",
        )


class OptionsStrategyBuilder:
    """
    Constructs and values the 7 Core Options Strategies with exact math:
    - Long Call
    - Long Put
    - Bull Call Spread
    - Bear Put Spread
    - Long Straddle
    - Long Strangle
    - Protective Put
    """

    @staticmethod
    def create_long_call(
        underlying: str,
        spot_price: float,
        strike: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        lot_size: int = DEFAULT_LOT_SIZE,
        quantity: int = DEFAULT_LOT_SIZE,
        agent_id: str = "ALPHA",
        snapshot_id: str = "",
    ) -> MultiLegStrategy:
        T_years = max(0.001, expiry_days / 365.0)
        calc = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=strike, time_to_expiry_years=T_years, volatility=volatility, is_call=True
        )
        prem = calc["price"]
        opt_inst = OptionInstrument(
            underlying=underlying, strike=strike, option_type=OptionType.CE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=prem,
            implied_volatility=volatility, delta=calc["delta"], gamma=calc["gamma"],
            theta=calc["theta"], vega=calc["vega"]
        )

        leg = StrategyLeg(
            leg_id=f"LEG-1-{opt_inst.symbol}",
            instrument=opt_inst,
            side=LegSide.BUY,
            ratio=1,
            quantity=quantity,
            entry_price=prem,
            current_price=prem,
        )

        net_debit = prem * quantity
        max_loss = net_debit
        max_profit = round(spot_price * 0.10 * quantity, 2)  # Modeled target upside (+10%)
        breakeven = [strike + prem]
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 2.5

        strat_id = f"STRAT-LC-{underlying.replace('.NS', '')}-{int(strike)}-{snapshot_id[:6] or 'GEN'}"
        return MultiLegStrategy(
            strategy_id=strat_id,
            strategy_type=StrategyType.LONG_CALL,
            underlying=underlying,
            expiry=f"{expiry_days}D",
            legs=[leg],
            net_debit=net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakeven,
            risk_reward_ratio=rr,
            net_delta=calc["delta"] * quantity,
            net_gamma=calc["gamma"] * quantity,
            net_theta=calc["theta"] * quantity,
            net_vega=calc["vega"] * quantity,
            agent_id=agent_id,
            entry_underlying_price=spot_price,
            current_underlying_price=spot_price,
            current_strategy_value=net_debit,
            stop_loss_amount=net_debit * 0.5,  # Stop at 50% premium decay
            target_profit_amount=net_debit * 1.0,  # Target 100% gain
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def create_long_put(
        underlying: str,
        spot_price: float,
        strike: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        lot_size: int = DEFAULT_LOT_SIZE,
        quantity: int = DEFAULT_LOT_SIZE,
        agent_id: str = "ALPHA",
        snapshot_id: str = "",
    ) -> MultiLegStrategy:
        T_years = max(0.001, expiry_days / 365.0)
        calc = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=strike, time_to_expiry_years=T_years, volatility=volatility, is_call=False
        )
        prem = calc["price"]
        opt_inst = OptionInstrument(
            underlying=underlying, strike=strike, option_type=OptionType.PE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=prem,
            implied_volatility=volatility, delta=calc["delta"], gamma=calc["gamma"],
            theta=calc["theta"], vega=calc["vega"]
        )

        leg = StrategyLeg(
            leg_id=f"LEG-1-{opt_inst.symbol}",
            instrument=opt_inst,
            side=LegSide.BUY,
            ratio=1,
            quantity=quantity,
            entry_price=prem,
            current_price=prem,
        )

        net_debit = prem * quantity
        max_loss = net_debit
        max_profit = round((strike - prem) * quantity, 2)
        breakeven = [strike - prem]
        rr = round(min(max_profit, spot_price * 0.10 * quantity) / max_loss, 2) if max_loss > 0 else 2.5

        strat_id = f"STRAT-LP-{underlying.replace('.NS', '')}-{int(strike)}-{snapshot_id[:6] or 'GEN'}"
        return MultiLegStrategy(
            strategy_id=strat_id,
            strategy_type=StrategyType.LONG_PUT,
            underlying=underlying,
            expiry=f"{expiry_days}D",
            legs=[leg],
            net_debit=net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakeven,
            risk_reward_ratio=rr,
            net_delta=calc["delta"] * quantity,
            net_gamma=calc["gamma"] * quantity,
            net_theta=calc["theta"] * quantity,
            net_vega=calc["vega"] * quantity,
            agent_id=agent_id,
            entry_underlying_price=spot_price,
            current_underlying_price=spot_price,
            current_strategy_value=net_debit,
            stop_loss_amount=net_debit * 0.5,
            target_profit_amount=net_debit * 1.0,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def create_bull_call_spread(
        underlying: str,
        spot_price: float,
        buy_strike: float,
        sell_strike: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        lot_size: int = DEFAULT_LOT_SIZE,
        quantity: int = DEFAULT_LOT_SIZE,
        agent_id: str = "ALPHA",
        snapshot_id: str = "",
    ) -> MultiLegStrategy:
        """
        Bull Call Spread: BUY Lower Strike CE + SELL Higher Strike CE.
        Capped loss (net debit paid) and capped profit ((K_high - K_low) - debit).
        """
        assert sell_strike > buy_strike, "Sell strike must be higher than buy strike for Bull Call Spread"

        T_years = max(0.001, expiry_days / 365.0)
        c_buy = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=buy_strike, time_to_expiry_years=T_years, volatility=volatility, is_call=True
        )
        c_sell = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=sell_strike, time_to_expiry_years=T_years, volatility=volatility, is_call=True
        )

        buy_inst = OptionInstrument(
            underlying=underlying, strike=buy_strike, option_type=OptionType.CE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=c_buy["price"],
            implied_volatility=volatility, delta=c_buy["delta"], gamma=c_buy["gamma"],
            theta=c_buy["theta"], vega=c_buy["vega"]
        )
        sell_inst = OptionInstrument(
            underlying=underlying, strike=sell_strike, option_type=OptionType.CE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=c_sell["price"],
            implied_volatility=volatility, delta=c_sell["delta"], gamma=c_sell["gamma"],
            theta=c_sell["theta"], vega=c_sell["vega"]
        )

        leg1 = StrategyLeg(
            leg_id=f"LEG-1-{buy_inst.symbol}", instrument=buy_inst, side=LegSide.BUY,
            ratio=1, quantity=quantity, entry_price=c_buy["price"], current_price=c_buy["price"]
        )
        leg2 = StrategyLeg(
            leg_id=f"LEG-2-{sell_inst.symbol}", instrument=sell_inst, side=LegSide.SELL,
            ratio=1, quantity=quantity, entry_price=c_sell["price"], current_price=c_sell["price"]
        )

        debit_per_share = max(0.10, c_buy["price"] - c_sell["price"])
        net_debit = round(debit_per_share * quantity, 2)
        spread_width = sell_strike - buy_strike
        max_profit = round((spread_width - debit_per_share) * quantity, 2)
        max_loss = net_debit
        breakeven = [buy_strike + debit_per_share]
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 2.0

        net_delta = (c_buy["delta"] - c_sell["delta"]) * quantity
        net_gamma = (c_buy["gamma"] - c_sell["gamma"]) * quantity
        net_theta = (c_buy["theta"] - c_sell["theta"]) * quantity
        net_vega = (c_buy["vega"] - c_sell["vega"]) * quantity

        strat_id = f"STRAT-BCS-{underlying.replace('.NS', '')}-{int(buy_strike)}-{int(sell_strike)}-{snapshot_id[:6] or 'GEN'}"
        return MultiLegStrategy(
            strategy_id=strat_id,
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            underlying=underlying,
            expiry=f"{expiry_days}D",
            legs=[leg1, leg2],
            net_debit=net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakeven,
            risk_reward_ratio=rr,
            net_delta=round(net_delta, 4),
            net_gamma=round(net_gamma, 6),
            net_theta=round(net_theta, 4),
            net_vega=round(net_vega, 4),
            agent_id=agent_id,
            entry_underlying_price=spot_price,
            current_underlying_price=spot_price,
            current_strategy_value=net_debit,
            stop_loss_amount=net_debit * 0.7,
            target_profit_amount=max_profit * 0.8,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def create_bear_put_spread(
        underlying: str,
        spot_price: float,
        buy_strike: float,
        sell_strike: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        lot_size: int = DEFAULT_LOT_SIZE,
        quantity: int = DEFAULT_LOT_SIZE,
        agent_id: str = "ALPHA",
        snapshot_id: str = "",
    ) -> MultiLegStrategy:
        """
        Bear Put Spread: BUY Higher Strike PE + SELL Lower Strike PE.
        """
        assert buy_strike > sell_strike, "Buy strike must be higher than sell strike for Bear Put Spread"

        T_years = max(0.001, expiry_days / 365.0)
        p_buy = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=buy_strike, time_to_expiry_years=T_years, volatility=volatility, is_call=False
        )
        p_sell = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=sell_strike, time_to_expiry_years=T_years, volatility=volatility, is_call=False
        )

        buy_inst = OptionInstrument(
            underlying=underlying, strike=buy_strike, option_type=OptionType.PE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=p_buy["price"],
            implied_volatility=volatility, delta=p_buy["delta"], gamma=p_buy["gamma"],
            theta=p_buy["theta"], vega=p_buy["vega"]
        )
        sell_inst = OptionInstrument(
            underlying=underlying, strike=sell_strike, option_type=OptionType.PE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=p_sell["price"],
            implied_volatility=volatility, delta=p_sell["delta"], gamma=p_sell["gamma"],
            theta=p_sell["theta"], vega=p_sell["vega"]
        )

        leg1 = StrategyLeg(
            leg_id=f"LEG-1-{buy_inst.symbol}", instrument=buy_inst, side=LegSide.BUY,
            ratio=1, quantity=quantity, entry_price=p_buy["price"], current_price=p_buy["price"]
        )
        leg2 = StrategyLeg(
            leg_id=f"LEG-2-{sell_inst.symbol}", instrument=sell_inst, side=LegSide.SELL,
            ratio=1, quantity=quantity, entry_price=p_sell["price"], current_price=p_sell["price"]
        )

        debit_per_share = max(0.10, p_buy["price"] - p_sell["price"])
        net_debit = round(debit_per_share * quantity, 2)
        spread_width = buy_strike - sell_strike
        max_profit = round((spread_width - debit_per_share) * quantity, 2)
        max_loss = net_debit
        breakeven = [buy_strike - debit_per_share]
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 2.0

        net_delta = (p_buy["delta"] - p_sell["delta"]) * quantity
        net_gamma = (p_buy["gamma"] - p_sell["gamma"]) * quantity
        net_theta = (p_buy["theta"] - p_sell["theta"]) * quantity
        net_vega = (p_buy["vega"] - p_sell["vega"]) * quantity

        strat_id = f"STRAT-BPS-{underlying.replace('.NS', '')}-{int(buy_strike)}-{int(sell_strike)}-{snapshot_id[:6] or 'GEN'}"
        return MultiLegStrategy(
            strategy_id=strat_id,
            strategy_type=StrategyType.BEAR_PUT_SPREAD,
            underlying=underlying,
            expiry=f"{expiry_days}D",
            legs=[leg1, leg2],
            net_debit=net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakeven,
            risk_reward_ratio=rr,
            net_delta=round(net_delta, 4),
            net_gamma=round(net_gamma, 6),
            net_theta=round(net_theta, 4),
            net_vega=round(net_vega, 4),
            agent_id=agent_id,
            entry_underlying_price=spot_price,
            current_underlying_price=spot_price,
            current_strategy_value=net_debit,
            stop_loss_amount=net_debit * 0.7,
            target_profit_amount=max_profit * 0.8,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def create_long_straddle(
        underlying: str,
        spot_price: float,
        strike: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        lot_size: int = DEFAULT_LOT_SIZE,
        quantity: int = DEFAULT_LOT_SIZE,
        agent_id: str = "ALPHA",
        snapshot_id: str = "",
    ) -> MultiLegStrategy:
        """
        Long Straddle: BUY ATM CE + BUY ATM PE at same strike & expiry.
        Delta-neutral strategy profiting from large volatility expansions.
        """
        T_years = max(0.001, expiry_days / 365.0)
        c = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=strike, time_to_expiry_years=T_years, volatility=volatility, is_call=True
        )
        p = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=strike, time_to_expiry_years=T_years, volatility=volatility, is_call=False
        )

        c_inst = OptionInstrument(
            underlying=underlying, strike=strike, option_type=OptionType.CE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=c["price"],
            implied_volatility=volatility, delta=c["delta"], gamma=c["gamma"], theta=c["theta"], vega=c["vega"]
        )
        p_inst = OptionInstrument(
            underlying=underlying, strike=strike, option_type=OptionType.PE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=p["price"],
            implied_volatility=volatility, delta=p["delta"], gamma=p["gamma"], theta=p["theta"], vega=p["vega"]
        )

        leg1 = StrategyLeg(leg_id=f"LEG-1-{c_inst.symbol}", instrument=c_inst, side=LegSide.BUY, ratio=1, quantity=quantity, entry_price=c["price"], current_price=c["price"])
        leg2 = StrategyLeg(leg_id=f"LEG-2-{p_inst.symbol}", instrument=p_inst, side=LegSide.BUY, ratio=1, quantity=quantity, entry_price=p["price"], current_price=p["price"])

        total_prem = (c["price"] + p["price"])
        net_debit = round(total_prem * quantity, 2)
        max_loss = net_debit
        max_profit = round(spot_price * 0.15 * quantity, 2)
        breakevens = [strike - total_prem, strike + total_prem]
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 2.0

        net_delta = (c["delta"] + p["delta"]) * quantity
        net_gamma = (c["gamma"] + p["gamma"]) * quantity
        net_theta = (c["theta"] + p["theta"]) * quantity
        net_vega = (c["vega"] + p["vega"]) * quantity

        strat_id = f"STRAT-STRD-{underlying.replace('.NS', '')}-{int(strike)}-{snapshot_id[:6] or 'GEN'}"
        return MultiLegStrategy(
            strategy_id=strat_id,
            strategy_type=StrategyType.LONG_STRADDLE,
            underlying=underlying,
            expiry=f"{expiry_days}D",
            legs=[leg1, leg2],
            net_debit=net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakevens,
            risk_reward_ratio=rr,
            net_delta=round(net_delta, 4),
            net_gamma=round(net_gamma, 6),
            net_theta=round(net_theta, 4),
            net_vega=round(net_vega, 4),
            agent_id=agent_id,
            entry_underlying_price=spot_price,
            current_underlying_price=spot_price,
            current_strategy_value=net_debit,
            stop_loss_amount=net_debit * 0.5,
            target_profit_amount=net_debit * 0.8,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def create_long_strangle(
        underlying: str,
        spot_price: float,
        put_strike: float,
        call_strike: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        lot_size: int = DEFAULT_LOT_SIZE,
        quantity: int = DEFAULT_LOT_SIZE,
        agent_id: str = "ALPHA",
        snapshot_id: str = "",
    ) -> MultiLegStrategy:
        """
        Long Strangle: BUY OTM Put + BUY OTM Call.
        Lower cost than straddle with wider breakevens.
        """
        assert call_strike > put_strike, "Call strike must be higher than put strike for Strangle"

        T_years = max(0.001, expiry_days / 365.0)
        c = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=call_strike, time_to_expiry_years=T_years, volatility=volatility, is_call=True
        )
        p = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=put_strike, time_to_expiry_years=T_years, volatility=volatility, is_call=False
        )

        c_inst = OptionInstrument(
            underlying=underlying, strike=call_strike, option_type=OptionType.CE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=c["price"],
            implied_volatility=volatility, delta=c["delta"], gamma=c["gamma"], theta=c["theta"], vega=c["vega"]
        )
        p_inst = OptionInstrument(
            underlying=underlying, strike=put_strike, option_type=OptionType.PE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=p["price"],
            implied_volatility=volatility, delta=p["delta"], gamma=p["gamma"], theta=p["theta"], vega=p["vega"]
        )

        leg1 = StrategyLeg(leg_id=f"LEG-1-{c_inst.symbol}", instrument=c_inst, side=LegSide.BUY, ratio=1, quantity=quantity, entry_price=c["price"], current_price=c["price"])
        leg2 = StrategyLeg(leg_id=f"LEG-2-{p_inst.symbol}", instrument=p_inst, side=LegSide.BUY, ratio=1, quantity=quantity, entry_price=p["price"], current_price=p["price"])

        total_prem = (c["price"] + p["price"])
        net_debit = round(total_prem * quantity, 2)
        max_loss = net_debit
        max_profit = round(spot_price * 0.15 * quantity, 2)
        breakevens = [put_strike - total_prem, call_strike + total_prem]
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 2.5

        net_delta = (c["delta"] + p["delta"]) * quantity
        net_gamma = (c["gamma"] + p["gamma"]) * quantity
        net_theta = (c["theta"] + p["theta"]) * quantity
        net_vega = (c["vega"] + p["vega"]) * quantity

        strat_id = f"STRAT-STRG-{underlying.replace('.NS', '')}-{int(put_strike)}-{int(call_strike)}-{snapshot_id[:6] or 'GEN'}"
        return MultiLegStrategy(
            strategy_id=strat_id,
            strategy_type=StrategyType.LONG_STRANGLE,
            underlying=underlying,
            expiry=f"{expiry_days}D",
            legs=[leg1, leg2],
            net_debit=net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakevens,
            risk_reward_ratio=rr,
            net_delta=round(net_delta, 4),
            net_gamma=round(net_gamma, 6),
            net_theta=round(net_theta, 4),
            net_vega=round(net_vega, 4),
            agent_id=agent_id,
            entry_underlying_price=spot_price,
            current_underlying_price=spot_price,
            current_strategy_value=net_debit,
            stop_loss_amount=net_debit * 0.5,
            target_profit_amount=net_debit * 0.8,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def create_protective_put(
        underlying: str,
        spot_price: float,
        put_strike: float,
        expiry_days: int = 7,
        volatility: float = 0.14,
        lot_size: int = DEFAULT_LOT_SIZE,
        quantity: int = DEFAULT_LOT_SIZE,
        agent_id: str = "DEFENSIVE",
        snapshot_id: str = "",
    ) -> MultiLegStrategy:
        """
        Protective Put: Equity long + BUY OTM/ATM Put.
        Downside risk is strictly floor-limited at put_strike - premium.
        """
        T_years = max(0.001, expiry_days / 365.0)
        p = OptionsPricingEngine.calculate_price_and_greeks(
            spot=spot_price, strike=put_strike, time_to_expiry_years=T_years, volatility=volatility, is_call=False
        )
        prem = p["price"]

        p_inst = OptionInstrument(
            underlying=underlying, strike=put_strike, option_type=OptionType.PE,
            expiry=f"{expiry_days}D", lot_size=lot_size, model_price=prem,
            implied_volatility=volatility, delta=p["delta"], gamma=p["gamma"], theta=p["theta"], vega=p["vega"]
        )

        leg = StrategyLeg(
            leg_id=f"LEG-1-{p_inst.symbol}", instrument=p_inst, side=LegSide.BUY,
            ratio=1, quantity=quantity, entry_price=prem, current_price=prem
        )

        net_debit = round(prem * quantity, 2)
        downside_stock_loss = max(0.0, spot_price - put_strike) * quantity
        max_loss = round(downside_stock_loss + net_debit, 2)
        max_profit = round(spot_price * 0.10 * quantity, 2)
        breakeven = [spot_price + prem]
        rr = round(max_profit / max_loss, 2) if max_loss > 0 else 2.0

        net_delta = (1.0 + p["delta"]) * quantity  # Stock delta (+1) + put delta (negative)
        net_gamma = p["gamma"] * quantity
        net_theta = p["theta"] * quantity
        net_vega = p["vega"] * quantity

        strat_id = f"STRAT-PROT-{underlying.replace('.NS', '')}-{int(put_strike)}-{snapshot_id[:6] or 'GEN'}"
        return MultiLegStrategy(
            strategy_id=strat_id,
            strategy_type=StrategyType.PROTECTIVE_PUT,
            underlying=underlying,
            expiry=f"{expiry_days}D",
            legs=[leg],
            net_debit=net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakeven,
            risk_reward_ratio=rr,
            net_delta=round(net_delta, 4),
            net_gamma=round(net_gamma, 6),
            net_theta=round(net_theta, 4),
            net_vega=round(net_vega, 4),
            agent_id=agent_id,
            entry_underlying_price=spot_price,
            current_underlying_price=spot_price,
            current_strategy_value=net_debit,
            stop_loss_amount=max_loss,
            target_profit_amount=max_profit,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def generate_payoff_points(
        strategy: MultiLegStrategy,
        spot_center: Optional[float] = None,
        pct_range: float = 4.0,
        num_points: int = 17,
    ) -> List[Dict[str, float]]:
        """
        Generates deterministic (spot, pnl) points for the options payoff chart.
        """
        center = spot_center or strategy.entry_underlying_price
        if center <= 0:
            center = 25000.0

        min_spot = center * (1.0 - pct_range / 100.0)
        max_spot = center * (1.0 + pct_range / 100.0)
        step = (max_spot - min_spot) / max(1, num_points - 1)

        points = []
        for i in range(num_points):
            s = round(min_spot + (i * step), 1)
            payoff = strategy.calculate_payoff_at(s)
            points.append({
                "spot": s,
                "payoff": round(payoff, 2),
                "is_atm": abs(s - center) < (step / 2.0),
            })
        return points


class OptionsStrategySelector:
    """
    Deterministic rule-based selection of appropriate options strategy
    based on agent market conviction, expected move, and volatility regime.
    """

    @staticmethod
    def select_strategy(
        underlying: str,
        spot_price: float,
        directional_bias: str,      # BULLISH, BEARISH, VOLATILE, DEFENSIVE
        expected_move_pct: float,
        confidence: float,
        volatility: float = 0.14,
        strike_step: float = 50.0,
        lot_size: int = DEFAULT_LOT_SIZE,
        agent_id: str = "ALPHA",
        snapshot_id: str = "",
    ) -> Optional[MultiLegStrategy]:
        """
        Returns a constructed MultiLegStrategy or None if no setup passes criteria.
        """
        if confidence < 60.0 or abs(expected_move_pct) < 0.3:
            return None  # NO_TRADE condition

        atm_strike = round(spot_price / strike_step) * strike_step

        if directional_bias == "BULLISH":
            if abs(expected_move_pct) >= 2.0:
                # Strong breakout: Long Call
                return OptionsStrategyBuilder.create_long_call(
                    underlying=underlying, spot_price=spot_price, strike=atm_strike,
                    volatility=volatility, lot_size=lot_size, agent_id=agent_id, snapshot_id=snapshot_id
                )
            else:
                # Moderate move: Bull Call Spread (ATM BUY, OTM SELL)
                buy_k = atm_strike
                sell_k = atm_strike + (strike_step * 2)
                return OptionsStrategyBuilder.create_bull_call_spread(
                    underlying=underlying, spot_price=spot_price, buy_strike=buy_k, sell_strike=sell_k,
                    volatility=volatility, lot_size=lot_size, agent_id=agent_id, snapshot_id=snapshot_id
                )

        elif directional_bias == "BEARISH":
            if abs(expected_move_pct) >= 2.0:
                # Strong breakdown: Long Put
                return OptionsStrategyBuilder.create_long_put(
                    underlying=underlying, spot_price=spot_price, strike=atm_strike,
                    volatility=volatility, lot_size=lot_size, agent_id=agent_id, snapshot_id=snapshot_id
                )
            else:
                # Moderate bearish move: Bear Put Spread
                buy_k = atm_strike
                sell_k = atm_strike - (strike_step * 2)
                return OptionsStrategyBuilder.create_bear_put_spread(
                    underlying=underlying, spot_price=spot_price, buy_strike=buy_k, sell_strike=sell_k,
                    volatility=volatility, lot_size=lot_size, agent_id=agent_id, snapshot_id=snapshot_id
                )

        elif directional_bias == "VOLATILE":
            # Event expected (earnings or macro event): Long Straddle or Strangle
            if volatility < 0.18:
                return OptionsStrategyBuilder.create_long_straddle(
                    underlying=underlying, spot_price=spot_price, strike=atm_strike,
                    volatility=volatility, lot_size=lot_size, agent_id=agent_id, snapshot_id=snapshot_id
                )
            else:
                # High IV: Long Strangle
                put_k = atm_strike - strike_step
                call_k = atm_strike + strike_step
                return OptionsStrategyBuilder.create_long_strangle(
                    underlying=underlying, spot_price=spot_price, put_strike=put_k, call_strike=call_k,
                    volatility=volatility, lot_size=lot_size, agent_id=agent_id, snapshot_id=snapshot_id
                )

        elif directional_bias == "DEFENSIVE":
            # Downside protection: Protective Put
            put_k = atm_strike - strike_step
            return OptionsStrategyBuilder.create_protective_put(
                underlying=underlying, spot_price=spot_price, put_strike=put_k,
                volatility=volatility, lot_size=lot_size, agent_id=agent_id, snapshot_id=snapshot_id
            )

        return None
