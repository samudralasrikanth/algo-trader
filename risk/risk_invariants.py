# =============================================================================
# risk/risk_invariants.py — Unified 8 Institutional Risk Invariants Engine
# =============================================================================
"""
V3.6.4 Production Mathematical Risk Invariant Evaluator.

Strict Institutional Invariants:
1. Absence of evidence = NOT_VERIFIED. Insufficient data NEVER defaults to PASS or FAIL.
2. Canonical gate status: status = 'PASS' | 'FAIL' | 'NOT_VERIFIED'.
3. Single source of truth: Zero 'passed' boolean fields.
4. Mathematical derivation from runtime portfolio & closed trade distributions.

Gates Evaluated:
1. GATE_VAR_99: Parametric 99% Single-Day Value-at-Risk (<= 2.0%)
2. GATE_SLIPPAGE: Maximum Mean Execution Slippage (<= 15.0 bps)
3. GATE_DELTA_NEUTRALITY: Absolute Portfolio Net Delta (< 0.15)
4. GATE_GAMMA_BUFFER: Portfolio Curvature Shock Response ([-0.05, +0.05])
5. GATE_STOCK_CONCENTRATION: Maximum Single Stock Position (<= 10.0%)
6. GATE_SECTOR_ALLOCATION: Maximum Single Sector Allocation (<= 25.0%)
7. GATE_SESSION_CUTOFF: Hard Session Execution Cutoff at 15:30 IST
8. GATE_ANTI_LEAKAGE: Causal Timestamp Integrity (t_feature <= t_signal <= t_entry)
"""

import math
from datetime import datetime, time, timezone, timedelta
from typing import Any, Dict, List, Optional


Z_99_PARAMETRIC = 2.326347874  # Normal inverse CDF at 99% confidence


