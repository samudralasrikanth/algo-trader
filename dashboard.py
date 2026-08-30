# =============================================================================
# dashboard.py — Streamlit Live Dashboard
# =============================================================================
"""
Run:  streamlit run dashboard.py

Tabs:
    📊 Live Session   — open positions, PnL, equity curve (auto-refreshes)
    📋 Trade History  — full closed trade table + filters
    📈 Indicators     — per-symbol RSI / VWAP / Price chart (last 100 bars)
    🧪 Backtest       — run backtest from dashboard, see metrics + equity curve
"""

import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ── path to shared DB ────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "trades.db"

# ── page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="algo-trader | Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── global CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* Dark card */
    .metric-card {
        background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%);
        border: 1px solid #2a3550;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        text-align: center;
    }
    .metric-label { color: #8b95b0; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; }
    .metric-value { color: #e8ecf4; font-size: 1.8rem; font-weight: 700; margin-top: 0.25rem; }
    .metric-pos   { color: #00d4aa !important; }
    .metric-neg   { color: #ff4d6d !important; }

    /* Status badge */
    .badge-live  { background:#00d4aa22; color:#00d4aa; border:1px solid #00d4aa55; padding:2px 10px; border-radius:20px; font-size:0.75rem; }
    .badge-hold  { background:#f59e0b22; color:#f59e0b; border:1px solid #f59e0b55; padding:2px 10px; border-radius:20px; font-size:0.75rem; }

    /* Hide Streamlit branding */
    #MainMenu, footer { visibility: hidden; }
    .block-container { padding-top: 4rem; }
</style>
""", unsafe_allow_html=True)


# ── helpers ──────────────────────────────────────────────────────────────────

@st.cache_resource
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_trades(conn) -> pd.DataFrame:
    try:
        df = pd.read_sql("SELECT * FROM trades ORDER BY id DESC", conn)
        return df
    except Exception:
        return pd.DataFrame()


def fetch_ticks(conn, symbol: str, limit: int = 150) -> pd.DataFrame:
    try:
        df = pd.read_sql(
            "SELECT * FROM tick_log WHERE symbol=? ORDER BY id DESC LIMIT ?",
            conn, params=(symbol, limit),
        )
        return df.iloc[::-1].reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def closed_trades(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["closed_at"].notna()] if not df.empty else pd.DataFrame()


def open_trades(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["closed_at"].isna()] if not df.empty else pd.DataFrame()


def pnl_color(val):
    return "color: #00d4aa" if val > 0 else "color: #ff4d6d"


def metric_html(label: str, value: str, cls: str = "") -> str:
    val_cls = f"metric-value {cls}"
    return f"""<div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="{val_cls}">{value}</div>
    </div>"""


# ── sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ algo-trader")
    st.markdown("---")
    refresh_rate = st.slider("Auto-refresh (sec)", 5, 60, 10)
    symbols_cfg  = st.multiselect(
        "Symbols to display",
        ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS"],
        default=["RELIANCE", "HDFCBANK", "ICICIBANK"],
    )
    st.markdown("---")
    st.markdown(f"**DB:** `{DB_PATH.name}`")
    st.markdown(f"**Last refresh:** {datetime.now().strftime('%H:%M:%S')}")
    st.markdown("---")
    st.caption("Paper trading only. Not financial advice.")


# ── data load ────────────────────────────────────────────────────────────────

conn  = get_conn()
df_all = fetch_trades(conn)
df_closed = closed_trades(df_all)
df_open   = open_trades(df_all)

total_pnl = df_closed["pnl"].sum() if not df_closed.empty and "pnl" in df_closed else 0.0
wins      = int((df_closed["pnl"] > 0).sum()) if not df_closed.empty and "pnl" in df_closed else 0
losses    = int((df_closed["pnl"] <= 0).sum()) if not df_closed.empty and "pnl" in df_closed else 0
win_rate  = wins / max(wins + losses, 1) * 100


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TABS                                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Live Session",
    "📋 Trade History",
    "📈 Indicators",
    "🧪 Backtest",
    "🎓 Learn to Trade",
])


# ──────────────────────────────────────────────────────────────────────────────
# TAB 1 — Live Session
# ──────────────────────────────────────────────────────────────────────────────

with tab1:
    st.markdown("### Session Overview")

    # KPI row
    c1, c2, c3, c4, c5 = st.columns(5)
    pnl_cls = "metric-pos" if total_pnl >= 0 else "metric-neg"
    c1.markdown(metric_html("Total PnL", f"₹{total_pnl:,.2f}", pnl_cls), unsafe_allow_html=True)
    c2.markdown(metric_html("Closed Trades", str(len(df_closed))), unsafe_allow_html=True)
    c3.markdown(metric_html("Open Positions", str(len(df_open))), unsafe_allow_html=True)
    c4.markdown(metric_html("Win Rate", f"{win_rate:.1f}%", "metric-pos" if win_rate > 50 else "metric-neg"), unsafe_allow_html=True)
    c5.markdown(metric_html("W / L", f"{wins} / {losses}"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Equity curve
    if not df_closed.empty and "pnl" in df_closed.columns:
        eq = df_closed.sort_values("id")["pnl"].cumsum().tolist()
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            y=eq, mode="lines", line=dict(color="#00d4aa", width=2),
            fill="tozeroy",
            fillcolor="rgba(0,212,170,0.08)",
            name="Equity",
        ))
        fig_eq.update_layout(
            title="Cumulative PnL (₹)",
            template="plotly_dark",
            height=300,
            margin=dict(l=0, r=0, t=40, b=0),
            yaxis_title="₹",
            xaxis_title="Trade #",
            paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117",
        )
        st.plotly_chart(fig_eq, use_container_width=True)
    else:
        st.info("No closed trades yet — equity curve will appear here.")

    # Open positions table
    st.markdown("#### 🟢 Open Positions")
    if df_open.empty:
        st.markdown('<p style="color:#8b95b0">No open positions</p>', unsafe_allow_html=True)
    else:
        disp = df_open[["symbol", "side", "entry_price", "stop_loss", "target", "qty", "opened_at"]].copy()
        st.dataframe(
            disp.style.applymap(lambda v: "color:#00d4aa" if v == "BUY" else "color:#ff4d6d", subset=["side"]),
            use_container_width=True,
            hide_index=True,
        )


# ──────────────────────────────────────────────────────────────────────────────
# TAB 2 — Trade History
# ──────────────────────────────────────────────────────────────────────────────

with tab2:
    st.markdown("### Trade History")

    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        sym_filter = st.multiselect("Filter by symbol", options=df_all["symbol"].unique().tolist() if not df_all.empty else [], default=[])
    with col_f2:
        side_filter = st.selectbox("Side", ["All", "BUY", "SELL"])

    filtered = df_all.copy()
    if sym_filter:
        filtered = filtered[filtered["symbol"].isin(sym_filter)]
    if side_filter != "All":
        filtered = filtered[filtered["side"] == side_filter]

    if filtered.empty:
        st.info("No trades match the filter.")
    else:
        cols_show = ["symbol", "side", "entry_price", "exit_price", "qty",
                     "stop_loss", "target", "exit_reason", "pnl", "opened_at", "closed_at"]
        cols_show = [c for c in cols_show if c in filtered.columns]
        styled = (
            filtered[cols_show]
            .style
            .applymap(pnl_color, subset=["pnl"] if "pnl" in cols_show else [])
            .format({"entry_price": "₹{:.2f}", "exit_price": "₹{:.2f}",
                     "stop_loss": "₹{:.2f}", "target": "₹{:.2f}",
                     "pnl": "₹{:.2f}"}, na_rep="—")
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # PnL distribution bar chart
        if "pnl" in filtered.columns:
            df_pnl = filtered.dropna(subset=["pnl"])
            if not df_pnl.empty:
                fig_bar = px.bar(
                    df_pnl.reset_index(drop=True),
                    y="pnl", x=df_pnl.index,
                    color="pnl",
                    color_continuous_scale=["#ff4d6d", "#222", "#00d4aa"],
                    title="PnL per Trade",
                    labels={"x": "Trade #", "pnl": "PnL (₹)"},
                    template="plotly_dark",
                )
                fig_bar.update_layout(
                    height=280, margin=dict(l=0, r=0, t=40, b=0),
                    coloraxis_showscale=False,
                    paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                )
                st.plotly_chart(fig_bar, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3 — Indicators
# ──────────────────────────────────────────────────────────────────────────────

with tab3:
    st.markdown("### Live Indicator Feed")
    sym_sel = st.selectbox("Symbol", symbols_cfg, key="ind_sym")

    df_ticks = fetch_ticks(conn, sym_sel, limit=150)

    if df_ticks.empty:
        st.info(f"No tick data for {sym_sel} yet — start the runner first.")
    else:
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            row_heights=[0.5, 0.25, 0.25],
            subplot_titles=[f"{sym_sel} Price vs VWAP", "RSI", "Volume"],
            vertical_spacing=0.08,
        )

        # Price + VWAP
        fig.add_trace(go.Scatter(
            x=df_ticks["timestamp"], y=df_ticks["ltp"],
            mode="lines", line=dict(color="#e8ecf4", width=1.5), name="LTP",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df_ticks["timestamp"], y=df_ticks["vwap"],
            mode="lines", line=dict(color="#f59e0b", width=1.2, dash="dash"), name="VWAP",
        ), row=1, col=1)

        # RSI with overbought/oversold bands
        fig.add_trace(go.Scatter(
            x=df_ticks["timestamp"], y=df_ticks["rsi"],
            mode="lines", line=dict(color="#a78bfa", width=1.5), name="RSI",
        ), row=2, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ff4d6d", row=2, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00d4aa", row=2, col=1)
        fig.add_hline(y=50, line_dash="dot", line_color="#555", row=2, col=1)

        # Volume bars coloured by signal
        colors_vol = []
        for sig in df_ticks.get("signal", []):
            if sig == "BUY":   colors_vol.append("#00d4aa")
            elif sig == "SELL": colors_vol.append("#ff4d6d")
            else:               colors_vol.append("#444")

        fig.add_trace(go.Bar(
            x=df_ticks["timestamp"], y=df_ticks["volume"],
            marker_color=colors_vol, name="Volume",
        ), row=3, col=1)

        fig.update_layout(
            template="plotly_dark",
            height=650,
            paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117",
            legend=dict(orientation="h", y=1.02),
            margin=dict(l=0, r=0, t=60, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 4 — Backtest
# ──────────────────────────────────────────────────────────────────────────────

with tab4:
    st.markdown("### Backtest Engine")
    st.caption("Replays historical candles through the full pipeline — indicators → signal → agent → paper executor")

    col_b1, col_b2, col_b3 = st.columns(3)
    bt_symbol  = col_b1.selectbox("Symbol", symbols_cfg, key="bt_sym")
    bt_days    = col_b2.slider("Lookback (days)", 5, 60, 30)
    bt_warmup  = col_b3.slider("Warmup bars", 20, 100, 50)

    if st.button("▶ Run Backtest", type="primary"):
        with st.spinner(f"Fetching {bt_days}d of candles for {bt_symbol}..."):
            try:
                from data.provider import get_broker
                from strategy.indicators import build_dataframe
                from backtest.backtester import Backtester

                broker = get_broker()
                candles = broker.get_historical_candles(bt_symbol, interval="minute", lookback_days=bt_days)
                df_bt   = build_dataframe(candles)
                bt      = Backtester(symbol=bt_symbol, df=df_bt, warmup=bt_warmup)
                result  = bt.run()

                st.success(f"Backtest complete — {len(result.trades)} trades")

                # Metrics
                m1, m2, m3, m4, m5 = st.columns(5)
                pnl_c = "metric-pos" if result.total_pnl >= 0 else "metric-neg"
                m1.markdown(metric_html("Total PnL", f"₹{result.total_pnl:,.2f}", pnl_c), unsafe_allow_html=True)
                m2.markdown(metric_html("Win Rate",  f"{result.win_rate:.1f}%"), unsafe_allow_html=True)
                m3.markdown(metric_html("Max Drawdown", f"{result.max_drawdown:.1f}%", "metric-neg"), unsafe_allow_html=True)
                m4.markdown(metric_html("Sharpe", f"{result.sharpe_ratio:.2f}"), unsafe_allow_html=True)
                m5.markdown(metric_html("Profit Factor", f"{result.profit_factor:.2f}"), unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)

                # Equity curve
                fig_bt = go.Figure()
                fig_bt.add_trace(go.Scatter(
                    y=result.equity_curve,
                    mode="lines",
                    line=dict(color="#00d4aa", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(0,212,170,0.08)",
                    name="Equity",
                ))
                fig_bt.update_layout(
                    title=f"Backtest Equity Curve — {bt_symbol} ({bt_days}d)",
                    template="plotly_dark",
                    height=350,
                    paper_bgcolor="#0d1117",
                    plot_bgcolor="#0d1117",
                    margin=dict(l=0, r=0, t=40, b=0),
                    yaxis_title="Cumulative PnL (₹)",
                    xaxis_title="Bar #",
                )
                st.plotly_chart(fig_bt, use_container_width=True)

                # Trade table
                if result.trades:
                    st.markdown("#### Trade Log")
                    df_res = result.to_dataframe()
                    show_cols = [c for c in ["symbol","side","entry_price","exit_price","qty","exit_reason","pnl"] if c in df_res.columns]
                    st.dataframe(
                        df_res[show_cols].style
                        .applymap(pnl_color, subset=["pnl"] if "pnl" in show_cols else [])
                        .format({"entry_price":"₹{:.2f}","exit_price":"₹{:.2f}","pnl":"₹{:.2f}"}, na_rep="—"),
                        use_container_width=True,
                        hide_index=True,
                    )

            except Exception as e:
                st.error(f"Backtest failed: {e}")
                st.exception(e)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 5 — Learn to Trade
# ──────────────────────────────────────────────────────────────────────────────

with tab5:
    st.markdown("### 🎓 Trading Academy")
    st.markdown("Welcome to the Trading Academy! Here you will learn the fundamental logic and reasoning required to understand the stock market and algorithmic trading.")

    edu_tabs = st.tabs([
        "1. Basics of Stock Market", 
        "2. Understanding Indicators", 
        "3. Order Types & Execution", 
        "4. Risk Management"
    ])

    with edu_tabs[0]:
        st.markdown("#### The Basics of the Stock Market")
        st.markdown('''
        **What is a Stock?**  
        A stock represents a fraction of ownership in a business. When you buy a stock, you are buying a small piece of a company.
        
        **Why do prices move?**  
        Prices move based on **Supply and Demand**. 
        - If more people want to buy a stock (demand) than sell it (supply), the price goes up.
        - If more people want to sell a stock than buy it, the price goes down.
        
        **What is Algorithmic Trading?**  
        Instead of manually clicking "Buy" or "Sell", we write computer programs (algorithms) that follow a set of predefined rules to execute trades automatically. This removes human emotion from trading and allows for faster execution.
        ''')

    with edu_tabs[1]:
        st.markdown("#### Understanding Indicators")
        st.markdown('''
        Indicators help us analyze price movements and make informed trading decisions.
        
        **1. LTP (Last Traded Price):**  
        The most recent price at which a trade occurred. This is the current "live" price of the stock.
        
        **2. VWAP (Volume Weighted Average Price):**  
        VWAP is the average price a stock has traded at throughout the day, based on both **volume** and **price**. 
        - **Logic:** If the current price is *above* VWAP, the trend is generally considered *bullish* (buyers are in control). If it's *below* VWAP, the trend is *bearish* (sellers are in control).
        
        **3. RSI (Relative Strength Index):**  
        RSI measures the speed and magnitude of recent price changes to evaluate overvalued or undervalued conditions. It ranges from 0 to 100.
        - **Overbought (RSI > 70):** The stock may have risen too fast and might pull back.
        - **Oversold (RSI < 30):** The stock may have fallen too fast and might bounce back.
        ''')

    with edu_tabs[2]:
        st.markdown("#### Order Types & Execution")
        st.markdown('''
        **1. Long (Buy) vs. Short (Sell):**
        - **Long (Buy):** You buy a stock hoping the price goes **up**. You profit from the difference when you sell it at a higher price.
        - **Short (Sell):** You sell a stock you don't own (borrowing it) hoping the price goes **down**. You profit by buying it back later at a lower price.
        
        **2. Stop Loss:**  
        A safety net! It's a predefined price level where your trade will automatically close to limit your losses if the market goes against you. *Never trade without a stop loss.*
        
        **3. Target / Take Profit:**  
        The price level where you want to lock in your profits and exit the trade automatically.
        ''')

    with edu_tabs[3]:
        st.markdown("#### Risk Management")
        st.markdown('''
        Risk management is the most important skill in trading. It's about preserving your capital.
        
        **1. Position Sizing:**  
        Never risk your entire account on one trade. A common rule is to never risk more than 1% to 2% of your total capital on a single trade.
        
        **2. Risk-to-Reward Ratio:**  
        For every ₹1 you risk (stop loss), you should aim to make at least ₹2 (target). This is a 1:2 risk-to-reward ratio. Even if you lose 50% of your trades, you will still be profitable!
        
        **3. Win Rate vs. Profitability:**  
        You don't need a 100% win rate to make money. A strategy with a 40% win rate can be highly profitable if the winning trades are much larger than the losing trades (due to good risk-to-reward).
        ''')

# ── auto-refresh ─────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(f"Auto-refreshing every {refresh_rate}s · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
time.sleep(refresh_rate)
st.rerun()
