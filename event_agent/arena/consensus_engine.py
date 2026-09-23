# =============================================================================
# event_agent/arena/consensus_engine.py — 50-Stock Market Analytics & Consensus
# =============================================================================
"""
Shared Market Analytics & Multi-Agent Consensus Engine for V3.2 Arena:
1. Generates the unified, immutable 50-stock market snapshot.
2. Queries all 5 agents on the exact same snapshot.
3. Computes the Agent Consensus Matrix across all 50 stocks (e.g. '3 BUY • 1 NO TRADE • 1 SELL').
4. Identifies top consensus opportunities, high divergence stocks, and macro regime alignment.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import NIFTY50_UNIVERSE
from .models import InstrumentType, ProposedTrade, TradeAction, TradeDirection

logger = logging.getLogger(__name__)

DEFAULT_STOCK_PRICES: Dict[str, float] = {
    "RELIANCE.NS": 1287.0,
    "TCS.NS": 4120.0,
    "HDFCBANK.NS": 1640.0,
    "ICICIBANK.NS": 1215.0,
    "INFY.NS": 1835.0,
    "BHARTIARTL.NS": 1590.0,
    "SBIN.NS": 815.0,
    "LT.NS": 3650.0,
    "ITC.NS": 490.0,
    "MARUTI.NS": 13376.0,
    "HINDUNILVR.NS": 2820.0,
    "KOTAKBANK.NS": 1780.0,
    "AXISBANK.NS": 1160.0,
    "ASIANPAINT.NS": 2850.0,
    "BAJFINANCE.NS": 7320.0,
    "TITAN.NS": 3480.0,
    "SUNPHARMA.NS": 1820.0,
    "TATAMOTORS.NS": 980.0,
    "NTPC.NS": 410.0,
    "POWERGRID.NS": 330.0,
}


class ConsensusEngine:
    """
    Computes market snapshots and consensus decisions across all 50 Nifty stocks.
    """

    @staticmethod
    def generate_market_snapshot(
        market_date: str,
        predictions: Optional[List[Dict[str, Any]]] = None,
        regime_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Produce the immutable 50-stock market snapshot.
        If predictions are supplied (e.g. from run_night_forecast), they are mapped to stocks.
        Any remaining stocks in NIFTY50_UNIVERSE are synthesized with PIT metadata.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        pred_map = {p.get("symbol"): p for p in (predictions or [])}

        if regime_data is None:
            regime_data = {
                "composite": 0.05,
                "label": "NEUTRAL",
                "dimensions": {
                    "risk": "NEUTRAL",
                    "monetary": "STABLE",
                    "inflation": "MODERATE",
                    "growth": "EXPANSION",
                    "volatility": "NORMAL",
                },
            }

        stocks: Dict[str, Any] = {}
        from event_agent.fundamentals.market_lens_provider import MarketLensProvider
        from event_agent.fundamentals.fundamental_score import FundamentalScoreEngine
        lens_provider = MarketLensProvider()
        now_dt = datetime.now(timezone.utc)
        fund_snapshots_map = {}
        sorted_keys = sorted(NIFTY50_UNIVERSE.keys())

        for sym in sorted_keys:
            meta = NIFTY50_UNIVERSE[sym]
            pred = pred_map.get(sym)

            if pred:
                base_price = float(pred.get("base_price", DEFAULT_STOCK_PRICES.get(sym, 1000.0)))
                pred_1d_pct = float(pred.get("expected_1d_pct", pred.get("predicted_1d_pct", 0.0)))
                conviction = float(pred.get("conviction", 55.0))
                catalysts = pred.get("occurred_events", []) or pred.get("active_catalysts", [])
                sentiment = float(pred.get("stock_sentiment", 0.0))
                vol_5d = float(pred.get("volatility_5d", 0.015))
                action = str(pred.get("action", "NO_TRADE"))
                direction = str(pred.get("direction", "NEUTRAL"))
                target = float(pred.get("target_price", pred.get("predicted_1d_target", base_price)))
                stop = float(pred.get("stop_loss", base_price * 0.98))
                baselines = pred.get("baselines", {})
                fund_snap = pred.get("fundamental_snapshot")
            else:
                base_price = DEFAULT_STOCK_PRICES.get(sym, 1000.0)
                pred_1d_pct = 0.0
                conviction = 50.0
                catalysts = []
                sentiment = 0.0
                vol_5d = 0.015
                action = "NO_TRADE"
                direction = "NEUTRAL"
                target = base_price
                stop = base_price * 0.98
                baselines = {}
                fund_snap = None

            if not fund_snap:
                fund_snap = lens_provider.get_snapshot(sym, as_of_dt=now_dt)

            if hasattr(fund_snap, "to_dict"):
                fund_snapshots_map[sym] = fund_snap
                fund_dict = fund_snap.to_dict()
            else:
                fund_dict = fund_snap or {}

            stocks[sym] = {
                "symbol": sym,
                "name": meta.get("name", sym),
                "short_name": meta.get("name", sym).split()[0],
                "sector": meta.get("sector", "Diversified"),
                "beta": float(meta.get("beta", 1.0)),
                "base_price": base_price,
                "predicted_1d_pct": pred_1d_pct,
                "conviction": conviction,
                "volatility_5d": vol_5d,
                "catalysts": catalysts,
                "stock_sentiment": sentiment,
                "action": action,
                "direction": direction,
                "target_price": target,
                "stop_loss": stop,
                "baselines": baselines,
                "fundamental_snapshot": fund_dict,
                "fundamentals": fund_dict,
                "key_drivers": meta.get("key_drivers", []),
                "effective_from": meta.get("effective_from"),
                "effective_to": meta.get("effective_to"),
            }


        # Also include any custom/index prediction passed in predictions (e.g. NIFTY50)
        for p_sym, p_data in pred_map.items():
            if p_sym and p_sym not in stocks:
                stocks[p_sym] = {
                    "symbol": p_sym,
                    "name": p_data.get("name", p_sym),
                    "short_name": p_sym,
                    "sector": p_data.get("sector", "Index"),
                    "beta": 1.0,
                    "base_price": float(p_data.get("base_price", 25000.0)),
                    "predicted_1d_pct": float(p_data.get("predicted_1d_pct", 0.0)),
                    "conviction": float(p_data.get("conviction", 60.0)),
                    "volatility_5d": 0.14,
                    "catalysts": p_data.get("occurred_events", p_data.get("catalysts", [])),
                    "stock_sentiment": float(p_data.get("stock_sentiment", 0.0)),
                    "action": p_data.get("action", "BUY"),
                    "direction": p_data.get("direction", "BULLISH"),
                    "target_price": float(p_data.get("target_price", 0.0)),
                    "stop_loss": float(p_data.get("stop_loss", 0.0)),
                    "baselines": {},
                    "key_drivers": [],
                    "effective_from": None,
                    "effective_to": None,
                }

        # Deterministic snapshot hash
        payload_data = [
            market_date,
            regime_data.get("label", "NEUTRAL"),
            [(s, stocks[s]["base_price"], stocks[s]["predicted_1d_pct"]) for s in sorted_keys],
        ]
        snapshot_hash = hashlib.sha256(json.dumps(payload_data, sort_keys=True).encode()).hexdigest()

        # Compute Nifty 50 fundamental breadth and regime
        fund_breadth = FundamentalScoreEngine.compute_market_breadth_and_regime(fund_snapshots_map)

        return {
            "snapshot_id": snapshot_hash,
            "market_date": market_date,
            "timestamp": now_str,
            "regime": regime_data,
            "fundamental_breadth": fund_breadth,
            "fundamental_regime": fund_breadth["fundamental_regime"],
            "stocks": stocks,
            "universe_count": len(stocks),
        }

    @staticmethod
    def compute_consensus(
        market_snapshot: Dict[str, Any],
        agent_proposals: Dict[str, List[ProposedTrade]],
    ) -> Dict[str, Any]:
        """
        Build the consensus matrix across all 50 stocks from the 5 agents.
        """
        stocks = market_snapshot.get("stocks", {})
        all_agent_ids = ["ALPHA", "MOMENTUM", "MACRO", "DEFENSIVE", "CONTRARIAN"]

        # Map: agent_id -> {symbol: ProposedTrade}
        agent_symbol_trade: Dict[str, Dict[str, ProposedTrade]] = {aid: {} for aid in all_agent_ids}
        for aid, proposals in agent_proposals.items():
            for p in proposals:
                if p.action != TradeAction.NO_TRADE:
                    agent_symbol_trade.setdefault(aid, {})[p.symbol] = p

        stock_consensus_list = []
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        divergent_stocks = []

        for symbol, sdata in stocks.items():
            votes = {}
            buys = 0
            sells = 0
            no_trades = 0

            for aid in all_agent_ids:
                trade = agent_symbol_trade.get(aid, {}).get(symbol)
                if trade:
                    if trade.action == TradeAction.BUY:
                        stance = "BUY"
                        buys += 1
                    elif trade.action == TradeAction.SELL:
                        stance = "SELL"
                        sells += 1
                    else:
                        stance = "NO_TRADE"
                        no_trades += 1
                else:
                    stance = "NO_TRADE"
                    no_trades += 1
                votes[aid] = stance

            # Determine aggregate consensus
            if buys >= 3 and sells == 0:
                consensus_label = "STRONG_BULLISH"
                bullish_count += 1
            elif buys >= 2 and sells == 0:
                consensus_label = "MODERATE_BULLISH"
                bullish_count += 1
            elif sells >= 3 and buys == 0:
                consensus_label = "STRONG_BEARISH"
                bearish_count += 1
            elif sells >= 2 and buys == 0:
                consensus_label = "MODERATE_BEARISH"
                bearish_count += 1
            elif buys >= 1 and sells >= 1:
                consensus_label = "DIVIDED"
                divergent_stocks.append(symbol)
            else:
                consensus_label = "NEUTRAL"
                neutral_count += 1

            # Format human string: "3 BUY • 1 NO TRADE • 1 SELL"
            parts = []
            if buys > 0:
                parts.append(f"{buys} BUY")
            if no_trades > 0:
                parts.append(f"{no_trades} NO TRADE")
            if sells > 0:
                parts.append(f"{sells} SELL")
            consensus_str = " • ".join(parts) if parts else "5 NO TRADE"

            # Compute average conviction among active voters
            active_convictions = []
            for aid in all_agent_ids:
                trade = agent_symbol_trade.get(aid, {}).get(symbol)
                if trade and trade.action != TradeAction.NO_TRADE:
                    active_convictions.append(trade.confidence)
            avg_conviction = (
                round(sum(active_convictions) / len(active_convictions), 1)
                if active_convictions
                else round(float(sdata.get("conviction", 50.0)), 1)
            )

            stock_consensus_list.append({
                "symbol": symbol,
                "name": sdata.get("name", symbol),
                "short_name": sdata.get("short_name", symbol),
                "sector": sdata.get("sector", "Diversified"),
                "beta": sdata.get("beta", 1.0),
                "base_price": sdata.get("base_price", 0.0),
                "predicted_1d_pct": sdata.get("predicted_1d_pct", 0.0),
                "target_price": sdata.get("target_price", sdata.get("base_price", 0.0)),
                "stop_loss": sdata.get("stop_loss", sdata.get("base_price", 0.0) * 0.98),
                "consensus_label": consensus_label,
                "consensus_text": consensus_str,
                "buys": buys,
                "sells": sells,
                "no_trades": no_trades,
                "agent_votes": votes,
                "avg_conviction": avg_conviction,
                "catalysts_count": len(sdata.get("catalysts", [])),
                "stock_sentiment": sdata.get("stock_sentiment", 0.0),
            })

        # Sort picks by agreement strength (buys desc, then sells desc, then conviction)
        stock_consensus_list.sort(key=lambda x: (x["buys"] - x["sells"], x["avg_conviction"]), reverse=True)

        top_buys = [s for s in stock_consensus_list if s["buys"] >= 2][:5]
        top_sells = [s for s in stock_consensus_list if s["sells"] >= 2][:5]

        summary = {
            "total_stocks": len(stocks),
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
            "divergent_count": len(divergent_stocks),
            "top_bullish_picks": [s["symbol"] for s in top_buys],
            "top_bearish_picks": [s["symbol"] for s in top_sells],
            "divergent_symbols": divergent_stocks,
        }

        return {
            "snapshot_id": market_snapshot.get("snapshot_id", ""),
            "market_date": market_snapshot.get("market_date", ""),
            "stocks": stock_consensus_list,
            "summary": summary,
        }
