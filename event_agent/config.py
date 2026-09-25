# =============================================================================
# event_agent/config.py — Nifty 50 Universe & V3.2 Arena Configuration
# =============================================================================

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
DB_PATH = DATA_DIR / "event_predictions.db"

# V3.2 Arena Constants
TOTAL_VIRTUAL_CAPITAL = 1_00_00_000.0   # ₹1 Crore total virtual capital
AGENT_STARTING_CAPITAL = 20_00_000.0    # ₹20 Lakhs per agent
NUM_ARENA_AGENTS = 5
MAX_ACTIVE_POSITIONS_PER_AGENT = 10     # Dynamic 0 to 10 active positions

# V3.2 Research Risk Parameters
MAX_RISK_PER_TRADE_PCT = 0.5            # 0.5% portfolio risk per trade
MAX_SINGLE_POSITION_ALLOCATION_PCT = 20.0 # Max 20% capital in single stock
MAX_PORTFOLIO_EXPOSURE_PCT = 50.0       # Max 50% capital deployed
MAX_CORRELATED_EXPOSURE_PCT = 25.0      # Max 25% exposure per sector
MIN_CONFIDENCE_PCT = float(os.getenv("MIN_AGENT_CONVICTION", "60.0")) # Minimum calibrated conviction hurdle
DAILY_LOSS_LIMIT_PCT = 1.5              # 1.5% daily loss limit circuit breaker
DRAWDOWN_WARNING_PCT = 20.0             # 20% drawdown alert
DRAWDOWN_SUSPEND_PCT = 30.0             # 30% drawdown suspension

# Frozen Agent Strategy Versions
STRATEGY_VERSIONS = {
    "ALPHA": "ALPHA-1.0",
    "MOMENTUM": "MOMENTUM-1.0",
    "MACRO": "MACRO-1.0",
    "DEFENSIVE": "DEFENSIVE-1.0",
    "CONTRARIAN": "CONTRARIAN-1.0",
}

