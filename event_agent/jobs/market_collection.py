# =============================================================================
# event_agent/jobs/market_collection.py — Indian Market Close Collector
# =============================================================================
"""
V3.6.1 Indian Market Close Data Collector.
Captures official market close benchmarks after 15:30 IST:
  - NIFTY 50 (^NSEI)
  - Bank Nifty (^NSEBANK)
  - India VIX (^INDIAVIX)

Extracts prices, point-in-time market timestamps, and computes freshness.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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

        try:
            req = urllib.request.Request(url, headers=cls.HEADERS)
            with urllib.request.urlopen(req, timeout=8) as resp:
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

            # Classify quality
            if freshness <= 300:
                quality = "LIVE"
            elif freshness <= 86400:
                quality = "EOD"
            else:
                quality = "STALE"

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
                    "raw_meta": {"error": "Feed unavailable or timed out"},
                }
                failed += 1

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
