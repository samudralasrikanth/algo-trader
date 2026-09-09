# =============================================================================
# event_agent/jobs/market_collection.py — Indian Market Close Collector
# =============================================================================
"""
V3.6.1 Indian Market Close Data Collector.
Captures official market close benchmarks after 15:30 IST:
  - NIFTY 50 (^NSEI)
  - Bank Nifty (^NSEBANK)
  - India VIX (^INDIAVIX)

Extracts prices, point-in-time market timestamps, and computes truthful freshness.
Includes exchange operating hour state calculation (NSE open 09:15-15:30 IST).
"""

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INDIAN_BENCHMARKS = [
    {"symbol": "^NSEI", "asset": "NIFTY 50", "category": "INDEX"},
    {"symbol": "^NSEBANK", "asset": "NIFTY BANK", "category": "INDEX"},
    {"symbol": "^INDIAVIX", "asset": "INDIA VIX", "category": "VOLATILITY"},
]


@dataclass
class MarketAssetQuote:
    symbol: str
    asset: str
    price: float
    change: float
    change_pct: float
    market_timestamp: str
    ingestion_timestamp: str
    source: str
    freshness_seconds: int
    quality: str                      # "LIVE" | "DELAYED" | "EOD" | "STALE" | "INVALID"
    market_state: str                 # "OPEN" | "PRE_MARKET" | "CLOSED" | "EOD"
    market_state_desc: str
    raw_meta: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MarketCloseCollector:
    """
    Collects Indian indices closing prices via Yahoo Finance v8 chart query.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    @classmethod
    def fetch_quote(cls, symbol: str, asset: str) -> Optional[MarketAssetQuote]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        ingest_time = datetime.now(timezone.utc)
        ist_tz = timezone(timedelta(hours=5, minutes=30))

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

            # Real exchange session state for NSE
            now_ist = ingest_time.astimezone(ist_tz)
            weekday = now_ist.weekday()  # 0=Monday, 4=Friday, 5=Sat, 6=Sun
            time_val = now_ist.time()

            if weekday < 5 and time(9, 15) <= time_val <= time(15, 30):
                market_state = "OPEN"
                market_state_desc = "NSE Live Trading Session"
                quality = "LIVE" if freshness <= 300 else "DELAYED"
            elif weekday < 5 and time(9, 0) <= time_val < time(9, 15):
                market_state = "PRE_MARKET"
                market_state_desc = "NSE Pre-Open Auction Window"
                quality = "DELAYED"
            else:
                market_state = "CLOSED"
                updated_ist = mkt_dt.astimezone(ist_tz).strftime("%H:%M IST")
                market_state_desc = f"Market closed • Last updated {updated_ist}"
                quality = "EOD" if freshness <= 86400 * 3 else "STALE"

            return MarketAssetQuote(
                symbol=symbol,
                asset=asset,
                price=round(float(price), 2),
                change=chg,
                change_pct=chg_pct,
                market_timestamp=mkt_dt.isoformat(),
                ingestion_timestamp=ingest_time.isoformat(),
                source="Yahoo Finance / NSE Feed",
                freshness_seconds=freshness,
                quality=quality,
                market_state=market_state,
                market_state_desc=market_state_desc,
                raw_meta={
                    "currency": meta.get("currency", "INR"),
                    "exchange": meta.get("exchangeName", "NSE"),
                },
            )
        except Exception as e:
            logger.warning("Failed fetching market close for %s: %s", symbol, e)
            return None

    @classmethod
    def collect_all_benchmarks(cls) -> Dict[str, Any]:
        results = {}
        succeeded = 0
        failed = 0

        for item in INDIAN_BENCHMARKS:
            quote = cls.fetch_quote(item["symbol"], item["asset"])
            if quote:
                results[item["asset"]] = quote.to_dict()
                succeeded += 1
            else:
                results[item["asset"]] = {
                    "symbol": item["symbol"],
                    "asset": item["asset"],
                    "price": None,
                    "change": None,
                    "change_pct": None,
                    "market_timestamp": None,
                    "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "Yahoo Finance / NSE Feed",
                    "freshness_seconds": 999999,
                    "quality": "DATA_UNAVAILABLE",
                    "market_state": "UNKNOWN",
                    "market_state_desc": "Feed offline or unavailable",
                    "raw_meta": {"error": "Feed unavailable or timed out"},
                }
                failed += 1

        # Universal aliases for Bank Nifty
        if "NIFTY BANK" in results and "BANK NIFTY" not in results:
            results["BANK NIFTY"] = results["NIFTY BANK"]
        elif "BANK NIFTY" in results and "NIFTY BANK" not in results:
            results["NIFTY BANK"] = results["BANK NIFTY"]

        return {
            "succeeded": succeeded,
            "failed": failed,
            "total": len(INDIAN_BENCHMARKS),
            "quotes": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
