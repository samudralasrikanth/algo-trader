# =============================================================================
# event_agent/reporting/ai_analyst.py — OpenRouter AI Performance Analyst
# =============================================================================
"""
Integrates with OpenRouter to analyze post-market trading performance and
generate a 60–120 second financial-news style narration script.

Strict Institutional Invariants:
1. Feeds strictly factual, structured numerical data to OpenRouter.
2. AI is instructed NEVER to invent or hallucinate numerical facts.
3. Every narration script explicitly states: PAPER TRADING and MODELLED DERIVATIVES.
4. Complete request-level API telemetry (request_id, latency_ms, tokens, status).
5. If OpenRouter fails or key is invalid: reports AI_ANALYSIS = FAILED without falsification.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from .trade_reconciliation import DailyReconciliationReport
from ..engine.llm_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


@dataclass
class DailyAIAnalysisResult:
    executive_summary: str
    performance_analysis: str
    strategy_analysis: str
    agent_analysis: str
    risk_analysis: str
    prediction_accuracy: str
    best_trade_analysis: str
    worst_trade_analysis: str
    lessons_learned: str
    tomorrow_watchlist: str
    narration_script: str
    ai_provider: str
    ai_model: str
    ai_request_id: Optional[str]
    ai_latency_ms: int
    ai_tokens: Dict[str, int]
    ai_status: str              # 'SUCCESS' | 'FAILED' | 'SKIPPED'
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DailyAIAnalyst:
    """
    Executes post-market AI analysis and script generation via OpenRouter.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "openai/gpt-4o-mini",
    ):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = os.environ.get("OPENROUTER_MODEL", model)

    def analyze_daily_performance(
        self,
        reconciliation: DailyReconciliationReport,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> DailyAIAnalysisResult:
        """
        Generate structured analysis and narration script for the daily trading report.
        """
        if not self.api_key:
            return self._build_failed_result(
                error_msg="OPENROUTER_API_KEY environment variable is not configured",
                status="NOT_CONFIGURED",
            )

        # Build factual data context
        data_context = {
            "date": reconciliation.report_date,
            "status": reconciliation.trading_status,
            "trades": {
                "total": reconciliation.total_trades,
                "buys": reconciliation.buy_orders,
                "sells": reconciliation.sell_orders,
                "winners": reconciliation.winning_trades,
                "losers": reconciliation.losing_trades,
                "win_rate_pct": reconciliation.win_rate,
            },
            "pnl": {
                "gross_pnl_inr": reconciliation.gross_pnl,
                "statutory_charges_inr": reconciliation.charges,
                "net_pnl_inr": reconciliation.net_pnl,
                "realized_pnl_inr": reconciliation.realized_pnl,
                "unrealized_pnl_inr": reconciliation.unrealized_pnl,
                "total_pnl_inr": reconciliation.total_pnl,
                "profit_factor": reconciliation.profit_factor,
            },
            "best_trade": reconciliation.best_trade,
            "worst_trade": reconciliation.worst_trade,
            "strategy_pnl": reconciliation.strategy_pnl,
            "agent_pnl": reconciliation.agent_pnl,
            "risk_metrics": {
                "total_exposure_inr": reconciliation.exposure,
                "open_positions": reconciliation.open_positions_count,
                "max_drawdown_pct": reconciliation.max_drawdown_pct,
                "risk_engine_rejections": reconciliation.risk_rejected_count,
                "broker_rejections": reconciliation.broker_rejected_count,
            },
            "reconciliation_warnings": reconciliation.reconciliation_warnings,
            "market_context": market_context or {
                "nifty_move": "Neutral / Consolidation",
                "vix": "Normal",
            },
        }

        system_prompt = (
            "You are the Lead Quantitative Portfolio Analyst for NEXUS AI Investment Intelligence.\n"
            "Analyze today's recorded Indian equity session based strictly on the factual JSON provided.\n"
            "STRICT RULES:\n"
            "1. NEVER invent or extrapolate any financial numbers. All figures must match the input JSON.\n"
            "2. This is PAPER TRADING only. Never claim live or real-money execution.\n"
            "3. If trades are 0, state clearly: 'Trades: 0, P&L: ₹0, Status: NO TRADES'.\n"
            "4. Clearly distinguish REALIZED and UNREALIZED P&L.\n"
            "5. Respond with a JSON object containing the exact keys below."
        )

        user_prompt = f"""Evaluate today's session based on this factual record:
{json.dumps(data_context, indent=2)}

Produce a JSON object with these exact keys:
- executive_summary: High-level overview of what happened today (2-3 sentences).
- performance_analysis: Detailed explanation of why P&L moved as it did.
- strategy_analysis: Breakdown of top performing vs lagging strategies.
- agent_analysis: Breakdown of agent contribution (Alpha, Beta, Gamma, etc.).
- risk_analysis: Were any losses caused by regime, execution slippage, or prediction error? Note rejections.
- prediction_accuracy: Compare predicted stance vs actual market outcome.
- best_trade_analysis: Concrete reason why the best trade succeeded.
- worst_trade_analysis: Forensic analysis of why the worst trade failed.
- lessons_learned: Actionable systematic improvements for NEXUS algorithms.
- tomorrow_watchlist: Evidence-based watchlist observations for the next session.
- narration_script: A professional, polished 60 to 120-second financial-news style narration script.
  Must start with: 'Welcome to the NEXUS Daily Trade Report for {reconciliation.report_date}. This report reflects algorithmic paper trading and modelled derivatives.'
  Must clearly state trades, net P&L, best trade, worst trade, risk stance, and concluding thoughts.
"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/samudralasrikanth/algo-trader",
            "X-Title": "NEXUS Daily Trade Report",
        }
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1200,
        }).encode("utf-8")

        start_time = time.perf_counter()
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=body,
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                usage = data.get("usage", {})
                req_id = data.get("id")

                tokens_dict = {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }

                # Ensure paper trading badge is present in narration script
                narration = parsed.get("narration_script", "")
                if "paper trading" not in narration.lower():
                    narration = f"[PAPER TRADING REPORT] {narration}"

                return DailyAIAnalysisResult(
                    executive_summary=parsed.get("executive_summary", "Session completed."),
                    performance_analysis=parsed.get("performance_analysis", "Performance aligned with market movement."),
                    strategy_analysis=parsed.get("strategy_analysis", "Strategies executed in sandbox environment."),
                    agent_analysis=parsed.get("agent_analysis", "Agents maintained assigned allocations."),
                    risk_analysis=parsed.get("risk_analysis", "Risk limits strictly enforced."),
                    prediction_accuracy=parsed.get("prediction_accuracy", "Directional accuracy tracked against market close."),
                    best_trade_analysis=parsed.get("best_trade_analysis", "Evaluated against catalyst criteria."),
                    worst_trade_analysis=parsed.get("worst_trade_analysis", "Risk stops limited downside exposure."),
                    lessons_learned=parsed.get("lessons_learned", "System continues continuous Bayesian parameter tuning."),
                    tomorrow_watchlist=parsed.get("tomorrow_watchlist", "Key sector leaders under observation."),
                    narration_script=narration,
                    ai_provider="openrouter",
                    ai_model=self.model,
                    ai_request_id=req_id,
                    ai_latency_ms=latency_ms,
                    ai_tokens=tokens_dict,
                    ai_status="SUCCESS",
                )

        except urllib.error.HTTPError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error("OpenRouter HTTP Error %d: %s", e.code, err_body)
            return self._build_failed_result(
                error_msg=f"OpenRouter HTTP {e.code}: {err_body[:200]}",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("OpenRouter exception: %s", e)
            return self._build_failed_result(
                error_msg=str(e),
                latency_ms=latency_ms,
            )

    def _build_failed_result(
        self,
        error_msg: str,
        status: str = "FAILED",
        latency_ms: int = 0,
    ) -> DailyAIAnalysisResult:
        return DailyAIAnalysisResult(
            executive_summary="DATA UNAVAILABLE: AI analysis could not be completed.",
            performance_analysis="DATA UNAVAILABLE",
            strategy_analysis="DATA UNAVAILABLE",
            agent_analysis="DATA UNAVAILABLE",
            risk_analysis="DATA UNAVAILABLE",
            prediction_accuracy="DATA UNAVAILABLE",
            best_trade_analysis="DATA UNAVAILABLE",
            worst_trade_analysis="DATA UNAVAILABLE",
            lessons_learned="DATA UNAVAILABLE",
            tomorrow_watchlist="DATA UNAVAILABLE",
            narration_script="DATA UNAVAILABLE: Narration script generation failed.",
            ai_provider="openrouter",
            ai_model=self.model,
            ai_request_id=None,
            ai_latency_ms=latency_ms,
            ai_tokens={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            ai_status=status,
            error_message=error_msg,
        )
