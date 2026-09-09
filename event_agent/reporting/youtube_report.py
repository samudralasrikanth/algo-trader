# =============================================================================
# event_agent/reporting/youtube_report.py — YouTube Transparency Script Generator
# =============================================================================
"""
Formats transparent video scripts and public summaries for YouTube.
Strictly downstream: never feeds back into or influences prediction algorithms.
Prominently features losing trades and forensic root causes to educate viewers.
"""

from typing import Any, Dict, List, Optional, Union
from .web_export import build_web_payload


def generate_youtube_script(payload_or_audits: Union[Dict[str, Any], List[Dict[str, Any]]]) -> str:
    """Generate structured YouTube video script with losers featured first."""
    if isinstance(payload_or_audits, list):
        web_payload = build_web_payload(audit_records=payload_or_audits)
    else:
        web_payload = payload_or_audits

    port = web_payload.get("portfolio", {})
    baselines = web_payload.get("vs_baselines", {})
    failed = web_payload.get("failed_trades_prominent", [])
    successes = web_payload.get("successful_trades", [])
    regime = web_payload.get("regime", {})
    b_nifty = baselines.get("nifty_buy_and_hold", {})

    script = []
    script.append("===============================================================================")
    script.append("YOUTUBE SCRIPT: NIFTY 50 QUANT PAPER TRADING EXPERIMENT (DAILY FORENSIC AUDIT)")
    script.append("===============================================================================\n")

    script.append("[SECTION 1: INTRO & MANDATORY DISCLAIMER]")
    script.append(f"'Welcome back to our quantitative trading experiment where we audit an algorithmic agent")
    script.append(f"predicting the Nifty 50. Mandatory disclaimer: This is for academic research and code transparency only,")
    script.append(f"never financial advice. Today our paper portfolio stands at ₹{port.get('current_capital', 1000000.0):,.0f},")
    script.append(f"an overall return of {port.get('return_pct', 0.0):+.2f}% vs the Nifty Buy & Hold benchmark at {b_nifty.get('return_pct', 0.0):+.2f}%.\n")

    script.append("[SECTION 2: TRANSPARENCY FIRST — TODAY'S BIGGEST LOSERS]")
    script.append("'As always, we review our worst mistakes first before looking at any winning trades.'")
    if failed:
        for i, f in enumerate(failed[:3], 1):
            script.append(f"Loss #{i}: {f.get('short_name')}")
            script.append(f"  - What the model predicted: {f.get('predicted_direction')} ({f.get('predicted_pct'):+.2f}%)")
            script.append(f"  - What actually happened: {f.get('actual_direction')} ({f.get('actual_pct'):+.2f}%)")
            script.append(f"  - Realized loss: ₹{abs(f.get('pnl', 0.0)):,.2f}")
            script.append(f"  - Forensic failure code: {f.get('primary_failure_code')} ({f.get('primary_category')})")
            script.append(f"  - Root cause: {f.get('diagnostic_explanation')}\n")
    else:
        script.append("'No losing trades occurred in today's execution window.'\n")

    script.append("[SECTION 3: TODAY'S WINNERS & CAPTURED CATALYSTS]")
    if successes:
        for i, s in enumerate(successes[:3], 1):
            script.append(f"Win #{i}: {s.get('short_name')}")
            script.append(f"  - Move: {s.get('actual_direction')} {s.get('actual_pct'):+.2f}% (P&L: ₹{s.get('pnl'):,.2f})")
            script.append(f"  - Catalyst: {s.get('diagnostic_explanation')}\n")

    script.append("[SECTION 4: 8-DIMENSION REGIME & TOMORROW'S PREDICTIONS]")
    script.append(f"'Heading into tomorrow, our 8-dimension regime detector classifies the market as {regime.get('composite_regime')}.")
    script.append(f"Risk regime is {regime.get('dimensions', {}).get('risk')}, with volatility {regime.get('dimensions', {}).get('volatility')}.")
    script.append(f"All 10 prediction snapshots and 5 baseline predictions are already locked into our immutable database.")
    script.append(f"Check the link in the description for the live Netlify dashboard and GitHub code.'\n")

    return "\n".join(script)
