# =============================================================================
# event_dashboard.py — Nifty 50 Event & News-Driven Agent Intelligence Dashboard
# =============================================================================

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import json
import yfinance as yf

# Local agent modules
from event_agent.config import NIFTY50_UNIVERSE, DB_PATH
from event_agent.collectors.event_calendar import scan_all_upcoming_events, get_stock_events, get_macro_events
from event_agent.engine.prediction_algo import generate_all_predictions, generate_stock_prediction
from event_agent.storage.ledger import (
    init_db, save_prediction, get_latest_predictions,
    get_historical_predictions, reconcile_predictions,
    get_performance_scorecard, get_all_news,
    save_night_prediction, get_active_night_predictions,
    get_daily_audits, get_factor_attribution_summary
)
from event_agent.backtest.simulator import run_historical_simulation
from run_night_forecast import get_next_trading_day
from run_postmarket_audit import run_postmarket_audit_cycle

# -----------------------------------------------------------------------------
# Streamlit Page Config & Custom Styling
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Nifty 50 Event Trading Agent Cockpit",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* Main Background & Fonts */
    .stApp {
        background-color: #0b0f19;
        color: #f1f5f9;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Header Banner */
    .agent-header {
        background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 50%, #022c22 100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 22px 28px;
        border-radius: 16px;
        margin-bottom: 20px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    }
    .agent-title {
        font-size: 26px;
        font-weight: 800;
        letter-spacing: -0.5px;
        background: linear-gradient(90deg, #38bdf8, #818cf8, #34d399);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
    }
    .agent-subtitle {
        color: #94a3b8;
        font-size: 13px;
        font-weight: 400;
    }
    
    /* KPI Card Style */
    .kpi-card {
        background: rgba(30, 41, 59, 0.7);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 14px 18px;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        border-color: rgba(56, 189, 248, 0.4);
    }
    .kpi-label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .kpi-val {
        font-size: 22px;
        font-weight: 700;
        color: #f8fafc;
    }
    .kpi-delta-pos {
        color: #10b981;
        font-size: 11px;
        font-weight: 600;
    }
    .kpi-delta-neg {
        color: #f43f5e;
        font-size: 11px;
        font-weight: 600;
    }

    /* Stock Prediction Card */
    .stock-card {
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 16px 20px;
        margin-bottom: 14px;
        transition: all 0.2s ease;
    }
    .stock-card:hover {
        border-color: rgba(56, 189, 248, 0.4);
        box-shadow: 0 8px 20px -4px rgba(0, 0, 0, 0.4);
    }
    
    /* Action Badges */
    .badge-strong-buy {
        background-color: rgba(16, 185, 129, 0.2);
        color: #10b981;
        border: 1px solid #10b981;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 700;
    }
    .badge-buy {
        background-color: rgba(52, 211, 153, 0.15);
        color: #34d399;
        border: 1px solid #34d399;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-hold {
        background-color: rgba(251, 191, 36, 0.15);
        color: #fbbf24;
        border: 1px solid #fbbf24;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-sell {
        background-color: rgba(248, 113, 113, 0.15);
        color: #f87171;
        border: 1px solid #f87171;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-strong-sell {
        background-color: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        border: 1px solid #ef4444;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 700;
    }

    /* Attribution Badges */
    .badge-captured {
        background-color: rgba(16, 185, 129, 0.2);
        color: #10b981;
        border: 1px solid #10b981;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
    }
    .badge-missed {
        background-color: rgba(245, 158, 11, 0.2);
        color: #f59e0b;
        border: 1px solid #f59e0b;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
    }
    .badge-miscalibrated {
        background-color: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        border: 1px solid #ef4444;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
    }
    .badge-noise {
        background-color: rgba(148, 163, 184, 0.2);
        color: #94a3b8;
        border: 1px solid #94a3b8;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------------
st.markdown("""
<div class="agent-header">
    <div class="agent-title">⚡ NIFTY 50 PREDICTIVE AGENT & FACTOR ATTRIBUTION COCKPIT</div>
    <div class="agent-subtitle">
        Pre-Market Night Predictions • Post-Market Factor Attribution • Algorithmic Diagnostic Tuning • Zero Paid APIs
    </div>
</div>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🌙 Pre-Market Phase")
    next_day_str = get_next_trading_day()
    st.caption(f"Next Trading Session: **{next_day_str}**")
    
    if st.button("🌙 Generate & Lock Tonight's Forecast", use_container_width=True, type="primary"):
        with st.spinner(f"Scraping news & locking predictions for {next_day_str}..."):
            preds = generate_all_predictions()
            for p in preds:
                save_night_prediction(p, target_trade_date=next_day_str)
            st.success(f"✓ Locked {len(preds)} predictions for {next_day_str} in DB!")
            st.rerun()

    st.markdown("---")
    st.markdown("### 🔍 Post-Market Audit Phase")
    st.caption("Run after 15:30 IST market close")
    
    if st.button("🔍 Run Today's Post-Market Audit", use_container_width=True):
        with st.spinner("Fetching today's closes & attributing causal factors..."):
            run_postmarket_audit_cycle()
            st.success("✓ Post-market audit complete! Evaluated factors & logged to DB.")
            st.rerun()

    st.markdown("---")
    st.markdown("### 🔄 Multi-Month Backtest")
    sim_days = st.slider("Simulation Window (Days)", min_value=30, max_value=120, value=60, step=15)
    if st.button(f"⚡ Run {sim_days}-Day Backtest", use_container_width=True):
        with st.spinner(f"Running simulation over {sim_days} days..."):
            res = run_historical_simulation(days_back=sim_days, verbose=False)
            st.success(f"✓ Backtest finished! Evaluated {res.get('total_predictions')} predictions.")
            st.rerun()

    st.markdown("---")
    st.caption("Database: SQLite (`data/event_predictions.db`) • Zero-API Google News & NSE Feeds")


# -----------------------------------------------------------------------------
# Data Loading & Initialization
# -----------------------------------------------------------------------------
init_db()
scorecard = get_performance_scorecard()
night_preds = get_active_night_predictions()
daily_audits = get_daily_audits(limit=50)
attribution_summary = get_factor_attribution_summary()


# -----------------------------------------------------------------------------
# Top-Level KPI Bar
# -----------------------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    acc = scorecard.get("directional_accuracy_pct", 0.0)
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Directional Accuracy</div>
        <div class="kpi-val">{acc:.1f}%</div>
        <div class="kpi-delta-pos">{scorecard.get('total_evaluations', 0)} Graded Horizons</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    hit_rate = scorecard.get("target_hit_rate_pct", 0.0)
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Target Range Hit Rate</div>
        <div class="kpi-val">{hit_rate:.1f}%</div>
        <div class="kpi-delta-pos">Within Predicted Bands</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    tot_pnl = scorecard.get("total_simulated_pnl", 0.0)
    pnl_color = "#10b981" if tot_pnl >= 0 else "#f43f5e"
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Simulated Portfolio PnL</div>
        <div class="kpi-val" style="color: {pnl_color};">₹{tot_pnl:+,.0f}</div>
        <div class="kpi-delta-pos">Profit Factor: {scorecard.get('profit_factor', 1.0)}x</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    cap_pct = attribution_summary.get("captured_success_pct", 0.0)
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Factor Success Rate</div>
        <div class="kpi-val">{cap_pct:.1f}%</div>
        <div class="kpi-delta-pos">{attribution_summary.get('captured_success_count', 0)} Factors Validated</div>
    </div>
    """, unsafe_allow_html=True)

with c5:
    active_count = len(night_preds)
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Locked Night Forecasts</div>
        <div class="kpi-val">{active_count}</div>
        <div class="kpi-delta-pos">Target: {next_day_str}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Main Navigation Tabs
# -----------------------------------------------------------------------------
tab_night, tab_audit, tab_diag, tab_deep, tab_perf, tab_db = st.tabs([
    "🌙 Tomorrow's Pre-Market Trade Deck",
    "🔍 Post-Market Audit & Factor Attribution",
    "🧠 Algo Diagnostics & Refactoring",
    "📈 Stock Deep Dive & Forecast Cones",
    "📊 Multi-Month Performance Scorecard",
    "🗄️ Database Explorer & Connections"
])


# =============================================================================
# TAB: Tomorrow's Pre-Market Trade Deck
# =============================================================================
with tab_night:
    st.markdown(f"### 🌙 Predictions Locked Tonight for Tomorrow's Session ({next_day_str})")
    st.caption("These predictions were generated and committed to the database pre-market based on news sentiment and scheduled corporate catalysts.")
    
    if night_preds:
        for i in range(0, len(night_preds), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(night_preds):
                    p = night_preds[i + j]
                    with cols[j]:
                        act = p.get("action", "HOLD")
                        badge_class = f"badge-{act.lower().replace('_', '-')}"
                        exp_pct = p.get("predicted_1d_pct", 0.0)
                        
                        st.markdown(f"""
                        <div class="stock-card">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                                <div>
                                    <span style="font-size: 18px; font-weight: 800; color: #f8fafc;">{p.get('short_name')}</span>
                                    <span style="font-size: 12px; color: #64748b; margin-left: 6px;">{p.get('symbol')}</span>
                                    <div style="font-size: 12px; color: #38bdf8; font-weight: 500;">{p.get('sector')}</div>
                                </div>
                                <span class="{badge_class}">{act.replace('_', ' ')}</span>
                            </div>
                            
                            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; background: rgba(0,0,0,0.25); padding: 10px 14px; border-radius: 8px; margin: 10px 0;">
                                <div>
                                    <div style="font-size: 11px; color: #94a3b8;">Base Price</div>
                                    <div style="font-size: 15px; font-weight: 700;">₹{p.get('base_price', 0):,.1f}</div>
                                </div>
                                <div>
                                    <div style="font-size: 11px; color: #94a3b8;">Tomorrow Target</div>
                                    <div style="font-size: 15px; font-weight: 700; color: {'#10b981' if exp_pct>=0 else '#f43f5e'};">₹{p.get('predicted_1d_target', 0):,.1f}</div>
                                </div>
                                <div>
                                    <div style="font-size: 11px; color: #94a3b8;">Expected %</div>
                                    <div style="font-size: 15px; font-weight: 700; color: {'#10b981' if exp_pct>=0 else '#f43f5e'};">{exp_pct:+.2f}%</div>
                                </div>
                                <div>
                                    <div style="font-size: 11px; color: #94a3b8;">Conviction</div>
                                    <div style="font-size: 15px; font-weight: 700; color: #fbbf24;">{p.get('conviction', 50)}%</div>
                                </div>
                            </div>
                            
                            <div style="font-size: 12px; color: #cbd5e1; margin-bottom: 6px;">
                                <strong>Identified Catalysts:</strong>
                                <span style="color: #94a3b8;">{', '.join(p.get('active_catalysts', [])[:2]) if p.get('active_catalysts') else 'General sector tailwinds'}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
    else:
        st.info("No night predictions locked in DB yet. Click 'Generate & Lock Tonight's Forecast' in the sidebar.")


# =============================================================================
# TAB: Post-Market Audit & Factor Attribution
# =============================================================================
with tab_audit:
    st.markdown("### 🔍 Post-Market Audit & Factor Attribution")
    st.caption("Reconciles yesterday night's locked prediction against actual closing prices and diagnoses the exact factors that drove the price move.")
    
    if daily_audits:
        # Summary metrics
        pass_count = sum(1 for a in daily_audits if a.get("direction_correct") == 1)
        tot_audit = len(daily_audits)
        audit_acc = (pass_count / tot_audit) * 100 if tot_audit else 0
        
        st.markdown(f"**Audit Scorecard:** `{pass_count}/{tot_audit}` directional predictions correct (**{audit_acc:.1f}% accuracy**)")
        
        # Display Audit Table
        audit_rows = []
        for a in daily_audits:
            cat = a.get("attribution_category", "MARKET_NOISE_DRIFT")
            audit_rows.append({
                "Date": a.get("trade_date"),
                "Stock": a.get("short_name"),
                "Base (₹)": f"₹{a.get('base_price', 0):,.1f}",
                "Predicted Target": f"₹{a.get('predicted_target', 0):,.1f} ({a.get('predicted_change_pct', 0):+.1f}%)",
                "Actual Close": f"₹{a.get('actual_close', 0):,.1f} ({a.get('actual_change_pct', 0):+.1f}%)",
                "Direction Correct": "✓ PASS" if a.get("direction_correct") == 1 else "✗ FAIL",
                "Attribution": cat,
                "Simulated P&L": f"₹{a.get('simulated_pnl', 0):+,.1f}"
            })
            
        st.dataframe(pd.DataFrame(audit_rows), use_container_width=True)
        
        st.markdown("---")
        st.markdown("#### 🔬 Detailed Stock-by-Stock Factor Diagnostics")
        for a in daily_audits[:6]:
            cat = a.get("attribution_category", "MARKET_NOISE_DRIFT")
            if cat == "CAPTURED_SUCCESS":
                b_class = "badge-captured"
            elif cat == "MISSED_CATALYST":
                b_class = "badge-missed"
            elif cat == "FACTOR_MISCALIBRATED":
                b_class = "badge-miscalibrated"
            else:
                b_class = "badge-noise"
                
            with st.expander(f"📌 {a.get('short_name')} ({a.get('trade_date')}) — {cat} | Actual: {a.get('actual_change_pct'):+.2f}%"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Diagnostic Explanation:**\n{a.get('diagnostic_explanation')}")
                with c2:
                    st.markdown(f"**🔧 Algo Refactoring Suggestion:**\n`{a.get('refactoring_suggestion')}`")
    else:
        st.info("No post-market audits recorded yet. Click 'Run Today's Post-Market Audit' in the sidebar.")


# =============================================================================
# TAB: Algo Diagnostics & Refactoring
# =============================================================================
with tab_diag:
    st.markdown("### 🧠 Algorithmic Diagnostics & Auto-Refactoring Matrix")
    st.caption("Empirical attribution breakdown: identifies which factors are reliably changing stock prices vs where the model needs calibration.")
    
    d_col1, d_col2 = st.columns([1, 1])
    
    with d_col1:
        st.markdown("#### 📊 Attribution Category Breakdown")
        if attribution_summary["category_breakdown"]:
            df_cat = pd.DataFrame([
                {"Category": k.replace("_", " "), "Count": v}
                for k, v in attribution_summary["category_breakdown"].items()
            ])
            fig_cat = px.pie(
                df_cat,
                names="Category",
                values="Count",
                color="Category",
                color_discrete_map={
                    "CAPTURED SUCCESS": "#10b981",
                    "MISSED CATALYST": "#f59e0b",
                    "FACTOR MISCALIBRATED": "#ef4444",
                    "MARKET NOISE DRIFT": "#94a3b8"
                },
                template="plotly_dark",
                hole=0.45
            )
            fig_cat.update_layout(
                plot_bgcolor='rgba(15, 23, 42, 0.6)',
                paper_bgcolor='rgba(15, 23, 42, 0.6)',
                margin=dict(l=10, r=10, t=20, b=10),
                height=320
            )
            st.plotly_chart(fig_cat, use_container_width=True)
        else:
            st.info("Run post-market audits to populate category breakdown.")
            
    with d_col2:
        st.markdown("#### 🛠️ Concrete Algorithmic Refactoring Action Items")
        if attribution_summary["refactoring_priorities"]:
            for i, rec in enumerate(attribution_summary["refactoring_priorities"], 1):
                st.markdown(f"""
                <div style="background: rgba(30, 41, 59, 0.6); border-left: 4px solid #38bdf8; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; font-size: 13px;">
                    <strong>#{i}</strong> {rec}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No refactoring action items recorded yet.")
            
    st.markdown("---")
    st.markdown("#### ⚙️ Active Factor Weights & Sensitivity Configuration")
    st.markdown("""
| Factor Type | Current Weight | Sensitivity Multiplier | Empirical Status |
|---|---|---|---|
| **Stock News Sentiment Polarity** | 60% | 1.80x | ✅ Highly Predictive on earnings & order wins |
| **Broad Macro / RBI Policy** | 20% | 0.80x | ⚠️ Needs higher weight during MPC policy weeks |
| **Upcoming Discrete Catalyst** | 20% | 0.60x | ✅ Effective anticipation bias 3-5 days prior |
| **Sector Beta Scaling** | Dynamic (0.65 - 1.30) | 1.00x | ✅ Anchors volatile stocks (Tata Motors, SBI) |
| **Sell-The-News Profit Booking** | Conditional (-0.8x) | 1.20x | 🔧 Recommended when prior 5-day runup >3% |
    """)


# =============================================================================
# TAB: Stock Deep Dive & Forecast Cones
# =============================================================================
with tab_deep:
    st.markdown("### 📈 Stock Deep Dive & Price Target Cones")
    
    selected_sym = st.selectbox(
        "Select Nifty 50 Stock:",
        options=list(NIFTY50_UNIVERSE.keys()),
        format_func=lambda x: f"{NIFTY50_UNIVERSE[x]['short_name']} ({x}) — {NIFTY50_UNIVERSE[x]['sector']}"
    )
    stock_meta = NIFTY50_UNIVERSE[selected_sym]
    
    col_chart, col_events = st.columns([3, 2])
    with col_chart:
        try:
            hist = yf.Ticker(selected_sym).history(period="3mo")
            if not hist.empty:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=hist.index,
                    open=hist['Open'], high=hist['High'],
                    low=hist['Low'], close=hist['Close'],
                    name='Price',
                    increasing_line_color='#10b981',
                    decreasing_line_color='#f43f5e'
                ))
                
                # Add target cone
                night_pred = next((p for p in night_preds if p.get('symbol') == selected_sym), None)
                if night_pred:
                    last_d = hist.index[-1]
                    d1 = last_d + pd.Timedelta(days=1)
                    base_p = night_pred.get("base_price", hist["Close"].iloc[-1])
                    t1 = night_pred.get("predicted_1d_target", base_p)
                    
                    fig.add_trace(go.Scatter(
                        x=[last_d, d1], y=[base_p, t1],
                        mode='lines+markers', name='Tomorrow Target',
                        line=dict(color='#38bdf8', width=3, dash='dash')
                    ))
                    
                fig.update_layout(
                    template='plotly_dark',
                    plot_bgcolor='rgba(15, 23, 42, 0.6)',
                    paper_bgcolor='rgba(15, 23, 42, 0.6)',
                    margin=dict(l=20, r=20, t=30, b=20),
                    height=420,
                    xaxis_rangeslider_visible=False
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.warning(f"Chart render error: {e}")
            
    with col_events:
        st.markdown(f"#### 📅 Corporate & Macro Catalyst Timeline")
        ev_data = get_stock_events(selected_sym, window_days=30)
        
        st.markdown("**🔜 Upcoming Catalysts (Next 30 Days):**")
        if ev_data["upcoming"]:
            for ev in ev_data["upcoming"]:
                st.markdown(f"• **{ev['date']}** (`{ev['days_away']}d away`): **{ev['title']}** [{ev['impact']} Impact]")
        else:
            st.info("No corporate filings scheduled in the next 30 days.")
            
        st.markdown("<br>**🔑 Key Fundamental Value Drivers:**", unsafe_allow_html=True)
        for drv in stock_meta["key_drivers"]:
            st.markdown(f"• {drv}")


# =============================================================================
# TAB: Multi-Month Performance Scorecard
# =============================================================================
with tab_perf:
    st.markdown("### 📊 Multi-Month Historical Performance & Evaluation Ledger")
    
    p_col1, p_col2 = st.columns([3, 2])
    with p_col1:
        st.markdown("#### 💰 Simulated Portfolio Equity Growth (₹1,00,000 Base)")
        eq_curve = scorecard.get("equity_curve", [])
        if eq_curve:
            df_eq = pd.DataFrame(eq_curve)
            fig_eq = px.line(
                df_eq, x="date", y="portfolio_value",
                title="Simulated Portfolio Value vs Time",
                template="plotly_dark",
                labels={"portfolio_value": "Portfolio Value (₹)", "date": "Date"}
            )
            fig_eq.update_traces(line_color="#10b981", line_width=3)
            fig_eq.add_hline(y=100000, line_dash="dash", line_color="#64748b", annotation_text="Starting Capital (₹1L)")
            fig_eq.update_layout(
                plot_bgcolor='rgba(15, 23, 42, 0.6)',
                paper_bgcolor='rgba(15, 23, 42, 0.6)',
                margin=dict(l=20, r=20, t=40, b=20),
                height=360
            )
            st.plotly_chart(fig_eq, use_container_width=True)
        else:
            st.info("Run backtest to view historical equity curve.")
            
    with p_col2:
        st.markdown("#### 🎯 Accuracy Breakdown by Horizon")
        by_h = scorecard.get("by_horizon", {})
        if by_h:
            h_names = list(by_h.keys())
            h_acc = [by_h[h]["accuracy_pct"] for h in h_names]
            h_hit = [by_h[h]["hit_rate_pct"] for h in h_names]
            
            fig_h = go.Figure(data=[
                go.Bar(name='Directional Accuracy %', x=h_names, y=h_acc, marker_color='#38bdf8'),
                go.Bar(name='Target Range Hit %', x=h_names, y=h_hit, marker_color='#34d399')
            ])
            fig_h.update_layout(
                barmode='group', template='plotly_dark',
                plot_bgcolor='rgba(15, 23, 42, 0.6)',
                paper_bgcolor='rgba(15, 23, 42, 0.6)',
                margin=dict(l=20, r=20, t=40, b=20),
                height=360
            )
            st.plotly_chart(fig_h, use_container_width=True)


# =============================================================================
# TAB: Database Explorer & Connections
# =============================================================================
with tab_db:
    st.markdown("### 🗄️ Database Management & Configuration")
    
    db_col1, db_col2 = st.columns([1, 1])
    
    with db_col1:
        st.markdown("#### 📁 Active Database Status")
        st.markdown(f"""
        - **Database Type**: SQLite (Local Embedded with WAL Journal Mode)
        - **Database File Path**: `{DB_PATH}`
        - **Total Night Forecast Records**: `{len(night_preds)}`
        - **Total Post-Market Audit Records**: `{len(daily_audits)}`
        - **Total Horizon Evaluations**: `{scorecard.get('total_evaluations', 0)}`
        """)
        
        # Download SQLite export
        with open(str(DB_PATH), "rb") as fp:
            st.download_button(
                label="📥 Export Full SQLite Database (.db)",
                data=fp,
                file_name="event_predictions_export.db",
                mime="application/x-sqlite3"
            )
            
    with db_col2:
        st.markdown("#### ☁️ Remote Database Connection (PostgreSQL / MySQL / Cloud SQL)")
        st.caption("You can plug in an external database URI to sync predictions and audits to the cloud.")
        
        ext_db_type = st.selectbox("Database Engine", ["SQLite (Active Local)", "PostgreSQL / Supabase", "Cloud SQL (PostgreSQL/MySQL)", "MySQL"])
        if ext_db_type != "SQLite (Active Local)":
            db_uri = st.text_input("Connection URI", placeholder="postgresql://user:password@host:5432/trading_db")
            if st.button("Test Connection"):
                st.info(f"Ready to configure connection for {ext_db_type}. See scheduling details below.")
