#!/usr/bin/env python3
"""
Test Suite for Phase G: Dashboard & Public Reporting (Losers Prominent)
"""
import json
from pathlib import Path
from event_agent.reporting.web_export import build_web_payload, export_to_web_app
from event_agent.reporting.daily_report import generate_daily_markdown_report
from event_agent.reporting.youtube_report import generate_youtube_script

def test_web_export_payload():
    print("--- Testing 1: Web Export Payload & Losers-First Ordering ---")
    payload = build_web_payload()
    
    assert "portfolio" in payload, "Missing portfolio in payload"
    assert "vs_baselines" in payload, "Missing vs_baselines in payload"
    assert "regime" in payload, "Missing regime in payload"
    assert "failed_trades_prominent" in payload, "Missing failed_trades_prominent in payload"
    assert "latest_predictions" in payload, "Missing latest_predictions in payload"
    assert "metadata" in payload, "Missing metadata in payload"
    
    # Verify baselines
    baselines = payload["vs_baselines"]
    assert "nifty_buy_and_hold" in baselines
    assert "momentum_5d" in baselines
    assert "previous_day" in baselines
    assert "random_deterministic" in baselines
    
    # Verify 8-dimension regime
    regime = payload["regime"]
    assert len(regime["dimensions"]) == 8, f"Expected 8 dimensions, got {len(regime['dimensions'])}"
    
    # Verify losers prominent
    losers = payload["failed_trades_prominent"]
    print(f"Total prominent losers: {len(losers)}")
    if losers:
        top_loser = losers[0]
        assert "primary_failure_code" in top_loser, "Missing primary_failure_code"
        assert "diagnostic_explanation" in top_loser, "Missing diagnostic_explanation"
        assert "refactoring_suggestion" in top_loser, "Missing refactoring_suggestion"
        print(f"Top loser: {top_loser['symbol']} ({top_loser['primary_failure_code']}) - Loss: ₹{abs(top_loser['pnl'])}")
        
    print("✅ Web Export Payload passed.")

def test_daily_report_losers_first():
    print("\n--- Testing 2: Daily Markdown Report (Failures First) ---")
    mock_audits = [
        {
            "symbol": "TCS.NS", "short_name": "TCS", "trade_date": "2026-09-08",
            "direction_correct": 0, "simulated_pnl": -340.50,
            "predicted_change_pct": 1.2, "actual_change_pct": -0.8,
            "primary_failure_code": "F06", "attribution_category": "POLARITY_INVERSION",
            "diagnostic_explanation": "IT bellwether sentiment did not hold through session.",
            "refactoring_suggestion": "Tighten entry confirmation filters."
        },
        {
            "symbol": "INFY.NS", "short_name": "Infosys", "trade_date": "2026-09-08",
            "direction_correct": 1, "simulated_pnl": 520.00,
            "predicted_change_pct": 1.5, "actual_change_pct": 1.4,
            "primary_failure_code": "NONE", "attribution_category": "CAPTURED_SUCCESS",
            "diagnostic_explanation": "Predicted target achieved.",
            "refactoring_suggestion": "None."
        }
    ]
    report = generate_daily_markdown_report(mock_audits)
    assert "Forensic Failure Audit (Losers Shown First)" in report, "Report missing Failures First section"
    assert "F06" in report, "Report did not include failure code"
    assert "Captured Catalysts (Winning Trades)" in report, "Report missing winning section"
    
    # Verify failure section appears BEFORE success section
    fail_idx = report.find("Forensic Failure Audit (Losers Shown First)")
    succ_idx = report.find("Captured Catalysts (Winning Trades)")
    assert fail_idx < succ_idx, "Failed trades are NOT positioned before successful trades!"
    print("✅ Daily Markdown Report passed with failures strictly first.")

def test_youtube_script_losers_first():
    print("\n--- Testing 3: YouTube Transparency Video Script ---")
    mock_audits = [
        {
            "symbol": "RELIANCE.NS", "short_name": "Reliance", "trade_date": "2026-09-08",
            "direction_correct": 0, "simulated_pnl": -550.00,
            "predicted_change_pct": 0.8, "actual_change_pct": -1.1,
            "primary_failure_code": "F01", "attribution_category": "MAGNITUDE_ERROR",
            "diagnostic_explanation": "O2C margin contraction surprise.",
            "refactoring_suggestion": "Incorporate GRM spreads."
        }
    ]
    script = generate_youtube_script(mock_audits)
    assert "TRANSPARENCY FIRST — TODAY'S BIGGEST LOSERS" in script, "Script missing losers first hook"
    assert "F01" in script, "Script missing failure code"
    print("✅ YouTube script generator passed.")

def test_web_assets_integrity():
    print("\n--- Testing 4: Web Assets Integrity ---")
    data_json = Path("web_app/data.json")
    data_js = Path("web_app/data.js")
    index_html = Path("web_app/index.html")
    app_js = Path("web_app/app.js")
    
    assert data_json.exists(), "web_app/data.json missing"
    assert data_js.exists(), "web_app/data.js missing"
    assert index_html.exists(), "web_app/index.html missing"
    assert app_js.exists(), "web_app/app.js missing"
    
    with open(data_json) as f:
        d = json.load(f)
    assert len(d.get("failed_trades_prominent", [])) > 0, "failed_trades_prominent is empty"
    
    html_text = index_html.read_text()
    assert "quant-current-nav" in html_text
    assert "baselines-list-container" in html_text
    assert "regime-dims-container" in html_text
    assert "post-losers-cards" in html_text
    
    js_text = app_js.read_text()
    assert "renderQuantOverview" in js_text
    assert "failed_trades_prominent" in js_text
    assert "execution-strip" in js_text or "stopPrice" in js_text
    print("✅ Web assets integrity passed.")

if __name__ == "__main__":
    test_web_export_payload()
    test_daily_report_losers_first()
    test_youtube_script_losers_first()
    test_web_assets_integrity()
    print("\n🎉 ALL PHASE G TESTS PASSED SUCCESSFULLY! (4/4 test groups)")
