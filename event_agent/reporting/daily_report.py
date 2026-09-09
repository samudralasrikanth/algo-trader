# =============================================================================
# event_agent/reporting/daily_report.py — Daily Forensic & Performance Report
# =============================================================================
"""
Generates a markdown daily report for researchers and operators.
Prominently displays model failures, 18-code diagnostics, and baseline alpha.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from .web_export import build_web_payload


def generate_daily_markdown_report(
    payload_or_audits: Union[Dict[str, Any], List[Dict[str, Any]]],
) -> str:
    """Generate clean GitHub-Flavored Markdown daily report with failures first."""
    if isinstance(payload_or_audits, list):
        web_payload = build_web_payload(audit_records=payload_or_audits)
    else:
        web_payload = payload_or_audits

    meta = web_payload.get("metadata", {})
    port = web_payload.get("portfolio", {})
    baselines = web_payload.get("vs_baselines", {})
    regime = web_payload.get("regime", {})
    failed = web_payload.get("failed_trades_prominent", [])
    successes = web_payload.get("successful_trades", [])
    preds = web_payload.get("latest_predictions", [])
    v_rec = meta.get("version_record", {})

    lines = []
    lines.append("# 📊 Nifty 50 Quantitative Paper Trading — Daily Forensic Report")
    lines.append(f"**Generated**: {meta.get('generated_at', datetime.now().isoformat())} | **Model**: v{v_rec.get('model_version', '3.0.0')} (Regime: {v_rec.get('regime_version', 'R1')}, Weights: {v_rec.get('weights_version', 'W1.0')})\n")

    lines.append("> [!NOTE]")
    lines.append("> **Research & Transparency Only**. Numerical models and levels are 100% deterministic math. LLMs are used exclusively for text interpretation of corporate/macro news. Losses and model failures are prominently featured to eliminate survivorship bias.\n")

    # 1. Performance Overview
    lines.append("## 1. Portfolio Performance")
    lines.append("| Metric | Value | Benchmark (Nifty Buy & Hold) | Alpha |")
    lines.append("|:---|:---|:---|:---|")
    b_nifty = baselines.get("nifty_buy_and_hold", {})
    lines.append(f"| Current Capital | ₹{port.get('current_capital', 1000000.0):,.2f} | — | — |")
    lines.append(f"| Strategy Return | **{port.get('return_pct', 0.0):+.2f}%** | {b_nifty.get('return_pct', 0.0):+.2f}% | **{b_nifty.get('alpha', 0.0):+.2f}%** |")
    lines.append(f"| Trades (Wins/Losses) | {port.get('total_closed_trades', 0)} ({port.get('win_rate_pct', 0.0):.1f}% Win Rate) | — | — |")
    lines.append(f"| Profit Factor | {port.get('profit_factor', 1.0):.2f} | — | — |")
    lines.append(f"| Max Drawdown | {port.get('max_drawdown_pct', 0.0):.2f}% | — | — |\n")

    # 2. Baseline Comparison Table
    lines.append("## 2. Comparison Against All 5 Benchmark Baselines")
    lines.append("| Benchmark Model | Return % | Model Alpha | Description |")
    lines.append("|:---|:---|:---|:---|")
    for b_key, b_data in baselines.items():
        if b_key == "model":
            continue
        lines.append(f"| {b_data.get('name', b_key)} | {b_data.get('return_pct', 0.0):+.2f}% | **{b_data.get('alpha', 0.0):+.2f}%** | Independent benchmark hurdle |")
    lines.append("")

    # 3. Market Regime
    lines.append("## 3. Active 8-Dimension Market Regime")
    lines.append(f"**Composite Regime**: `{regime.get('composite_regime', 'NEUTRAL')}` (Score: {regime.get('composite_score', 0.0):+.2f}, Confidence: {regime.get('confidence', 70.0):.0f}%)")
    lines.append("```")
    dims = regime.get("dimensions", {})
    lines.append(f"Risk: {dims.get('risk', 'NEUTRAL')} | Monetary: {dims.get('monetary', 'NEUTRAL')} | Inflation: {dims.get('inflation', 'NEUTRAL')} | Growth: {dims.get('growth', 'NEUTRAL')}")
    lines.append(f"Liquidity: {dims.get('liquidity', 'NEUTRAL')} | Volatility: {dims.get('volatility', 'NORMAL')} | Geopolitical: {dims.get('geopolitical', 'STABLE')} | Earnings: {dims.get('earnings', 'NEUTRAL')}")
    lines.append("```\n")

    # 4. Forensic Audit (Losers Prominently First)
    lines.append("## 4. 🔍 Forensic Failure Audit (Losers Shown First)")
    if failed:
        for f in failed:
            lines.append(f"### ❌ {f.get('short_name', f.get('symbol'))} — FAILURE [{f.get('primary_failure_code')}: {f.get('primary_category')}]")
            lines.append(f"- **Predicted**: {f.get('predicted_direction')} ({f.get('predicted_pct', 0.0):+.2f}%)")
            lines.append(f"- **Actual Market Move**: {f.get('actual_direction')} ({f.get('actual_pct', 0.0):+.2f}%)")
            lines.append(f"- **Realized P&L**: ₹{f.get('pnl', 0.0):+.2f}")
            lines.append(f"- **Diagnostic Explanation**: {f.get('diagnostic_explanation')}")
            lines.append(f"- **Actionable Model Guidance**: {f.get('refactoring_suggestion')}\n")
    else:
        lines.append("*No trade failures recorded in recent sessions.*\n")

    # 5. Successful Trades
    lines.append("## 5. ✅ Captured Catalysts (Winning Trades)")
    if successes:
        for s in successes[:5]:
            lines.append(f"- **{s.get('short_name')}**: {s.get('actual_direction')} {s.get('actual_pct', 0.0):+.2f}% (P&L: ₹{s.get('pnl', 0.0):+.2f}) — {s.get('diagnostic_explanation')}")
    else:
        lines.append("*No winning trades to display.*")
    lines.append("")

    return "\n".join(lines)
