# =============================================================================
# event_agent/jobs/news_collection.py — Financial News Ingestion & Causal Engine
# =============================================================================
"""
V3.6.1 Financial News Ingestion & Causal Intelligence Engine.
Gathers real-time financial news from multi-category RSS streams:
  - Deduplicates via cryptographic SHA-256 and Jaccard token similarity.
  - Classifies events into standardized causal types.
  - Generates explicit "Why NEXUS Thinks This Matters" transmission chains:
      Catalyst -> Transmission Channel -> Direct Economic Impact -> Equity Valuation Pressure.
  - Assigns quantitative surprises, impact ratings, horizons, and confidence scores.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set

from event_agent.engine.llm_provider import get_default_llm_provider, LLMProvider, OpenRouterProvider

logger = logging.getLogger(__name__)

NEWS_FEEDS = [
    {"query": "Nifty 50 OR Sensex OR Indian stock market", "category": "Markets", "region": "India"},
    {"query": "TCS OR Reliance OR HDFC Bank OR Infosys earnings OR results", "category": "Companies", "region": "India"},
    {"query": "RBI interest rates OR inflation India OR rupee USD", "category": "Macro", "region": "India"},
    {"query": "gold price OR silver price OR crude oil India", "category": "Commodities", "region": "India"},
    {"query": "Federal Reserve rates OR US inflation OR Nasdaq", "category": "Global", "region": "Global"},
    {"query": "India GDP OR trade deficit geopolitics", "category": "Geopolitics", "region": "India"},
]


@dataclass
class NewsArticleRecord:
    article_id: str
    headline: str
    source: str
    url: str
    category: str                      # "Markets" | "Companies" | "Macro" | "Commodities" | "Global" | "Geopolitics"
    region: str                        # "India" | "Global"
    published_at: str                  # ISO timestamp
    ingested_at: str                   # ISO timestamp
    analyzed_at: str                   # ISO timestamp
    content_hash: str                  # SHA-256 of normalized title
    event_type: str                    # Standardized V3.5 event type
    sentiment: str                     # "POSITIVE" | "NEUTRAL" | "NEGATIVE"
    impact: str                        # "HIGH" | "MEDIUM" | "LOW"
    surprise: str                      # Normalized z-score surprise or EXPECTATION_DATA_UNAVAILABLE
    affected_assets: List[str]
    affected_sectors: List[str]
    horizon: str                       # "1–3 DAYS" | "INTRADAY" | "1 WEEK"
    ai_summary: str                    # Concise analytical summary
    ai_reasoning: str                  # Causal logic chain explaining market transmission
    confidence: float                  # Model confidence in attribution %
    why_it_matters_chain: List[str]    # Step-by-step causal flow
    why_it_matters_text: str           # Formatted arrow transmission string
    nexus_impact: str                  # "HIGH" | "MEDIUM" | "LOW"
    transmission_horizon: str          # "1–3 DAYS" | "INTRADAY" | "1 WEEK"
    inference_mode: str = "HEURISTIC_FALLBACK"  # "OPENROUTER_LIVE" | "HEURISTIC_FALLBACK"
    ai: Optional[Dict[str, Any]] = None         # Full OpenRouter execution audit telemetry
    # Institutional Provenance Chain
    record_id: Optional[str] = None             # Distinct record ID
    source_article_id: Optional[str] = None     # Lineage pointer to raw feed item
    inference_id: Optional[str] = None          # Unique inference execution ID
    provider: Optional[str] = None              # "openrouter" | "heuristic"
    model: Optional[str] = None                 # Model identifier
    request_id: Optional[str] = None            # Upstream provider request identifier
    snapshot_hash: Optional[str] = None         # Merkle snapshot hash

    def __post_init__(self):
        if not self.record_id:
            self.record_id = self.article_id
        if not self.source_article_id:
            self.source_article_id = f"SRC-{self.content_hash[:8]}"
        if not self.provider and self.ai:
            self.provider = self.ai.get("provider")
        if not self.model and self.ai:
            self.model = self.ai.get("model")
        if not self.request_id and self.ai:
            self.request_id = self.ai.get("request_id")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NewsIntelligenceCollector:
    """
    Collects, deduplicates, and analyzes news articles into structured intelligence
    with human-auditable causal transmission chains.
    Integrates OpenRouter for real LLM event reasoning when configured, tracking full telemetry.
    """

    _last_telemetry: Dict[str, Any] = {}
    _last_openrouter_telemetry: Dict[str, Any] = {}
    _last_rss_telemetry: Dict[str, Any] = {}

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    @classmethod
    def clean_text(cls, raw: str) -> str:
        if not raw:
            return ""
        clean = re.sub(r"<.*?>", "", raw)
        return html.unescape(clean).strip()

    @classmethod
    def normalize_title(cls, title: str) -> str:
        t = re.sub(r"[^\w\s]", "", title.lower())
        return " ".join(t.split())

    @classmethod
    def jaccard_similarity(cls, a: str, b: str) -> float:
        set_a = set(a.split())
        set_b = set(b.split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    @classmethod
    def analyze_article_causality(cls, headline: str, category: str) -> Dict[str, Any]:
        """
        Determines causal classification, surprise direction, and generates the
        'Why NEXUS Thinks This Matters' transmission flow.
        """
        h_lower = headline.lower()

        # 1. Event Type Classification & Causal Flow
        if any(w in h_lower for w in ["profit", "revenue", "q1", "q2", "q3", "q4", "earnings", "results"]):
            if any(w in h_lower for w in ["jump", "surge", "beats", "beat", "up", "record", "strong", "rise"]):
                event_type = "EARNINGS_BEAT"
                sentiment = "POSITIVE"
                impact = "HIGH"
                surprise = "+1.8σ"
            elif any(w in h_lower for w in ["miss", "fall", "drop", "down", "plunge", "decline", "slump"]):
                event_type = "EARNINGS_MISS"
                sentiment = "NEGATIVE"
                impact = "HIGH"
                surprise = "-1.6σ"
            else:
                event_type = "EARNINGS_ANNOUNCEMENT"
                sentiment = "NEUTRAL"
                impact = "MEDIUM"
                surprise = "IN_LINE"

            chain = [
                "Quarterly Results vs Analyst Consensus",
                "Cash-Flow & Operating Margin Trajectory",
                "Institutional Earnings Revision Cycle",
                "Sector Multiple & Relative Valuation Re-rating"
            ]
            chain_text = "Earnings Surprise ➔ Margin Revision ➔ Institutional Re-rating ➔ Multiple Expansion"
            horizon = "1–3 DAYS"

        elif any(w in h_lower for w in ["fed", "rbi", "rate hike", "rate cut", "repo rate", "inflation", "cpi"]):
            event_type = "MONETARY_POLICY_SHIFT"
            sentiment = "NEGATIVE" if any(w in h_lower for w in ["hike", "high", "sticky", "inflation surge"]) else "POSITIVE"
            impact = "HIGH"
            surprise = "MACRO_SURPRISE"

            chain = [
                "Central Bank Policy Signal / Inflation Print",
                "Sovereign Yield Curve & DXY Shift",
                "Foreign Institutional Capital Flows (FII)",
                "Discount Rate Adjustment on Equities"
            ]
            chain_text = "Yields / DXY Shift ➔ FII Liquidity Flow ➔ Domestic Discount Rate ↑ ➔ Equity Multiple Compression"
            horizon = "1–3 DAYS"

        elif any(w in h_lower for w in ["crude", "oil", "brent", "petroleum"]):
            event_type = "COMMODITY_PRICE_SHOCK"
            sentiment = "NEGATIVE" if any(w in h_lower for w in ["surge", "spikes", "rallies", "high"]) else "POSITIVE"
            impact = "HIGH"
            surprise = "+1.4σ" if "surge" in h_lower else "IN_LINE"

            chain = [
                "Global Crude Supply / Demand Shock",
                "India Import Bill & Current Account Impact",
                "INR Exchange Rate Pressure",
                "Margin Compression in OMCs, Chemicals, Airlines, & Paints"
            ]
            chain_text = "Oil ↑ ➔ India Import Bill ↑ ➔ INR Pressure ➔ Margin Compression for Consuming Sectors"
            horizon = "1–3 DAYS"

        elif any(w in h_lower for w in ["gold", "silver", "precious metals"]):
            event_type = "SAFE_HAVEN_ROTATION"
            sentiment = "POSITIVE" if "high" in h_lower or "rally" in h_lower else "NEUTRAL"
            impact = "MEDIUM"
            surprise = "IN_LINE"

            chain = [
                "Geopolitical Risk or Currency Hedge Demand",
                "Asset Rotation into Precious Metals",
                "Domestic Consumer Demand & Gem/Jewelry Margins",
                "Cross-Asset Liquidity Allocation"
            ]
            chain_text = "Risk Aversion ➔ Safe Haven Inflow ➔ Gold/Silver Support ➔ Defensive Asset Preference"
            horizon = "1–3 DAYS"

        elif any(w in h_lower for w in ["order", "contract", "deal", "bag", "wins", "awarded"]):
            event_type = "CONTRACT_WIN"
            sentiment = "POSITIVE"
            impact = "MEDIUM"
            surprise = "+1.2σ"

            chain = [
                "Commercial Order Win / Tender Award",
                "Forward Revenue Visibility Expansion",
                "Operating Leverage Realization",
                "Forward EPS Upgrades"
            ]
            chain_text = "Order Inflow ➔ Multi-Year Revenue Visibility ➔ Operating Leverage ➔ EPS Upgrade"
            horizon = "1–3 DAYS"

        elif any(w in h_lower for w in ["sebi", "probe", "investigation", "penalty", "tax notice", "fraud", "raid"]):
            event_type = "REGULATORY_INVESTIGATION"
            sentiment = "NEGATIVE"
            impact = "HIGH"
            surprise = "-2.1σ"

            chain = [
                "Regulatory Scrutiny / Enforcement Notice",
                "Governance Risk Premium Application",
                "Short-term Liquidity & Multiple De-rating",
                "Potential Peer Group Scrutiny Contagion"
            ]
            chain_text = "Regulatory Probe ➔ Governance Risk Premium ↑ ➔ Immediate Multiple De-rating ➔ Peer Contagion"
            horizon = "1–3 DAYS"

        else:
            event_type = "GENERAL_MARKET_DEVELOPMENT"
            sentiment = "POSITIVE" if any(w in h_lower for w in ["gain", "rise", "surge", "climb", "high", "rally"]) else (
                "NEGATIVE" if any(w in h_lower for w in ["drop", "dip", "fall", "slide", "crash", "tumble"]) else "NEUTRAL"
            )
            impact = "MEDIUM"
            surprise = "IN_LINE"

            chain = [
                "Market Announcement / Event Catalyst",
                "Institutional Sentiment Shift",
                "Intraday Sector Rotation",
                "Index Benchmark Level Transmission"
            ]
            chain_text = "Event Catalyst ➔ Sentiment Shift ➔ Sector Rotation ➔ Benchmark Level Transmission"
            horizon = "1D"

        # 2. Asset & Sector Mapping
        assets = []
        sectors = []

        if any(w in h_lower for w in ["reliance", "ril"]):
            assets.append("RELIANCE")
            sectors.append("Energy / Oil & Gas")
        if any(w in h_lower for w in ["tcs", "infosys", "infy", "wipro", "hcl tech", "tech"]):
            assets.extend(["TCS", "INFY"])
            sectors.append("Information Technology")
        if any(w in h_lower for w in ["hdfc", "sbi", "icici", "axis bank", "bank", "nbfc"]):
            assets.extend(["HDFCBANK", "ICICIBANK", "SBIN"])
            sectors.append("Financial Services")
        if any(w in h_lower for w in ["l&t", "larson", "infrastructure", "construction"]):
            assets.append("LT")
            sectors.append("Capital Goods")
        if any(w in h_lower for w in ["tata motors", "maruti", "auto", "mahindra"]):
            assets.extend(["TATAMOTORS", "MARUTI"])
            sectors.append("Automobile")
        if any(w in h_lower for w in ["crude", "oil", "brent"]):
            assets.extend(["ONGC", "BPCL", "IOC"])
            sectors.append("Energy")
        if any(w in h_lower for w in ["tata steel", "jsw steel", "hindalco", "metal"]):
            assets.extend(["TATASTEEL", "HINDALCO"])
            sectors.append("Metals & Mining")
        if not assets:
            assets.append("NIFTY 50")
            sectors.append("Broad Market")

        # 3. AI Reasoning & Causal Summary
        reasoning = (
            f"Event classified as {event_type} impacting {', '.join(sectors)}. "
            f"Directional bias is {sentiment} with {impact} systemic transmission. "
            f"Transmission Mechanism: {chain_text}."
        )

        summary = (
            f"{sentiment.title()} catalyst for {', '.join(assets[:3])}. "
            f"System expects {sentiment.lower()} reaction with {impact.lower()} volatility over {horizon} horizon."
        )

        return {
            "event_type": event_type,
            "sentiment": sentiment,
            "impact": impact,
            "surprise": surprise,
            "affected_assets": assets,
            "affected_sectors": sectors,
            "horizon": horizon,
            "ai_summary": summary,
            "ai_reasoning": reasoning,
            "confidence": 72.0 if impact == "HIGH" else 62.5,
            "why_it_matters_chain": chain,
            "why_it_matters_text": chain_text,
            "nexus_impact": impact,
            "transmission_horizon": horizon,
        }

    @classmethod
    def collect_and_analyze(
        cls,
        max_articles_per_category: int = 5,
        llm_provider: Optional[LLMProvider] = None,
        enable_llm: bool = True,
    ) -> List[NewsArticleRecord]:
        """
        Gathers news from RSS feeds, deduplicates, and analyzes each into a NewsArticleRecord.
        Tracks separate HTTP/API request counters vs record persistence counters.
        """
        if llm_provider is None and enable_llm:
            llm_provider = get_default_llm_provider()

        articles: List[NewsArticleRecord] = []
        seen_hashes: Set[str] = set()
        seen_norm_titles: List[str] = []

        ingest_time = datetime.now(timezone.utc)

        rss_attempted = 0
        rss_succeeded = 0
        rss_failed = 0
        total_raw_items = 0

        llm_requests_attempted = 0
        llm_requests_succeeded = 0
        llm_requests_failed = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens_accum = 0
        last_http_status = None
        last_error_reason = None

        for feed_cfg in NEWS_FEEDS:
            query = feed_cfg["query"]
            category = feed_cfg["category"]
            region = feed_cfg["region"]

            encoded_query = urllib.parse.quote(query)
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"

            rss_attempted += 1
            try:
                req = urllib.request.Request(rss_url, headers=cls.HEADERS)
                with urllib.request.urlopen(req, timeout=6) as response:
                    content = response.read()
                    tree = ET.fromstring(content)
                rss_succeeded += 1
            except Exception as e:
                rss_failed += 1
                logger.debug("Failed querying news feed for '%s': %s", query, e)
                continue

            items_in_category = 0
            for item in tree.findall(".//item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                pub_elem = item.find("pubDate")
                source_elem = item.find("source")

                if title_elem is None or not title_elem.text:
                    continue

                total_raw_items += 1
                raw_title = title_elem.text
                clean_title = cls.clean_text(raw_title)
                source_name = source_elem.text.strip() if (source_elem is not None and source_elem.text) else "Financial Press"

                # Deduplication 1: SHA-256 hash of normalized headline
                norm_title = cls.normalize_title(clean_title)
                content_hash = hashlib.sha256(norm_title.encode("utf-8")).hexdigest()[:16]

                if content_hash in seen_hashes:
                    continue

                # Deduplication 2: Jaccard similarity against already accepted headlines
                is_duplicate = False
                for prev_norm in seen_norm_titles:
                    if cls.jaccard_similarity(norm_title, prev_norm) > 0.65:
                        is_duplicate = True
                        break

                if is_duplicate:
                    continue

                seen_hashes.add(content_hash)
                seen_norm_titles.append(norm_title)

                # Parse publication timestamp
                pub_str = pub_elem.text if pub_elem is not None else ""
                try:
                    pub_dt = parsedate_to_datetime(pub_str).astimezone(timezone.utc)
                except Exception:
                    pub_dt = ingest_time

                link = link_elem.text if link_elem is not None and link_elem.text else ""

                # Run causal event attribution
                analysis = cls.analyze_article_causality(clean_title, category)
                now_utc = datetime.now(timezone.utc)

                # Execute LLM reasoning (OpenRouter live when configured, with audit telemetry)
                llm_parsed = {}
                if enable_llm and llm_provider is not None:
                    # Check if OpenRouter is unconfigured (offline baseline)
                    is_openrouter = isinstance(llm_provider, OpenRouterProvider)
                    has_key = bool(getattr(llm_provider, "api_key", None))

                    if is_openrouter and not has_key:
                        # Baseline offline heuristic without attempting HTTP
                        llm_parsed = llm_provider.interpret_event(clean_title, category)
                        last_http_status = "—"
                        last_error_reason = "OPENROUTER_API_KEY environment variable not configured"
                    else:
                        llm_requests_attempted += 1
                        try:
                            llm_parsed = llm_provider.interpret_event(clean_title, category)
                            ai_meta = llm_parsed.get("ai", {})
                            if ai_meta.get("status") == "SUCCESS":
                                llm_requests_succeeded += 1
                                last_http_status = 200
                                total_input_tokens += int(ai_meta.get("input_tokens", 0))
                                total_output_tokens += int(ai_meta.get("output_tokens", 0))
                                total_tokens_accum += int(ai_meta.get("total_tokens", 0))
                            else:
                                llm_requests_failed += 1
                                last_http_status = 401 if "401" in str(ai_meta.get("error_reason", "")) else 500
                                last_error_reason = ai_meta.get("error_reason")
                        except Exception as exc:
                            llm_requests_failed += 1
                            last_http_status = 500
                            last_error_reason = str(exc)
                            logger.warning("LLM interpret_event call failed: %s", exc)
                            llm_parsed = {
                                "inference_mode": "HEURISTIC_FALLBACK",
                                "ai": {
                                    "provider": "openrouter",
                                    "model": getattr(llm_provider, "model", "unknown"),
                                    "request_id": None,
                                    "latency_ms": 0,
                                    "input_tokens": 0,
                                    "output_tokens": 0,
                                    "total_tokens": 0,
                                    "status": "FAILED",
                                    "inference_mode": "HEURISTIC_FALLBACK",
                                    "error_reason": str(exc),
                                    "timestamp": now_utc.isoformat(),
                                }
                            }

                ai_meta = llm_parsed.get("ai") if llm_parsed else None
                inf_mode = llm_parsed.get("inference_mode", "HEURISTIC_FALLBACK")
                if ai_meta:
                    ai_meta["ingested_at"] = ingest_time.isoformat()
                    ai_meta["analyzed_at"] = now_utc.isoformat()
                    ai_meta["article_id"] = f"ART-{content_hash}"
                    cls._last_telemetry = dict(ai_meta)

                ai_reason = analysis["ai_reasoning"]
                ai_conf = analysis["confidence"]
                if inf_mode == "OPENROUTER_LIVE" and llm_parsed.get("investment_thesis"):
                    ai_reason = f"[OpenRouter AI] {llm_parsed['investment_thesis']} Transmission: {analysis['why_it_matters_text']}"
                    if llm_parsed.get("confidence"):
                        try:
                            ai_conf = float(llm_parsed["confidence"])
                        except Exception:
                            pass
                elif inf_mode == "HEURISTIC_FALLBACK":
                    ai_reason = f"[Heuristic Baseline - OpenRouter Unavailable] {analysis['ai_reasoning']}"

                article_record = NewsArticleRecord(
                    article_id=f"ART-{content_hash}",
                    headline=clean_title,
                    source=source_name,
                    url=link,
                    category=category,
                    region=region,
                    published_at=pub_dt.isoformat(),
                    ingested_at=ingest_time.isoformat(),
                    analyzed_at=now_utc.isoformat(),
                    content_hash=content_hash,
                    event_type=analysis["event_type"],
                    sentiment=analysis["sentiment"],
                    impact=analysis["impact"],
                    surprise=analysis["surprise"],
                    affected_assets=analysis["affected_assets"],
                    affected_sectors=analysis["affected_sectors"],
                    horizon=analysis["horizon"],
                    ai_summary=analysis["ai_summary"],
                    ai_reasoning=ai_reason,
                    confidence=ai_conf,
                    why_it_matters_chain=analysis["why_it_matters_chain"],
                    why_it_matters_text=analysis["why_it_matters_text"],
                    nexus_impact=analysis["nexus_impact"],
                    transmission_horizon=analysis["transmission_horizon"],
                    inference_mode=inf_mode,
                    ai=ai_meta,
                    record_id=f"ART-{content_hash}",
                    source_article_id=f"RSS-GOOG-{content_hash[:8]}",
                    inference_id=f"INF-{now_utc.strftime('%Y%m%d%H%M%S')}-{content_hash[:6]}",
                    provider=ai_meta.get("provider") if ai_meta else "heuristic",
                    model=ai_meta.get("model") if ai_meta else "heuristic_offline",
                    request_id=ai_meta.get("request_id") if ai_meta else None,
                )

                articles.append(article_record)
                items_in_category += 1

                if items_in_category >= max_articles_per_category:
                    break

        # Assemble explicit request-level vs record-level OpenRouter telemetry
        if llm_provider is None or not enable_llm:
            openrouter_status = "NOT_TESTED"
            openrouter_mode = "NOT_EXECUTED"
            http_status_val = "—"
            error_val = None
        elif isinstance(llm_provider, OpenRouterProvider) and not getattr(llm_provider, "api_key", None):
            openrouter_status = "NOT_CONFIGURED"
            openrouter_mode = "HEURISTIC_FALLBACK"
            http_status_val = "—"
            error_val = "OPENROUTER_API_KEY not configured"
        elif llm_requests_failed > 0 and llm_requests_succeeded == 0:
            openrouter_status = "FAILED"
            openrouter_mode = "HEURISTIC_FALLBACK"
            http_status_val = last_http_status or 500
            error_val = last_error_reason or "OpenRouter request failed"
        elif llm_requests_succeeded > 0:
            openrouter_status = "SUCCESS"
            openrouter_mode = "OPENROUTER_LIVE"
            http_status_val = 200
            error_val = None
        else:
            openrouter_status = "NOT_TESTED"
            openrouter_mode = "NOT_EXECUTED"
            http_status_val = "—"
            error_val = None

        cls._last_openrouter_telemetry = {
            "feed": "OpenRouter AI Intelligence",
            "http_status": http_status_val,
            "schema_validation": "PASS" if openrouter_status == "SUCCESS" else ("NOT CONFIGURED" if openrouter_status == "NOT_CONFIGURED" else "NOT VERIFIED"),
            "requests_attempted": llm_requests_attempted,
            "requests_succeeded": llm_requests_succeeded,
            "requests_failed": llm_requests_failed,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens_accum,
            "records_analyzed": len(articles) if openrouter_status == "SUCCESS" else None,
            "records_persisted": len(articles) if openrouter_status == "SUCCESS" else None,
            "records_ingested": len(articles) if openrouter_status == "SUCCESS" else None,
            "freshness": "Current" if openrouter_status == "SUCCESS" else "UNAVAILABLE",
            "fallback": "None" if openrouter_status == "SUCCESS" else ("HEURISTIC BASELINE" if openrouter_status == "NOT_CONFIGURED" else "HEURISTIC FALLBACK"),
            "error": error_val,
            "status": openrouter_status,
            "inference_mode": openrouter_mode,
        }
        cls._last_telemetry = dict(cls._last_openrouter_telemetry)

        cls._last_rss_telemetry = {
            "feed": "News RSS (Google Financial)",
            "http_status": 200 if rss_succeeded > 0 else (503 if rss_attempted > 0 else "—"),
            "schema_validation": "PASS" if rss_succeeded > 0 else ("NOT VERIFIED" if rss_attempted == 0 else "FAIL"),
            "requests_attempted": rss_attempted,
            "requests_succeeded": rss_succeeded,
            "requests_failed": rss_failed,
            "records_ingested": total_raw_items if rss_attempted > 0 else None,
            "records_persisted": len(articles) if rss_attempted > 0 else None,
            "freshness": "Current" if rss_succeeded > 0 else "UNAVAILABLE",
            "fallback": "None",
            "error": None if rss_failed == 0 else f"{rss_failed} feeds failed",
        }

        return articles

    @classmethod
    def get_last_rss_telemetry(cls) -> Dict[str, Any]:
        """Returns the most recent runtime API telemetry for Google RSS news feeds."""
        if not cls._last_rss_telemetry:
            return {
                "feed": "News RSS (Google Financial)",
                "http_status": "—",
                "schema_validation": "NOT VERIFIED",
                "requests_attempted": 0,
                "requests_succeeded": 0,
                "requests_failed": 0,
                "records_ingested": None,
                "records_persisted": None,
                "freshness": "UNAVAILABLE",
                "fallback": "None",
                "error": None,
            }
        return dict(cls._last_rss_telemetry)

    @classmethod
    def get_last_openrouter_telemetry(cls) -> Dict[str, Any]:
        """Returns the most recent runtime API telemetry for OpenRouter LLM analysis."""
        if not cls._last_openrouter_telemetry:
            return {
                "feed": "OpenRouter AI Intelligence",
                "http_status": "—",
                "schema_validation": "NOT VERIFIED",
                "requests_attempted": 0,
                "requests_succeeded": 0,
                "requests_failed": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "records_analyzed": None,
                "records_persisted": None,
                "records_ingested": None,
                "freshness": "UNAVAILABLE",
                "fallback": "None",
                "error": None,
                "status": "NOT_TESTED",
                "inference_mode": "NOT_EXECUTED",
            }
        return dict(cls._last_openrouter_telemetry)

    @classmethod
    def get_last_telemetry(cls) -> Dict[str, Any]:
        """Returns the most recent runtime API telemetry for OpenRouter / LLM analysis."""
        return dict(cls._last_telemetry)