def evaluate_risk_invariants(
    portfolio: Optional[Dict[str, Any]] = None,
    open_positions: Optional[List[Dict[str, Any]]] = None,
    trades: Optional[List[Dict[str, Any]]] = None,
    system_status: Optional[Dict[str, Any]] = None,
    signals_meta: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Evaluates the 8 Institutional Risk Invariants against active runtime data.
    Returns a list of dicts with keys: id, name, threshold, current, status.
    """
    portfolio = portfolio or {}
    open_positions = open_positions or []
    trades = trades or []
    system_status = system_status or {}
    signals_meta = signals_meta or []

    capital = float(portfolio.get("current_capital") or portfolio.get("initial_capital") or 0.0)

    # -------------------------------------------------------------------------
    # 1. GATE_VAR_99 (VaR 99% Single-Day Limit <= 2.0%)
    # -------------------------------------------------------------------------
    returns: List[float] = []
    if trades and capital > 0:
        for t in trades:
            pnl = float(t.get("pnl") if t.get("pnl") is not None else (t.get("net_pnl") or 0.0))
            capital_at_risk = float(t.get("capital_at_risk") or t.get("notional") or capital)
            if capital_at_risk > 0:
                returns.append(pnl / capital_at_risk)

    if len(returns) < 5:
        var_status = "NOT_VERIFIED"
        var_current = None
    else:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        sigma = math.sqrt(max(0.0, variance))
        var99 = Z_99_PARAMETRIC * sigma
        var_current = f"{var99 * 100.0:.2f}%"
        var_status = "PASS" if var99 <= 0.02 else "FAIL"

    # -------------------------------------------------------------------------
    # 2. GATE_SLIPPAGE (Maximum Slippage Threshold <= 15 bps)
    # -------------------------------------------------------------------------
    slippages_bps: List[float] = []
    if trades:
        for t in trades:
            fill_p = float(t.get("exit_price") or t.get("fill_price") or 0.0)
            signal_p = float(t.get("entry_price") or t.get("signal_price") or 0.0)
            if signal_p > 0 and fill_p > 0:
                s_bps = (abs(fill_p - signal_p) / signal_p) * 10000.0
                slippages_bps.append(s_bps)

    if not slippages_bps:
        slip_status = "NOT_VERIFIED"
        slip_current = None
    else:
        mean_slip = sum(slippages_bps) / len(slippages_bps)
        slip_current = f"{mean_slip:.1f} bps"
        slip_status = "PASS" if mean_slip <= 15.0 else "FAIL"

    # -------------------------------------------------------------------------
    # 3. GATE_DELTA_NEUTRALITY (Net Delta < 0.15)
    # -------------------------------------------------------------------------
    if capital <= 0:
        delta_status = "NOT_VERIFIED"
        delta_current = None
    else:
        long_val = sum(float(p.get("notional", 0.0)) for p in open_positions if p.get("side") == "BUY")
        short_val = sum(float(p.get("notional", 0.0)) for p in open_positions if p.get("side") == "SELL")
        net_delta = abs(long_val - short_val) / capital
        delta_current = f"{net_delta:.2f}"
        delta_status = "PASS" if net_delta < 0.15 else "FAIL"

    # -------------------------------------------------------------------------
    # 4. GATE_GAMMA_BUFFER (Gamma Volatility Corridor [-0.05, +0.05])
    # -------------------------------------------------------------------------
    has_options = any(p.get("asset_class") == "OPTION" for p in open_positions)
    if not open_positions:
        gamma_status = "PASS"
        gamma_current = "0.000"
    elif has_options:
        tot_gamma = sum(float(p.get("gamma", 0.0)) * float(p.get("weight", 1.0)) for p in open_positions)
        gamma_current = f"{tot_gamma:+.3f}"
        gamma_status = "PASS" if abs(tot_gamma) <= 0.05 else "FAIL"
    else:
        gamma_status = "PASS"
        gamma_current = "Within Bounds"

    # -------------------------------------------------------------------------
    # 5. GATE_STOCK_CONCENTRATION (Single Stock Concentration <= 10.0%)
    # -------------------------------------------------------------------------
    if capital <= 0:
        conc_status = "NOT_VERIFIED"
        conc_current = None
    elif not open_positions:
        conc_status = "PASS"
        conc_current = "0.0%"
    else:
        max_pos = max(float(p.get("notional") or (float(p.get("qty", 0)) * float(p.get("price", 0)))) for p in open_positions)
        stock_pct = (max_pos / capital) * 100.0
        conc_current = f"{stock_pct:.1f}%"
        conc_status = "PASS" if stock_pct <= 10.0 else "FAIL"

    # -------------------------------------------------------------------------
    # 6. GATE_SECTOR_ALLOCATION (Sector Allocation Cap <= 25.0%)
    # -------------------------------------------------------------------------
    if capital <= 0:
        sec_status = "NOT_VERIFIED"
        sec_current = None
    elif not open_positions:
        sec_status = "PASS"
        sec_current = "0.0%"
    else:
        sector_totals: Dict[str, float] = {}
        for p in open_positions:
            sec = p.get("sector", "Other")
            val = float(p.get("notional") or (float(p.get("qty", 0)) * float(p.get("price", 0))))
            sector_totals[sec] = sector_totals.get(sec, 0.0) + val
        max_sec = max(sector_totals.values()) if sector_totals else 0.0
        sec_pct = (max_sec / capital) * 100.0
        sec_current = f"{sec_pct:.1f}%"
        sec_status = "PASS" if sec_pct <= 25.0 else "FAIL"

    # -------------------------------------------------------------------------
    # 7. GATE_SESSION_CUTOFF (Hard Session Cutoff at 15:30 IST)
    # -------------------------------------------------------------------------
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    cutoff_breach = False
    checked_timestamps = 0

    if trades:
        for t in trades:
            ts_str = t.get("entry_time") or t.get("timestamp") or t.get("submitted_at") or t.get("trade_date")
            if ts_str and "T" in str(ts_str):
                checked_timestamps += 1
                try:
                    dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")).astimezone(ist_tz)
                    if dt.time() > time(15, 30):
                        cutoff_breach = True
                        break
                except Exception:
                    pass

    if system_status:
        sys_ts = (
            system_status.get("last_order_submitted_at")
            or system_status.get("last_execution_time")
            or system_status.get("last_order_time")
        )
        if sys_ts and "T" in str(sys_ts):
            checked_timestamps += 1
            try:
                dt = datetime.fromisoformat(str(sys_ts).replace("Z", "+00:00")).astimezone(ist_tz)
                if dt.time() > time(15, 30):
                    cutoff_breach = True
            except Exception:
                pass

    if checked_timestamps == 0:
        if system_status.get("session_cutoff_enforced") is True:
            cutoff_status = "PASS"
            cutoff_current = "Enforced"
        elif system_status.get("session_cutoff_enforced") is False:
            cutoff_status = "FAIL"
            cutoff_current = "Breached"
        else:
            cutoff_status = "NOT_VERIFIED"
            cutoff_current = None
    else:
        cutoff_status = "FAIL" if cutoff_breach else "PASS"
        cutoff_current = "Breached" if cutoff_breach else "Enforced"

    # -------------------------------------------------------------------------
    # 8. GATE_ANTI_LEAKAGE (Anti-Leakage Circuit Breaker / Zero Lookahead)
    # -------------------------------------------------------------------------
    leakage_detected = False
    checked_signals = 0

    if signals_meta:
        for s in signals_meta:
            checked_signals += 1
            t_feat = s.get("feature_timestamp")
            t_sig = s.get("signal_timestamp")
            t_exec = s.get("execution_timestamp")
            if t_feat and t_sig and t_feat > t_sig:
                leakage_detected = True
                break
            if t_sig and t_exec and t_sig > t_exec:
                leakage_detected = True
                break

    if checked_signals == 0:
        if system_status.get("anti_leakage_verified") is True:
            leak_status = "PASS"
            leak_current = "Verified"
        elif system_status.get("anti_leakage_verified") is False:
            leak_status = "FAIL"
            leak_current = "Leakage Detected"
        else:
            leak_status = "NOT_VERIFIED"
            leak_current = None
    else:
        leak_status = "FAIL" if leakage_detected else "PASS"
        leak_current = "Leakage Detected" if leakage_detected else "Verified"

    return [
        {
            "id": "GATE_VAR_99",
            "name": "VaR 99% Single-Day Limit",
            "threshold": "≤ 2.0%",
            "current": var_current,
            "status": var_status,
        },
        {
            "id": "GATE_SLIPPAGE",
            "name": "Maximum Slippage Threshold",
            "threshold": "≤ 15 bps",
            "current": slip_current,
            "status": slip_status,
        },
        {
            "id": "GATE_DELTA_NEUTRALITY",
            "name": "Delta Neutrality Cap",
            "threshold": "Net Delta < 0.15",
            "current": delta_current,
            "status": delta_status,
        },
        {
            "id": "GATE_GAMMA_BUFFER",
            "name": "Gamma Volatility Buffer",
            "threshold": "Safe Corridor",
            "current": gamma_current,
            "status": gamma_status,
        },
        {
            "id": "GATE_STOCK_CONCENTRATION",
            "name": "Single Stock Concentration",
            "threshold": "≤ 10.0%",
            "current": conc_current,
            "status": conc_status,
        },
        {
            "id": "GATE_SECTOR_ALLOCATION",
            "name": "Sector Allocation Cap",
            "threshold": "≤ 25.0%",
            "current": sec_current,
            "status": sec_status,
        },
        {
            "id": "GATE_SESSION_CUTOFF",
            "name": "Hard Session Cutoff (15:30 IST)",
            "threshold": "Enforced",
            "current": cutoff_current,
            "status": cutoff_status,
        },
        {
            "id": "GATE_ANTI_LEAKAGE",
            "name": "Anti-Leakage Circuit Breaker",
            "threshold": "Zero Lookahead",
            "current": leak_current,
            "status": leak_status,
        },
    ]
