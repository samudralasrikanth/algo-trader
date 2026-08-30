# =============================================================================
# event_agent/collectors/event_calendar.py — Corporate & Macro Event Calendar
# =============================================================================

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

from ..config import NIFTY50_UNIVERSE

# Macro Scheduled Events (RBI MPC Meetings, CPI Releases, Union Budget)
SCHEDULED_MACRO_EVENTS = [
    {"date": "2026-02-01", "type": "UNION_BUDGET", "title": "Union Budget 2026-27 Presentation", "impact": "HIGH", "affected_sectors": ["ALL", "Infrastructure", "FMCG", "Banking"]},
    {"date": "2026-02-06", "type": "RBI_POLICY_MEET", "title": "RBI MPC Monetary Policy Decision", "impact": "HIGH", "affected_sectors": ["Banking", "Automobile", "Real Estate"]},
    {"date": "2026-03-12", "type": "MACRO_CPI", "title": "India CPI Inflation & IIP Data Release", "impact": "MEDIUM", "affected_sectors": ["ALL"]},
    {"date": "2026-04-09", "type": "RBI_POLICY_MEET", "title": "RBI MPC Bi-Monthly Policy Statement", "impact": "HIGH", "affected_sectors": ["Banking", "Automobile"]},
    {"date": "2026-05-13", "type": "MACRO_CPI", "title": "India April CPI Inflation Release", "impact": "MEDIUM", "affected_sectors": ["ALL"]},
    {"date": "2026-06-05", "type": "RBI_POLICY_MEET", "title": "RBI MPC Rate & Stance Announcement", "impact": "HIGH", "affected_sectors": ["Banking", "Automobile"]},
    {"date": "2026-07-14", "type": "MACRO_CPI", "title": "India June CPI Inflation Release", "impact": "MEDIUM", "affected_sectors": ["ALL"]},
    {"date": "2026-08-07", "type": "RBI_POLICY_MEET", "title": "RBI MPC Monetary Policy Review", "impact": "HIGH", "affected_sectors": ["Banking", "Automobile"]},
    {"date": "2026-09-12", "type": "MACRO_CPI", "title": "India August CPI Inflation Release", "impact": "MEDIUM", "affected_sectors": ["ALL"]},
    {"date": "2026-10-08", "type": "RBI_POLICY_MEET", "title": "RBI MPC Monetary Policy Decision", "impact": "HIGH", "affected_sectors": ["Banking", "Automobile"]},
    {"date": "2026-11-12", "type": "MACRO_CPI", "title": "India October CPI Inflation Data", "impact": "MEDIUM", "affected_sectors": ["ALL"]},
    {"date": "2026-12-04", "type": "RBI_POLICY_MEET", "title": "RBI MPC Bi-Monthly Policy Statement", "impact": "HIGH", "affected_sectors": ["Banking", "Automobile"]},
]

