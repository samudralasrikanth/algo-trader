# =============================================================================
# event_agent/arena/market_clock.py — Market Clock & Decision Cycle State Machine
# =============================================================================
"""
Deterministic Market Clock State Machine governing the trading lifecycle
in Indian Standard Time (IST / Asia/Kolkata).

Market Lifecycle Phases:
  WEEKEND_HOLIDAY   -> Saturday, Sunday, or NSE Holiday. UI displays last frozen snapshot.
  PRE_MARKET        -> 20:30 (prior day) to 09:15. Snapshots locked, agents propose 0-10 trades.
  MARKET_OPEN       -> 09:15 to 09:30. Opening print, Risk Engine validates and approves proposals.
  INTRADAY          -> 09:30 to 15:30. 5-min candle execution, continuous stop monitoring.
  MARKET_CLOSE      -> 15:30 to 15:45. STRICT CUTOFF: No new trades accepted. Mark-to-market close.
  POST_MARKET_AUDIT -> 15:45 to 16:30. Post-market audit reconciles closes, computes factor attributions.
  DAY_COMPLETE      -> 16:30 to 20:30. Daily NAV, Leaderboard rankings & trophies frozen.
"""

from datetime import datetime, date, time, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple

# Try zoneinfo, fallback to timezone offset
try:
    from zoneinfo import ZoneInfo
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")


class MarketPhase(str, Enum):
    WEEKEND_HOLIDAY = "WEEKEND_HOLIDAY"
    PRE_MARKET = "PRE_MARKET"
    MARKET_OPEN = "MARKET_OPEN"
    INTRADAY = "INTRADAY"
    MARKET_CLOSE = "MARKET_CLOSE"
    POST_MARKET_AUDIT = "POST_MARKET_AUDIT"
    DAY_COMPLETE = "DAY_COMPLETE"


class MarketClock:
    """
    State machine controlling decision cycles, order gating, and mark-to-market timing.
    """

    # Major NSE Holidays for 2026 (sample official calendar)
    NSE_HOLIDAYS_2026 = {
        date(2026, 1, 26),   # Republic Day
        date(2026, 3, 6),    # Maha Shivratri
        date(2026, 3, 20),   # Id-ul-Fitr
        date(2026, 3, 25),   # Holi
        date(2026, 4, 3),    # Good Friday
        date(2026, 4, 14),   # Dr. Ambedkar Jayanti
        date(2026, 5, 1),    # Maharashtra Day
        date(2026, 5, 27),   # Bakri Id
        date(2026, 8, 15),   # Independence Day
        date(2026, 10, 2),   # Gandhi Jayanti
        date(2026, 10, 20),  # Dussehra
        date(2026, 11, 8),   # Diwali Laxmi Pujan
        date(2026, 11, 10),  # Diwali Balipratipada
        date(2026, 11, 24),  # Gurunanak Jayanti
        date(2026, 12, 25),  # Christmas
    }

    @classmethod
    def get_ist_time(cls, dt: Optional[datetime] = None) -> datetime:
        """Return timezone-aware IST datetime."""
        if dt is None:
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            # Assume local system is already in local/IST or attach UTC
            dt = dt.replace(tzinfo=IST_TZ)
        return dt.astimezone(IST_TZ)

    @classmethod
    def is_trading_day(cls, dt: Optional[datetime] = None) -> bool:
        """Check if date is a standard NSE trading day (Monday–Friday, not holiday)."""
        ist_dt = cls.get_ist_time(dt)
        if ist_dt.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        if ist_dt.date() in cls.NSE_HOLIDAYS_2026:
            return False
        return True

    @classmethod
    def get_market_phase(cls, dt: Optional[datetime] = None) -> MarketPhase:
        """
        Determine exact market phase based on IST wall clock time.
        """
        ist_dt = cls.get_ist_time(dt)
        current_time = ist_dt.time()
        is_trading = cls.is_trading_day(dt)

        if not is_trading:
            # Even on weekend, after 20:30 Sunday evening it's PRE_MARKET for Monday
            if ist_dt.weekday() == 6 and current_time >= time(20, 30):
                return MarketPhase.PRE_MARKET
            return MarketPhase.WEEKEND_HOLIDAY

        # On trading days:
        if current_time < time(9, 15):
            return MarketPhase.PRE_MARKET
        elif time(9, 15) <= current_time < time(9, 30):
            return MarketPhase.MARKET_OPEN
        elif time(9, 30) <= current_time < time(15, 30):
            return MarketPhase.INTRADAY
        elif time(15, 30) <= current_time < time(15, 45):
            return MarketPhase.MARKET_CLOSE
        elif time(15, 45) <= current_time < time(16, 30):
            return MarketPhase.POST_MARKET_AUDIT
        elif time(16, 30) <= current_time < time(20, 30):
            return MarketPhase.DAY_COMPLETE
        else:  # >= 20:30 IST
            return MarketPhase.PRE_MARKET

    @classmethod
    def can_accept_new_orders(cls, dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Gating rule: Strict 15:30 IST cutoff.
        Orders are permitted during PRE_MARKET (staged), MARKET_OPEN, and INTRADAY.
        After 15:30 IST, order entry is strictly rejected.
        """
        phase = cls.get_market_phase(dt)
        if phase in (MarketPhase.MARKET_OPEN, MarketPhase.INTRADAY):
            return True, "MARKET_ACTIVE: Order accepted for execution simulation."
        elif phase == MarketPhase.PRE_MARKET:
            return True, "PRE_MARKET_STAGED: Order staged for market open auction."
        elif phase == MarketPhase.MARKET_CLOSE:
            return False, "CUTOFF_REACHED: 15:30 IST close cutoff breached. No new orders accepted."
        elif phase == MarketPhase.POST_MARKET_AUDIT:
            return False, "AUDIT_IN_PROGRESS: Market session ended. Post-market reconciliation active."
        elif phase == MarketPhase.DAY_COMPLETE:
            return False, "SESSION_CLOSED: Daily cycle frozen. Next forecast opens at 20:30 IST."
        else:
            return False, "MARKET_CLOSED: Exchange is closed for weekend or official holiday."

    @classmethod
    def is_market_open(cls, dt: Optional[datetime] = None) -> bool:
        """True strictly between 09:15 and 15:30 on active trading days."""
        phase = cls.get_market_phase(dt)
        return phase in (MarketPhase.MARKET_OPEN, MarketPhase.INTRADAY)

    @classmethod
    def get_clock_status(cls, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """Generate structured status payload for UI and reporting."""
        ist_dt = cls.get_ist_time(dt)
        phase = cls.get_market_phase(dt)
        is_open = cls.is_market_open(dt)
        can_trade, reason = cls.can_accept_new_orders(dt)

        return {
            "current_phase": phase.value,
            "is_market_open": is_open,
            "can_accept_orders": can_trade,
            "status_reason": reason,
            "ist_timestamp": ist_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
            "ist_time": ist_dt.strftime("%H:%M IST"),
            "market_date": ist_dt.strftime("%Y-%m-%d"),
            "order_cutoff_time": "15:30 IST",
            "forecast_run_time": "20:30 IST",
            "audit_run_time": "15:45 IST",
        }

    @classmethod
    def get_status(cls, current_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Alias for get_clock_status for compatibility."""
        status = cls.get_clock_status(current_time)
        status["phase"] = status["current_phase"]
        status["phase_desc"] = status["status_reason"]
        status["is_trading_allowed"] = status["can_accept_orders"]
        return status
