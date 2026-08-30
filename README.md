# algo-trader

Advanced Autonomous Trading & Event-Driven Intelligence Platform for Indian Equity Markets (NSE / Nifty 50).

**🌐 Live Netlify Web App**: **[https://nifty50-event-agent.netlify.app](https://nifty50-event-agent.netlify.app)**

---

## ⚡ 1. Nifty 50 Event & News-Driven Prediction Agent (Zero-API Workflow)

An autonomous fundamental and catalyst-driven trading agent workflow that predicts daily stock prices for **10 core Nifty 50 leaders** without requiring any paid broker or chart APIs.

```
algo-trader/
├── event_agent/
│   ├── config.py                     # 10 Nifty 50 Universe, sectors & beta weights
│   ├── collectors/
│   │   ├── news_collector.py         # Google News RSS scraper & cleaner (zero API)
│   │   └── event_calendar.py         # Corporate actions, earnings dates & RBI macro calendar
│   ├── engine/
│   │   ├── sentiment_analyzer.py     # Indian market financial sentiment NLP engine
│   │   └── prediction_algo.py        # Multi-factor target price cone generator (1D, 3D, 7D)
│   ├── storage/
│   │   └── ledger.py                 # SQLite database: predictions & evaluation accuracy ledger
│   └── backtest/
│       └── simulator.py              # Multi-month historical simulation & audit harness
├── run_daily_agent.py                # Daily CLI runner & scheduler entrypoint
└── event_dashboard.py                # Interactive Streamlit Cockpit & Analytics UI
```

### 10 Core Nifty 50 Universe

| Ticker | Company | Sector | Key Fundamental Catalyst |
|---|---|---|---|
| `RELIANCE.NS` | Reliance Industries | Conglomerate / Oil & Telecom | Retail EBITDA, Jio ARPU, GRM refining spreads |
| `HDFCBANK.NS` | HDFC Bank | Private Banking | Credit growth, Net Interest Margin (NIM), CD ratio |
| `ICICIBANK.NS` | ICICI Bank | Private Banking | Domestic loan growth, digital banking traction |
| `TCS.NS` | TCS | IT Services | North America client tech spend, deal TCV inflows |
| `INFY.NS` | Infosys | IT Services | Constant currency guidance, AI deals (Topaz) |
| `BHARTIARTL.NS` | Bharti Airtel | Telecommunications | Monthly ARPU tariff hikes, 5G monetization |
| `SBIN.NS` | State Bank of India | PSU Banking | Corporate capex cycle, GNPA asset quality |
| `LT.NS` | Larsen & Toubro | Infrastructure & Capital Goods | Mega order book inflows, government capex |
| `ITC.NS` | ITC Limited | FMCG / Diversified | Cigarette taxation stability, hotels demerger |
| `MARUTI.NS` | Maruti Suzuki | Automobile / Passenger Vehicles | Monthly auto wholesales, SUV & Hybrid volume |

### Quick Start Commands

```bash
# 1. Run Live Daily Agent Prediction Cycle
python3 run_daily_agent.py

# 2. Run Multi-Month Historical Backtest Simulation (e.g. 60 days)
python3 run_daily_agent.py --backtest --days 60

# 3. Launch Interactive Trading Intelligence Cockpit
streamlit run event_dashboard.py
```

---

## 📈 2. Technical Paper-Trading Agent (Zerodha Kite)

Production-style technical paper-trading agent using Kite Connect intraday indicators.

```bash
python3 main.py
```