# Corporate Events Calendar per Ticker (Earnings, AGMs, Dividends, Strategic Catalyst)
CORPORATE_EVENTS_REGISTRY = {
    "RELIANCE.NS": [
        {"date": "2026-01-19", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Financial Results & Retail Segment Numbers", "impact": "HIGH"},
        {"date": "2026-04-24", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Audited Annual & Quarterly Results", "impact": "HIGH"},
        {"date": "2026-07-18", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Financial Results & Jio ARPU Update", "impact": "HIGH"},
        {"date": "2026-08-28", "type": "ANNUAL_GENERAL_MEET", "title": "Reliance 49th AGM — Jio IPO Timeline & New Energy Updates", "impact": "HIGH"},
        {"date": "2026-10-19", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Financial Results", "impact": "HIGH"},
        {"date": "2026-08-14", "type": "DIVIDEND_EX_DATE", "title": "Final Dividend ₹10 per share Ex-Date", "impact": "LOW"}
    ],
    "HDFCBANK.NS": [
        {"date": "2026-01-16", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Net Profit, NIM & Deposit Growth Report", "impact": "HIGH"},
        {"date": "2026-04-18", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Audited Results & Dividend Declaration", "impact": "HIGH"},
        {"date": "2026-05-08", "type": "DIVIDEND_EX_DATE", "title": "Dividend Ex-Date ₹19.50 per share", "impact": "LOW"},
        {"date": "2026-07-19", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Results — Deposit Accretion & CD Ratio Update", "impact": "HIGH"},
        {"date": "2026-10-17", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Quarterly Earnings & Credit Cost Review", "impact": "HIGH"},
    ],
    "ICICIBANK.NS": [
        {"date": "2026-01-24", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Earnings — Core Operating Profit Growth", "impact": "HIGH"},
        {"date": "2026-04-25", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Financial Results & Asset Quality Audit", "impact": "HIGH"},
        {"date": "2026-06-12", "type": "DIVIDEND_EX_DATE", "title": "Dividend ₹10.00 Ex-Date", "impact": "LOW"},
        {"date": "2026-07-25", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Net Interest Income & Margin Report", "impact": "HIGH"},
        {"date": "2026-10-24", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Earnings Announcement", "impact": "HIGH"},
    ],
    "TCS.NS": [
        {"date": "2026-01-09", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Earnings Kickoff & TCV Deal Inflows", "impact": "HIGH"},
        {"date": "2026-04-10", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Annual Results & Special Dividend", "impact": "HIGH"},
        {"date": "2026-05-15", "type": "DIVIDEND_EX_DATE", "title": "Final Dividend Ex-Date ₹28 per share", "impact": "LOW"},
        {"date": "2026-07-09", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Earnings & AI Transformation Pipeline", "impact": "HIGH"},
        {"date": "2026-10-09", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Results & North American Client Demand", "impact": "HIGH"},
    ],
    "INFY.NS": [
        {"date": "2026-01-15", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Results & Annual FY26 Revenue Guidance Update", "impact": "HIGH"},
        {"date": "2026-04-16", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Results & FY27 Guidance Announcement", "impact": "HIGH"},
        {"date": "2026-05-28", "type": "DIVIDEND_EX_DATE", "title": "Dividend ₹20.00 per share Ex-Date", "impact": "LOW"},
        {"date": "2026-07-16", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Revenue Growth & Operating Margin Report", "impact": "HIGH"},
        {"date": "2026-10-15", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Results & Deal Wins Pipeline Review", "impact": "HIGH"},
    ],
    "BHARTIARTL.NS": [
        {"date": "2026-02-05", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Financial Results & Average ARPU Expansion", "impact": "HIGH"},
        {"date": "2026-05-14", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Results & 5G Capex Peak Review", "impact": "HIGH"},
        {"date": "2026-07-01", "type": "TARIFF_HIKE_ANNOUNCEMENT", "title": "Headline Telecom Tariff Revision & Data Pack Pricing", "impact": "HIGH"},
        {"date": "2026-08-05", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Earnings — ARPU Crossing ₹225 Target", "impact": "HIGH"},
        {"date": "2026-11-04", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Results & Africa FX Impact Update", "impact": "HIGH"},
    ],
    "SBIN.NS": [
        {"date": "2026-02-03", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Results — Record Net Profit & Low Credit Costs", "impact": "HIGH"},
        {"date": "2026-05-09", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Annual Results & Capital Adequacy Ratio", "impact": "HIGH"},
        {"date": "2026-05-22", "type": "DIVIDEND_EX_DATE", "title": "Dividend ₹13.70 per share Ex-Date", "impact": "LOW"},
        {"date": "2026-08-03", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Earnings & Corporate Loan Pipeline", "impact": "HIGH"},
        {"date": "2026-11-06", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Results & Retail Loan Book Performance", "impact": "HIGH"},
    ],
    "LT.NS": [
        {"date": "2026-01-30", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Results & International Order Book Update", "impact": "HIGH"},
        {"date": "2026-05-08", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Results & FY27 Inflow Guidance", "impact": "HIGH"},
        {"date": "2026-06-19", "type": "DIVIDEND_EX_DATE", "title": "Dividend ₹28.00 Ex-Date", "impact": "LOW"},
        {"date": "2026-07-28", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Orders, Revenue & Margin Realization", "impact": "HIGH"},
        {"date": "2026-10-28", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Financial Results & Capex Execution Pace", "impact": "HIGH"},
    ],
    "ITC.NS": [
        {"date": "2026-01-29", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Results — Cigarette Volumes & Agri Margins", "impact": "HIGH"},
        {"date": "2026-05-21", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Results & ITC Hotels Demerger Scheme Progress", "impact": "HIGH"},
        {"date": "2026-06-04", "type": "DIVIDEND_EX_DATE", "title": "Final Dividend ₹7.50 Ex-Date", "impact": "LOW"},
        {"date": "2026-08-01", "type": "EARNINGS_RELEASE", "title": "Q1 FY27 Results & FMCG Margin Expansion", "impact": "HIGH"},
        {"date": "2026-10-22", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Earnings Announcement", "impact": "HIGH"},
    ],
    "MARUTI.NS": [
        {"date": "2026-01-31", "type": "EARNINGS_RELEASE", "title": "Q3 FY26 Results & Utility Vehicle Margin Expansion", "impact": "HIGH"},
        {"date": "2026-04-28", "type": "EARNINGS_RELEASE", "title": "Q4 FY26 Annual Results & Highest Ever Dividend", "impact": "HIGH"},
        {"date": "2026-08-01", "type": "AUTO_MONTHLY_SALES", "title": "Monthly Wholesales Cross 190,000 Units Record", "impact": "HIGH"},
        {"date": "2026-08-05", "type": "DIVIDEND_EX_DATE", "title": "Final Dividend ₹125.00 Ex-Date", "impact": "LOW"},
        {"date": "2026-10-29", "type": "EARNINGS_RELEASE", "title": "Q2 FY27 Results & Festive Season Order Book", "impact": "HIGH"},
    ]
}


def get_stock_events(symbol: str, reference_date: Optional[date] = None, window_days: int = 14) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get occurred (past window_days) and upcoming (next window_days) events for a stock relative to reference_date.
    """
    if reference_date is None:
        reference_date = datetime.now().date()
        
    events = CORPORATE_EVENTS_REGISTRY.get(symbol, [])
    
    occurred = []
    upcoming = []
    
    for ev in events:
        ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        diff_days = (ev_date - reference_date).days
        
        ev_copy = dict(ev)
        ev_copy["days_away"] = diff_days
        ev_copy["date_str"] = ev["date"]
        
        if -window_days <= diff_days <= 0:
            ev_copy["status"] = "OCCURRED_RECENTLY"
            occurred.append(ev_copy)
        elif 0 < diff_days <= window_days:
            ev_copy["status"] = "UPCOMING"
            upcoming.append(ev_copy)
            
    # Sort occurred descending (most recent first), upcoming ascending (nearest first)
    occurred.sort(key=lambda x: x["days_away"], reverse=True)
    upcoming.sort(key=lambda x: x["days_away"])
    
    return {
        "occurred": occurred,
        "upcoming": upcoming
    }


def get_macro_events(reference_date: Optional[date] = None, window_days: int = 14) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get occurred and upcoming macroeconomic events relative to reference_date.
    """
    if reference_date is None:
        reference_date = datetime.now().date()
        
    occurred = []
    upcoming = []
    
    for ev in SCHEDULED_MACRO_EVENTS:
        ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        diff_days = (ev_date - reference_date).days
        
        ev_copy = dict(ev)
        ev_copy["days_away"] = diff_days
        ev_copy["date_str"] = ev["date"]
        
        if -window_days <= diff_days <= 0:
            ev_copy["status"] = "OCCURRED_RECENTLY"
            occurred.append(ev_copy)
        elif 0 < diff_days <= window_days:
            ev_copy["status"] = "UPCOMING"
            upcoming.append(ev_copy)
            
    occurred.sort(key=lambda x: x["days_away"], reverse=True)
    upcoming.sort(key=lambda x: x["days_away"])
    
    return {
        "occurred": occurred,
        "upcoming": upcoming
    }


def scan_all_upcoming_events(reference_date: Optional[date] = None, window_days: int = 30) -> List[Dict[str, Any]]:
    """
    Produce a consolidated upcoming catalyst timeline for all 10 stocks and macro events.
    """
    if reference_date is None:
        reference_date = datetime.now().date()
        
    all_upcoming = []
    
    # Macro
    macro = get_macro_events(reference_date, window_days=window_days)
    for ev in macro["upcoming"]:
        item = dict(ev)
        item["category"] = "MACRO"
        item["symbol"] = "MACRO"
        item["entity"] = "Indian Economy / RBI"
        all_upcoming.append(item)
        
    # Per stock
    for sym, meta in NIFTY50_UNIVERSE.items():
        stk_evs = get_stock_events(sym, reference_date, window_days=window_days)
        for ev in stk_evs["upcoming"]:
            item = dict(ev)
            item["category"] = "EQUITY"
            item["symbol"] = sym
            item["entity"] = meta["short_name"]
            all_upcoming.append(item)
            
    all_upcoming.sort(key=lambda x: x["days_away"])
    return all_upcoming
