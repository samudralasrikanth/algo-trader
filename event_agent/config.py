# =============================================================================
# event_agent/config.py — 10 Nifty 50 Universe & Agent Configuration
# =============================================================================

from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
DB_PATH = DATA_DIR / "event_predictions.db"

# 10 Nifty 50 Core Stocks Universe
NIFTY50_UNIVERSE = {
    "RELIANCE.NS": {
        "name": "Reliance Industries Ltd",
        "short_name": "Reliance",
        "sector": "Oil & Gas / Conglomerate / Telecom",
        "search_terms": ["Reliance Industries", "Mukesh Ambani", "Jio", "Reliance Retail", "RIL NSE"],
        "beta": 1.10,
        "key_drivers": ["Crude oil refining margins (GRM)", "Telecom ARPU & 5G rollout", "Retail footfall & revenue", "New energy investments"]
    },
    "HDFCBANK.NS": {
        "name": "HDFC Bank Ltd",
        "short_name": "HDFC Bank",
        "sector": "Private Banking",
        "search_terms": ["HDFC Bank", "HDFC Bank quarterly results", "HDFC merger NIMs", "HDFCBANK NSE"],
        "beta": 0.95,
        "key_drivers": ["Net Interest Margin (NIM)", "Deposit growth vs credit growth", "RBI repo rate stance", "Gross NPA / Asset quality"]
    },
    "ICICIBANK.NS": {
        "name": "ICICI Bank Ltd",
        "short_name": "ICICI Bank",
        "sector": "Private Banking",
        "search_terms": ["ICICI Bank", "ICICI Bank results", "ICICIBANK loan growth", "ICICIBANK NSE"],
        "beta": 1.05,
        "key_drivers": ["Domestic loan growth", "Retail & SME margins", "Provisioning coverage", "Digital banking adoption"]
    },
    "TCS.NS": {
        "name": "Tata Consultancy Services Ltd",
        "short_name": "TCS",
        "sector": "IT Services",
        "search_terms": ["Tata Consultancy Services", "TCS Q1 Q2 Q3 Q4", "TCS deal wins TCV", "TCS NSE"],
        "beta": 0.85,
        "key_drivers": ["US & European client tech spending", "Total Contract Value (TCV) bookings", "Employee attrition & margin expansion", "AI services demand"]
    },
    "INFY.NS": {
        "name": "Infosys Ltd",
        "short_name": "Infosys",
        "sector": "IT Services",
        "search_terms": ["Infosys Ltd", "Infosys guidance", "Infosys quarterly earnings", "INFY NSE"],
        "beta": 0.90,
        "key_drivers": ["Constant currency revenue growth guidance", "Large deal ramp-up", "Operating margins", "Discretionary BFSI tech spend"]
    },
    "BHARTIARTL.NS": {
        "name": "Bharti Airtel Ltd",
        "short_name": "Bharti Airtel",
        "sector": "Telecommunications",
        "search_terms": ["Bharti Airtel", "Sunil Mittal", "Airtel ARPU tariff hike", "BHARTIARTL NSE"],
        "beta": 0.80,
        "key_drivers": ["Average Revenue Per User (ARPU) tariff hikes", "5G subscriber monetization", "Africa business growth", "Capex moderation"]
    },
    "SBIN.NS": {
        "name": "State Bank of India",
        "short_name": "SBI",
        "sector": "PSU Banking",
        "search_terms": ["State Bank of India", "SBI quarterly results", "SBIN credit growth", "SBIN NSE"],
        "beta": 1.20,
        "key_drivers": ["Public sector capex demand", "Corporate credit cycle", "Slippages and recovery", "Cost of deposits"]
    },
    "LT.NS": {
        "name": "Larsen & Toubro Ltd",
        "short_name": "L&T",
        "sector": "Infrastructure & Capital Goods",
        "search_terms": ["Larsen and Toubro", "L&T order book win", "L&T infrastructure tender", "LT NSE"],
        "beta": 1.15,
        "key_drivers": ["Government infra spending", "Middle East hydrocarbon order inflows", "Order backlog execution pace", "Working capital cycle"]
    },
    "ITC.NS": {
        "name": "ITC Ltd",
        "short_name": "ITC",
        "sector": "FMCG / Diversified",
        "search_terms": ["ITC Ltd", "ITC hotel demerger", "ITC cigarette volumes", "ITC FMCG profits"],
        "beta": 0.65,
        "key_drivers": ["Cigarette taxation stability / Union Budget", "FMCG margin turnaround", "Agri & Paperboards cycle", "Hotels demerger value unlocking"]
    },
    "MARUTI.NS": {
        "name": "Maruti Suzuki India Ltd",
        "short_name": "Maruti Suzuki",
        "sector": "Automobile / Passenger Vehicles",
        "search_terms": ["Maruti Suzuki", "Maruti car sales wholesale", "Maruti Suzuki EV hybrid", "MARUTI NSE"],
        "beta": 1.05,
        "key_drivers": ["Monthly auto sales volume numbers", "Rural demand recovery", "Hybrid & SUV market share", "Yen currency movement & raw material costs"]
    }
}

# Macro & Indian Market Search Terms
MACRO_SEARCH_TERMS = [
    "Nifty 50 market wrap",
    "RBI monetary policy repo rate",
    "India inflation CPI",
    "FII DII equity flow India",
    "Crude oil prices impact India"
]

# Forecast Horizons (Days)
HORIZONS = [1, 3, 7]

# Event Categories & Standard Impact Multipliers
EVENT_CATEGORIES = {
    "EARNINGS_BEAT": {"base_impact": 0.025, "direction": 1, "severity": "HIGH"},
    "EARNINGS_MISS": {"base_impact": -0.030, "direction": -1, "severity": "HIGH"},
    "LARGE_ORDER_WIN": {"base_impact": 0.018, "direction": 1, "severity": "MEDIUM"},
    "REGULATORY_ACTION": {"base_impact": -0.025, "direction": -1, "severity": "HIGH"},
    "TARIFF_HIKE": {"base_impact": 0.022, "direction": 1, "severity": "HIGH"},
    "DIVIDEND_BUYBACK": {"base_impact": 0.012, "direction": 1, "severity": "LOW"},
    "MANAGEMENT_CHANGE": {"base_impact": -0.010, "direction": -1, "severity": "MEDIUM"},
    "RBI_POLICY_HAWKISH": {"base_impact": -0.015, "direction": -1, "severity": "HIGH"},
    "RBI_POLICY_DOVISH": {"base_impact": 0.015, "direction": 1, "severity": "HIGH"},
    "GENERAL_BULLISH_NEWS": {"base_impact": 0.010, "direction": 1, "severity": "LOW"},
    "GENERAL_BEARISH_NEWS": {"base_impact": -0.010, "direction": -1, "severity": "LOW"},
    "NEUTRAL_UPDATE": {"base_impact": 0.000, "direction": 0, "severity": "LOW"}
}

# Trading Simulation Defaults
INITIAL_CAPITAL = 100_000.0   # ₹1 Lakh paper portfolio
ALLOCATION_PER_STOCK = 10_000.0  # ₹10,000 per trade
CONFIDENCE_THRESHOLD_TRADE = 60.0  # Minimum conviction score (0-100) to trigger BUY/SELL