# 50 Nifty Constituents with Point-in-Time Validity
NIFTY50_UNIVERSE = {
    "RELIANCE.NS": {
        "name": "Reliance Industries Ltd",
        "short_name": "Reliance",
        "sector": "Oil & Gas / Conglomerate",
        "beta": 1.1,
        "key_drivers": [
            "Refining GRM",
            "Jio ARPU",
            "Retail footfall"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Reliance Industries Ltd",
            "Reliance",
            "RELIANCE NSE",
            "Reliance results"
        ]
    },
    "HDFCBANK.NS": {
        "name": "HDFC Bank Ltd",
        "short_name": "HDFC Bank",
        "sector": "Private Banking",
        "beta": 0.95,
        "key_drivers": [
            "NIMs",
            "Deposit growth",
            "RBI repo rate"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "HDFC Bank Ltd",
            "HDFC Bank",
            "HDFCBANK NSE",
            "HDFC Bank results"
        ]
    },
    "ICICIBANK.NS": {
        "name": "ICICI Bank Ltd",
        "short_name": "ICICI Bank",
        "sector": "Private Banking",
        "beta": 1.05,
        "key_drivers": [
            "Domestic loan growth",
            "Retail margins",
            "Asset quality"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "ICICI Bank Ltd",
            "ICICI Bank",
            "ICICIBANK NSE",
            "ICICI Bank results"
        ]
    },
    "TCS.NS": {
        "name": "Tata Consultancy Services Ltd",
        "short_name": "TCS",
        "sector": "IT Services",
        "beta": 0.85,
        "key_drivers": [
            "Global IT spending",
            "TCV deal wins",
            "Operating margins"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Tata Consultancy Services Ltd",
            "TCS",
            "TCS NSE",
            "TCS results"
        ]
    },
    "INFY.NS": {
        "name": "Infosys Ltd",
        "short_name": "Infosys",
        "sector": "IT Services",
        "beta": 0.9,
        "key_drivers": [
            "Revenue guidance",
            "BFSI tech demand",
            "Large deal wins"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Infosys Ltd",
            "Infosys",
            "INFY NSE",
            "Infosys results"
        ]
    },
    "BHARTIARTL.NS": {
        "name": "Bharti Airtel Ltd",
        "short_name": "Bharti Airtel",
        "sector": "Telecommunications",
        "beta": 0.8,
        "key_drivers": [
            "ARPU tariff hikes",
            "5G subscriber growth",
            "Africa business"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Bharti Airtel Ltd",
            "Bharti Airtel",
            "BHARTIARTL NSE",
            "Bharti Airtel results"
        ]
    },
    "SBIN.NS": {
        "name": "State Bank of India",
        "short_name": "SBI",
        "sector": "PSU Banking",
        "beta": 1.2,
        "key_drivers": [
            "Public sector capex",
            "Corporate credit cycle",
            "Slippages"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "State Bank of India",
            "SBI",
            "SBIN NSE",
            "SBI results"
        ]
    },
    "LT.NS": {
        "name": "Larsen & Toubro Ltd",
        "short_name": "L&T",
        "sector": "Infrastructure",
        "beta": 1.15,
        "key_drivers": [
            "Government capex",
            "Order book inflows",
            "Execution pace"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Larsen & Toubro Ltd",
            "L&T",
            "LT NSE",
            "L&T results"
        ]
    },
    "ITC.NS": {
        "name": "ITC Ltd",
        "short_name": "ITC",
        "sector": "FMCG / Diversified",
        "beta": 0.65,
        "key_drivers": [
            "Cigarette volumes",
            "FMCG margins",
            "Hotels demerger"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "ITC Ltd",
            "ITC",
            "ITC NSE",
            "ITC results"
        ]
    },
    "MARUTI.NS": {
        "name": "Maruti Suzuki India Ltd",
        "short_name": "Maruti Suzuki",
        "sector": "Automobile",
        "beta": 1.05,
        "key_drivers": [
            "Monthly auto wholesale",
            "Rural demand",
            "Yen exchange rate"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Maruti Suzuki India Ltd",
            "Maruti Suzuki",
            "MARUTI NSE",
            "Maruti Suzuki results"
        ]
    },
    "AXISBANK.NS": {
        "name": "Axis Bank Ltd",
        "short_name": "Axis Bank",
        "sector": "Private Banking",
        "beta": 1.12,
        "key_drivers": [
            "Credit costs",
            "Retail lending",
            "NIM margins"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Axis Bank Ltd",
            "Axis Bank",
            "AXISBANK NSE",
            "Axis Bank results"
        ]
    },
    "KOTAKBANK.NS": {
        "name": "Kotak Mahindra Bank Ltd",
        "short_name": "Kotak Bank",
        "sector": "Private Banking",
        "beta": 0.92,
        "key_drivers": [
            "CASA ratio",
            "Tech regulatory compliance",
            "Wealth management"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Kotak Mahindra Bank Ltd",
            "Kotak Bank",
            "KOTAKBANK NSE",
            "Kotak Bank results"
        ]
    },
    "HINDUNILVR.NS": {
        "name": "Hindustan Unilever Ltd",
        "short_name": "Hindustan Unilever",
        "sector": "FMCG",
        "beta": 0.6,
        "key_drivers": [
            "Rural consumption",
            "Raw material palm oil costs",
            "Volume growth"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Hindustan Unilever Ltd",
            "Hindustan Unilever",
            "HINDUNILVR NSE",
            "Hindustan Unilever results"
        ]
    },
    "BAJFINANCE.NS": {
        "name": "Bajaj Finance Ltd",
        "short_name": "Bajaj Finance",
        "sector": "Financial Services / NBFC",
        "beta": 1.25,
        "key_drivers": [
            "AUM growth",
            "Consumer durable loan demand",
            "Cost of funds"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Bajaj Finance Ltd",
            "Bajaj Finance",
            "BAJFINANCE NSE",
            "Bajaj Finance results"
        ]
    },
    "BAJAJFINSV.NS": {
        "name": "Bajaj Finserv Ltd",
        "short_name": "Bajaj Finserv",
        "sector": "Financial Services",
        "beta": 1.2,
        "key_drivers": [
            "Bajaj Finance performance",
            "Insurance premium growth",
            "Fintech expansion"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Bajaj Finserv Ltd",
            "Bajaj Finserv",
            "BAJAJFINSV NSE",
            "Bajaj Finserv results"
        ]
    },
    "HCLTECH.NS": {
        "name": "HCL Technologies Ltd",
        "short_name": "HCL Tech",
        "sector": "IT Services",
        "beta": 0.88,
        "key_drivers": [
            "Engineering R&D services",
            "Product business seasonality",
            "Attrition rate"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "HCL Technologies Ltd",
            "HCL Tech",
            "HCLTECH NSE",
            "HCL Tech results"
        ]
    },
    "SUNPHARMA.NS": {
        "name": "Sun Pharmaceutical Industries Ltd",
        "short_name": "Sun Pharma",
        "sector": "Pharmaceuticals",
        "beta": 0.7,
        "key_drivers": [
            "US generic sales",
            "Global specialty portfolio",
            "USFDA compliance"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Sun Pharmaceutical Industries Ltd",
            "Sun Pharma",
            "SUNPHARMA NSE",
            "Sun Pharma results"
        ]
    },
    "TATAMOTORS.NS": {
        "name": "Tata Motors Ltd",
        "short_name": "Tata Motors",
        "sector": "Automobile",
        "beta": 1.3,
        "key_drivers": [
            "JLR order book & margins",
            "India EV market share",
            "Commercial vehicle cycle"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Tata Motors Ltd",
            "Tata Motors",
            "TATAMOTORS NSE",
            "Tata Motors results"
        ]
    },
    "TATASTEEL.NS": {
        "name": "Tata Steel Ltd",
        "short_name": "Tata Steel",
        "sector": "Metals & Mining",
        "beta": 1.35,
        "key_drivers": [
            "Global steel prices",
            "China export dump",
            "UK transition grant"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Tata Steel Ltd",
            "Tata Steel",
            "TATASTEEL NSE",
            "Tata Steel results"
        ]
    },
    "NTPC.NS": {
        "name": "NTPC Ltd",
        "short_name": "NTPC",
        "sector": "Power / Utilities",
        "beta": 0.82,
        "key_drivers": [
            "Power demand peak loads",
            "Coal availability",
            "Renewable green energy IPO"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "NTPC Ltd",
            "NTPC",
            "NTPC NSE",
            "NTPC results"
        ]
    },
    "POWERGRID.NS": {
        "name": "Power Grid Corporation of India Ltd",
        "short_name": "Power Grid",
        "sector": "Power Transmission",
        "beta": 0.75,
        "key_drivers": [
            "Inter-state transmission capex",
            "Capitalization targets",
            "Regulated equity return"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Power Grid Corporation of India Ltd",
            "Power Grid",
            "POWERGRID NSE",
            "Power Grid results"
        ]
    },
    "ONGC.NS": {
        "name": "Oil & Natural Gas Corporation Ltd",
        "short_name": "ONGC",
        "sector": "Oil & Gas Exploration",
        "beta": 1.15,
        "key_drivers": [
            "Brent crude prices",
            "Domestic gas price cap",
            "Offshore production"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Oil & Natural Gas Corporation Ltd",
            "ONGC",
            "ONGC NSE",
            "ONGC results"
        ]
    },
    "TITAN.NS": {
        "name": "Titan Company Ltd",
        "short_name": "Titan",
        "sector": "Consumer Discretionary",
        "beta": 0.98,
        "key_drivers": [
            "Gold import duty cuts",
            "Wedding season jewelry buying",
            "Store addition pace"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Titan Company Ltd",
            "Titan",
            "TITAN NSE",
            "Titan results"
        ]
    },
    "ADANIENT.NS": {
        "name": "Adani Enterprises Ltd",
        "short_name": "Adani Enterprises",
        "sector": "Diversified Conglomerate",
        "beta": 1.65,
        "key_drivers": [
            "Airports passenger traffic",
            "Green hydrogen capex",
            "Mining services"
        ],
        "effective_from": "2022-09-30",
        "effective_to": None,
        "search_terms": [
            "Adani Enterprises Ltd",
            "Adani Enterprises",
            "ADANIENT NSE",
            "Adani Enterprises results"
        ]
    },
    "ADANIPORTS.NS": {
        "name": "Adani Ports & SEZ Ltd",
        "short_name": "Adani Ports",
        "sector": "Logistics & Ports",
        "beta": 1.28,
        "key_drivers": [
            "Cargo throughput volumes",
            "Container market share",
            "Port acquisitions"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Adani Ports & SEZ Ltd",
            "Adani Ports",
            "ADANIPORTS NSE",
            "Adani Ports results"
        ]
    },
    "ULTRACEMCO.NS": {
        "name": "UltraTech Cement Ltd",
        "short_name": "UltraTech Cement",
        "sector": "Materials / Cement",
        "beta": 1.05,
        "key_drivers": [
            "Cement realization prices",
            "Petcoke / energy costs",
            "Infra capex demand"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "UltraTech Cement Ltd",
            "UltraTech Cement",
            "ULTRACEMCO NSE",
            "UltraTech Cement results"
        ]
    },
    "COALINDIA.NS": {
        "name": "Coal India Ltd",
        "short_name": "Coal India",
        "sector": "Energy / Mining",
        "beta": 0.85,
        "key_drivers": [
            "Thermal plant dispatches",
            "E-auction premium realization",
            "Dividend yield"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Coal India Ltd",
            "Coal India",
            "COALINDIA NSE",
            "Coal India results"
        ]
    },
    "ASIANPAINT.NS": {
        "name": "Asian Paints Ltd",
        "short_name": "Asian Paints",
        "sector": "Consumer Discretionary",
        "beta": 0.8,
        "key_drivers": [
            "Decorative paints competition",
            "Crude-linked titanium dioxide costs",
            "Repainting demand"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Asian Paints Ltd",
            "Asian Paints",
            "ASIANPAINT NSE",
            "Asian Paints results"
        ]
    },
    "JSWSTEEL.NS": {
        "name": "JSW Steel Ltd",
        "short_name": "JSW Steel",
        "sector": "Metals & Mining",
        "beta": 1.3,
        "key_drivers": [
            "Domestic infra steel demand",
            "Coking coal import costs",
            "Capacity expansion"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "JSW Steel Ltd",
            "JSW Steel",
            "JSWSTEEL NSE",
            "JSW Steel results"
        ]
    },
    "M&M.NS": {
        "name": "Mahindra & Mahindra Ltd",
        "short_name": "M&M",
        "sector": "Automobile",
        "beta": 1.18,
        "key_drivers": [
            "SUV waiting periods",
            "Tractor sales monsoon correlation",
            "Farm machinery"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Mahindra & Mahindra Ltd",
            "M&M",
            "M&M NSE",
            "M&M results"
        ]
    },
    "GRASIM.NS": {
        "name": "Grasim Industries Ltd",
        "short_name": "Grasim",
        "sector": "Materials / Diversified",
        "beta": 1.1,
        "key_drivers": [
            "Birla Opus paint rollout",
            "VSF pulp prices",
            "Chemicals division margins"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Grasim Industries Ltd",
            "Grasim",
            "GRASIM NSE",
            "Grasim results"
        ]
    },
    "CIPLA.NS": {
        "name": "Cipla Ltd",
        "short_name": "Cipla",
        "sector": "Pharmaceuticals",
        "beta": 0.65,
        "key_drivers": [
            "Respiratory Albuterol market share",
            "Domestic prescription formulations",
            "US generic pipeline"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Cipla Ltd",
            "Cipla",
            "CIPLA NSE",
            "Cipla results"
        ]
    },
    "TECHM.NS": {
        "name": "Tech Mahindra Ltd",
        "short_name": "Tech Mahindra",
        "sector": "IT Services",
        "beta": 1.1,
        "key_drivers": [
            "Telecom client 5G capex turnaround",
            "Project Fortius margins",
            "Enterprise cloud spending"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Tech Mahindra Ltd",
            "Tech Mahindra",
            "TECHM NSE",
            "Tech Mahindra results"
        ]
    },
    "WIPRO.NS": {
        "name": "Wipro Ltd",
        "short_name": "Wipro",
        "sector": "IT Services",
        "beta": 0.95,
        "key_drivers": [
            "Capco consulting recovery",
            "Top client ramp downs",
            "Operating margin recovery"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Wipro Ltd",
            "Wipro",
            "WIPRO NSE",
            "Wipro results"
        ]
    },
    "DRREDDY.NS": {
        "name": "Dr. Reddy Laboratories Ltd",
        "short_name": "Dr. Reddy",
        "sector": "Pharmaceuticals",
        "beta": 0.72,
        "key_drivers": [
            "Revlimid generic contributions",
            "USFDA facility inspections",
            "Biosimilars launch pace"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Dr. Reddy Laboratories Ltd",
            "Dr. Reddy",
            "DRREDDY NSE",
            "Dr. Reddy results"
        ]
    },
    "APOLLOHOSP.NS": {
        "name": "Apollo Hospitals Enterprise Ltd",
        "short_name": "Apollo Hospitals",
        "sector": "Healthcare",
        "beta": 0.85,
        "key_drivers": [
            "Inpatient ARPOB",
            "Occupancy levels",
            "Apollo 24/7 digital breakeven"
        ],
        "effective_from": "2022-03-31",
        "effective_to": None,
        "search_terms": [
            "Apollo Hospitals Enterprise Ltd",
            "Apollo Hospitals",
            "APOLLOHOSP NSE",
            "Apollo Hospitals results"
        ]
    },
    "DIVISLAB.NS": {
        "name": "Divi Laboratories Ltd",
        "short_name": "Divis Lab",
        "sector": "Pharmaceuticals / API",
        "beta": 0.9,
        "key_drivers": [
            "Custom synthesis contracts",
            "API raw material prices",
            "GLP-1 generic intermediates"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Divi Laboratories Ltd",
            "Divis Lab",
            "DIVISLAB NSE",
            "Divis Lab results"
        ]
    },
    "EICHERMOT.NS": {
        "name": "Eicher Motors Ltd",
        "short_name": "Eicher Motors",
        "sector": "Automobile / Two-Wheelers",
        "beta": 0.95,
        "key_drivers": [
            "Royal Enfield monthly bookings",
            "Premium motorcycle competition",
            "VECV commercial trucks"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Eicher Motors Ltd",
            "Eicher Motors",
            "EICHERMOT NSE",
            "Eicher Motors results"
        ]
    },
    "HEROMOTOCO.NS": {
        "name": "Hero MotoCorp Ltd",
        "short_name": "Hero MotoCorp",
        "sector": "Automobile / Two-Wheelers",
        "beta": 0.92,
        "key_drivers": [
            "Entry-level 100cc rural bike demand",
            "Vida EV scale up",
            "Premium 400cc portfolio"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Hero MotoCorp Ltd",
            "Hero MotoCorp",
            "HEROMOTOCO NSE",
            "Hero MotoCorp results"
        ]
    },
    "BPCL.NS": {
        "name": "Bharat Petroleum Corporation Ltd",
        "short_name": "BPCL",
        "sector": "Oil & Gas / Refining",
        "beta": 1.15,
        "key_drivers": [
            "Auto fuel marketing margins",
            "Crude discount impact",
            "Divestment speculation"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Bharat Petroleum Corporation Ltd",
            "BPCL",
            "BPCL NSE",
            "BPCL results"
        ]
    },
    "TATACONSUM.NS": {
        "name": "Tata Consumer Products Ltd",
        "short_name": "Tata Consumer",
        "sector": "FMCG",
        "beta": 0.75,
        "key_drivers": [
            "Tata Tea volumes",
            "Tata Salt market share",
            "Ching Secret capital deployment"
        ],
        "effective_from": "2021-03-31",
        "effective_to": None,
        "search_terms": [
            "Tata Consumer Products Ltd",
            "Tata Consumer",
            "TATACONSUM NSE",
            "Tata Consumer results"
        ]
    },
    "BRITANNIA.NS": {
        "name": "Britannia Industries Ltd",
        "short_name": "Britannia",
        "sector": "FMCG",
        "beta": 0.65,
        "key_drivers": [
            "Biscuit volume growth",
            "Wheat and dairy input inflation",
            "Product innovations"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Britannia Industries Ltd",
            "Britannia",
            "BRITANNIA NSE",
            "Britannia results"
        ]
    },
    "NESTLEIND.NS": {
        "name": "Nestle India Ltd",
        "short_name": "Nestle India",
        "sector": "FMCG",
        "beta": 0.55,
        "key_drivers": [
            "Maggi and packaged noodles demand",
            "Milk and cocoa input prices",
            "Tier-2/3 penetration"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Nestle India Ltd",
            "Nestle India",
            "NESTLEIND NSE",
            "Nestle India results"
        ]
    },
    "HINDALCO.NS": {
        "name": "Hindalco Industries Ltd",
        "short_name": "Hindalco",
        "sector": "Metals / Aluminium",
        "beta": 1.35,
        "key_drivers": [
            "LME Aluminium cash prices",
            "Novelis beverage can shipments",
            "Coal linkage costs"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Hindalco Industries Ltd",
            "Hindalco",
            "HINDALCO NSE",
            "Hindalco results"
        ]
    },
    "SBILIFE.NS": {
        "name": "SBI Life Insurance Company Ltd",
        "short_name": "SBI Life",
        "sector": "Life Insurance",
        "beta": 0.88,
        "key_drivers": [
            "Annualized Premium Equivalent (APE)",
            "Value of New Business (VNB) margin",
            "SBI bancassurance tie-up"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "SBI Life Insurance Company Ltd",
            "SBI Life",
            "SBILIFE NSE",
            "SBI Life results"
        ]
    },
    "HDFCLIFE.NS": {
        "name": "HDFC Life Insurance Company Ltd",
        "short_name": "HDFC Life",
        "sector": "Life Insurance",
        "beta": 0.9,
        "key_drivers": [
            "Non-par savings mix",
            "Surrender value regulatory guidelines",
            "HDFC Bank distribution"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "HDFC Life Insurance Company Ltd",
            "HDFC Life",
            "HDFCLIFE NSE",
            "HDFC Life results"
        ]
    },
    "BAJAJ-AUTO.NS": {
        "name": "Bajaj Auto Ltd",
        "short_name": "Bajaj Auto",
        "sector": "Automobile / Two-Wheelers",
        "beta": 0.88,
        "key_drivers": [
            "Three-wheeler EV adoption",
            "Export recovery to Africa/LatAm",
            "Triumph / Chetak bookings"
        ],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "search_terms": [
            "Bajaj Auto Ltd",
            "Bajaj Auto",
            "BAJAJ-AUTO NSE",
            "Bajaj Auto results"
        ]
    },
    "SHRIRAMFIN.NS": {
        "name": "Shriram Finance Ltd",
        "short_name": "Shriram Finance",
        "sector": "Financial Services / NBFC",
        "beta": 1.3,
        "key_drivers": [
            "Used commercial vehicle loan demand",
            "Monsoon impact on rural credit",
            "Merger synergy realization"
        ],
        "effective_from": "2024-03-28",
        "effective_to": None,
        "search_terms": [
            "Shriram Finance Ltd",
            "Shriram Finance",
            "SHRIRAMFIN NSE",
            "Shriram Finance results"
        ]
    },
    "BEL.NS": {
        "name": "Bharat Electronics Ltd",
        "short_name": "BEL",
        "sector": "Defense / Capital Goods",
        "beta": 1.1,
        "key_drivers": [
            "Indigenous defense radar orders",
            "Electronic warfare systems",
            "Budgetary defense outlay"
        ],
        "effective_from": "2024-09-30",
        "effective_to": None,
        "search_terms": [
            "Bharat Electronics Ltd",
            "BEL",
            "BEL NSE",
            "BEL results"
        ]
    },
    "TRENT.NS": {
        "name": "Trent Ltd",
        "short_name": "Trent",
        "sector": "Retail / Consumer Discretionary",
        "beta": 1.22,
        "key_drivers": [
            "Zudio fast-fashion store additions",
            "Westside same-store sales growth",
            "Star Bazaar expansion"
        ],
        "effective_from": "2024-09-30",
        "effective_to": None,
        "search_terms": [
            "Trent Ltd",
            "Trent",
            "TRENT NSE",
            "Trent results"
        ]
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

# Legacy Compatibility Sizing
INITIAL_CAPITAL = 100_000.0
ALLOCATION_PER_STOCK = 10_000.0
CONFIDENCE_THRESHOLD_TRADE = 60.0
