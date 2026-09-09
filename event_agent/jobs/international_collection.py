# =============================================================================
# event_agent/jobs/international_collection.py — Global Markets Collector
# =============================================================================
"""
V3.6.1 International Market Data Collector.
Gathers global index, yields, dollar index, and forex rates after Indian market close:
  - US: S&P 500, NASDAQ, Dow Jones, Russell 2000, VIX, US 10Y, DXY
  - Europe: FTSE 100, DAX, CAC 40
  - Asia: Nikkei 225, Hang Seng, Shanghai Composite, KOSPI, ASX 200
  - FX: USD/INR, EUR/USD, USD/JPY

Integrates exchange operating hours calculation:
  Accurately identifies OPEN, PRE_MARKET, CLOSED, EOD, and DELAYED states.
  Never labels closed markets as LIVE.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INTERNATIONAL_TICKERS = [
    # US Equities & Volatility
    {"symbol": "^GSPC", "asset": "S&P 500", "region": "US", "type": "EQUITY_INDEX"},
    {"symbol": "^IXIC", "asset": "NASDAQ Composite", "region": "US", "type": "EQUITY_INDEX"},
    {"symbol": "^DJI", "asset": "Dow Jones Industrial", "region": "US", "type": "EQUITY_INDEX"},
    {"symbol": "^RUT", "asset": "Russell 2000", "region": "US", "type": "EQUITY_INDEX"},
    {"symbol": "^VIX", "asset": "CBOE VIX", "region": "US", "type": "VOLATILITY"},
    {"symbol": "^TNX", "asset": "US 10-Year Treasury Yield", "region": "US", "type": "RATES"},
    {"symbol": "DX-Y.NYB", "asset": "US Dollar Index (DXY)", "region": "US", "type": "CURRENCY_INDEX"},

    # Europe Equities
    {"symbol": "^FTSE", "asset": "FTSE 100", "region": "EUROPE", "type": "EQUITY_INDEX"},
    {"symbol": "^GDAXI", "asset": "DAX 40", "region": "EUROPE", "type": "EQUITY_INDEX"},
    {"symbol": "^FCHI", "asset": "CAC 40", "region": "EUROPE", "type": "EQUITY_INDEX"},

    # Asia-Pacific Equities
    {"symbol": "^N225", "asset": "Nikkei 225", "region": "ASIA", "type": "EQUITY_INDEX"},
    {"symbol": "^HSI", "asset": "Hang Seng", "region": "ASIA", "type": "EQUITY_INDEX"},
    {"symbol": "000001.SS", "asset": "Shanghai Composite", "region": "ASIA", "type": "EQUITY_INDEX"},
    {"symbol": "^KS11", "asset": "KOSPI", "region": "ASIA", "type": "EQUITY_INDEX"},
    {"symbol": "^AXJO", "asset": "ASX 200", "region": "ASIA", "type": "EQUITY_INDEX"},

    # Foreign Exchange
    {"symbol": "INR=X", "asset": "USD/INR", "region": "FX", "type": "CURRENCY_PAIR"},
    {"symbol": "EURUSD=X", "asset": "EUR/USD", "region": "FX", "type": "CURRENCY_PAIR"},
    {"symbol": "JPY=X", "asset": "USD/JPY", "region": "FX", "type": "CURRENCY_PAIR"},
]


@dataclass
class GlobalMarketQuote:
    symbol: str
    asset: str
    region: str
    type: str
    price: float
    change: float
    change_pct: float
    market_timestamp: str
    ingestion_timestamp: str
    source: str
    freshness_seconds: int
    quality: str                      # "OPEN" | "DELAYED" | "EOD" | "CLOSED" | "STALE" | "DATA_UNAVAILABLE"
    market_state: str                 # "OPEN" | "PRE_MARKET" | "CLOSED" | "EOD"
    market_state_desc: str
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class InternationalDataCollector:
    """
    Fetches global equity, forex, and bond benchmarks with truthful market-state awareness.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    @classmethod
    def calculate_market_state(
        cls, region: str, symbol: str, ingest_time: datetime, mkt_dt: datetime
    ) -> tuple[str, str, str]:
        """
        Computes accurate (market_state, market_state_desc, quality).
        Enforces that closed markets are tagged CLOSED / EOD, never falsely marked LIVE.
        """
        weekday = ingest_time.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        hour = ingest_time.hour
        minute = ingest_time.minute
        time_utc = time(hour, minute)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        mkt_ist = mkt_dt.astimezone(ist_tz).strftime("%H:%M IST")

        # 1. Foreign Exchange (24/5 continuous trading)
        if region == "FX":
            if weekday == 5 or (weekday == 4 and hour >= 21) or (weekday == 6 and hour < 21):
                return "CLOSED", f"Forex weekend close • Last updated {mkt_ist}", "CLOSED"
            else:
                return "OPEN", "Forex 24/5 spot continuous session", "LIVE"

        # 2. US Equities & Volatility (NYSE/NASDAQ 13:30 to 20:00 UTC)
        if region == "US":
            if weekday < 5:
                if time(13, 30) <= time_utc <= time(20, 0):
                    return "OPEN", "US Regular Trading Session (15m delayed)", "DELAYED"
                elif time(8, 0) <= time_utc < time(13, 30):
                    return "PRE_MARKET", "US Pre-Market Trading Window", "DELAYED"
                else:
                    return "CLOSED", f"Market closed • Last updated {mkt_ist}", "EOD"
            else:
                return "CLOSED", f"Weekend closed • Last updated {mkt_ist}", "EOD"

        # 3. European Equities (08:00 to 16:30 UTC)
        if region == "EUROPE":
            if weekday < 5 and time(8, 0) <= time_utc <= time(16, 30):
                return "OPEN", "European Regular Session (15m delayed)", "DELAYED"
            else:
                return "CLOSED", f"Market closed • Last updated {mkt_ist}", "EOD"

        # 4. Asian Equities
        if region == "ASIA":
            if weekday < 5:
                if symbol == "^N225" and time(0, 0) <= time_utc <= time(6, 0):
                    return "OPEN", "Tokyo Stock Exchange Active Session", "DELAYED"
                elif symbol in ["^HSI", "000001.SS"] and time(1, 30) <= time_utc <= time(8, 0):
                    return "OPEN", "Hong Kong / Shanghai Active Session", "DELAYED"
                elif symbol in ["^KS11", "^AXJO"] and time(0, 0) <= time_utc <= time(6, 30):
                    return "OPEN", "Seoul / Sydney Active Session", "DELAYED"
                else:
                    return "CLOSED", f"Market closed • Last updated {mkt_ist}", "EOD"
            else:
                return "CLOSED", f"Weekend closed • Last updated {mkt_ist}", "EOD"

        return "CLOSED", f"Market closed • Last updated {mkt_ist}", "EOD"

    @classmethod
    def fetch_single_quote(cls, item: Dict[str, str]) -> Optional[GlobalMarketQuote]:
        symbol = item["symbol"]
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        ingest_time = datetime.now(timezone.utc)

        try:
            req = urllib.request.Request(url, headers=cls.HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            res = data.get("chart", {}).get("result", [])
            if not res:
                return None

            meta = res[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose") or price

            if price is None:
                return None

            chg = round(price - prev, 2)
            chg_pct = round((chg / prev) * 100.0, 2) if prev else 0.0

            mkt_time_epoch = meta.get("regularMarketTime")
            if mkt_time_epoch:
                mkt_dt = datetime.fromtimestamp(mkt_time_epoch, tz=timezone.utc)
            else:
                mkt_dt = ingest_time

            freshness = int(max(0, (ingest_time - mkt_dt).total_seconds()))

            # Compute accurate exchange status
            mkt_state, mkt_desc, quality = cls.calculate_market_state(
                item["region"], symbol, ingest_time, mkt_dt
            )

            # If stale > 3 days, override quality
            if freshness > 86400 * 4:
                quality = "STALE"

            return GlobalMarketQuote(
                symbol=symbol,
                asset=item["asset"],
                region=item["region"],
                type=item["type"],
                price=round(float(price), 3),
                change=chg,
                change_pct=chg_pct,
                market_timestamp=mkt_dt.isoformat(),
                ingestion_timestamp=ingest_time.isoformat(),
                source="Yahoo Finance / Global Feeds",
                freshness_seconds=freshness,
                quality=quality,
                market_state=mkt_state,
                market_state_desc=mkt_desc,
                currency=meta.get("currency", "USD"),
            )
        except Exception as e:
            logger.debug("Could not fetch %s: %s", symbol, e)
            return None

    @classmethod
    def collect_all(cls) -> Dict[str, Any]:
        """
        Queries all 24 international tickers and compiles unified global market telemetry.
        """
        quotes = {}
        succeeded = 0
        failed = 0

        for item in INTERNATIONAL_TICKERS:
            q = cls.fetch_single_quote(item)
            if q:
                quotes[item["asset"]] = q.to_dict()
                succeeded += 1
            else:
                quotes[item["asset"]] = {
                    "symbol": item["symbol"],
                    "asset": item["asset"],
                    "region": item["region"],
                    "type": item["type"],
                    "price": None,
                    "change": None,
                    "change_pct": None,
                    "market_timestamp": None,
                    "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "Yahoo Finance / Global Feeds",
                    "freshness_seconds": 999999,
                    "quality": "DATA_UNAVAILABLE",
                    "market_state": "UNKNOWN",
                    "market_state_desc": "Feed offline or timed out",
                    "currency": "USD",
                }
                failed += 1

        # Universal aliases
        if "US 10-Year Treasury Yield" in quotes and "US 10Y Yield" not in quotes:
            quotes["US 10Y Yield"] = quotes["US 10-Year Treasury Yield"]
        elif "US 10Y Yield" in quotes and "US 10-Year Treasury Yield" not in quotes:
            quotes["US 10-Year Treasury Yield"] = quotes["US 10Y Yield"]

        return {
            "succeeded": succeeded,
            "failed": failed,
            "total": len(INTERNATIONAL_TICKERS),
            "quotes": quotes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
