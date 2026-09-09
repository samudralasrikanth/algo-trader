# =============================================================================
# event_agent/adapters/news_adapter.py — News Data Adapter
# =============================================================================
"""
Wraps the existing news_collector.py with the standard adapter interface.
The LLM is used ONLY here — for interpreting text from news articles.
All numerical calculations in other modules are deterministic.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from .base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class NewsAdapter(BaseAdapter):
    """
    News data adapter wrapping existing Google News RSS collector.

    LLM boundary: This adapter may use LLM for text interpretation
    (sentiment, event classification). No other adapter uses LLM.
    All downstream numerical calculations are deterministic.
    """

    def __init__(self):
        # Import existing collector
        try:
            from ..collectors.news_collector import (
                fetch_google_news_rss,
            )
            self._fetch_fn = fetch_google_news_rss
            self._available = True
        except ImportError:
            logger.warning("news_collector not available.")
            self._fetch_fn = None
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def fetch_series(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Not applicable for news — use fetch_news_for_symbol instead."""
        return pd.DataFrame()

    def get_latest(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Not applicable for news — use fetch_news_for_symbol instead."""
        return None

    def get_as_of(
        self,
        series_id: str,
        as_of_datetime: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Not applicable for news."""
        return None

    def fetch_news_for_symbol(
        self,
        search_terms: List[str],
        max_articles: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent news articles for given search terms.
        Returns list of article dicts with title, source, url, pub_date.
        """
        if not self._available or not self._fetch_fn:
            return []

        all_articles = []
        for term in search_terms:
            try:
                articles = self._fetch_fn(term, max_results=max_articles)
                if articles:
                    all_articles.extend(articles)
            except Exception as exc:
                logger.error("News fetch for '%s' failed: %s", term, exc)

        # Deduplicate by URL
        seen_urls = set()
        unique = []
        for article in all_articles:
            url = article.get("url", article.get("link", ""))
            if url and url not in seen_urls:
                seen_urls.add(url)
                article["fetched_at"] = datetime.now(timezone.utc).isoformat()
                unique.append(article)

        return unique[:max_articles]

    def fetch_macro_news(self, max_articles: int = 10) -> List[Dict[str, Any]]:
        """Fetch macro/market-level news."""
        macro_terms = [
            "Nifty 50 market today",
            "RBI monetary policy",
            "India inflation CPI",
            "FII DII equity flow India",
            "US Federal Reserve rate decision",
        ]
        return self.fetch_news_for_symbol(macro_terms, max_articles=max_articles)
