# =============================================================================
# event_agent/collectors/news_collector.py — Zero-API News Ingestion Engine
# =============================================================================

import re
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional

from ..config import NIFTY50_UNIVERSE, MACRO_SEARCH_TERMS


def clean_html(raw_html: str) -> str:
    """Strip HTML tags and unescape HTML entities."""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return html.unescape(cleantext).strip()


def parse_pub_date(pub_date_str: str) -> Optional[datetime]:
    """Parse standard RSS RFC-822 date formats."""
    if not pub_date_str:
        return None
    try:
        dt = parsedate_to_datetime(pub_date_str)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def fetch_google_news_rss(query: str, max_items: int = 15, cutoff_dt: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Fetch news from Google News RSS for India region with strict point-in-time cutoff filtering.
    """
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    }
    
    if cutoff_dt and cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
    
    articles = []
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            content = response.read()
            tree = ET.fromstring(content)
            
            for item in tree.findall(".//item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                pub_elem = item.find("pubDate")
                desc_elem = item.find("description")
                source_elem = item.find("source")
                
                raw_title = title_elem.text if title_elem is not None and title_elem.text else ""
                clean_title = clean_html(raw_title)
                
                # Split source from title if format is "Title - Source"
                source_name = source_elem.text if source_elem is not None and source_elem.text else "Google News"
                if " - " in clean_title:
                    parts = clean_title.rsplit(" - ", 1)
                    if len(parts[1]) < 40 and not source_name:
                        clean_title = parts[0]
                        source_name = parts[1]
                
                link = link_elem.text if link_elem is not None else ""
                pub_date_str = pub_elem.text if pub_elem is not None else ""
                pub_dt = parse_pub_date(pub_date_str)
                description = clean_html(desc_elem.text) if desc_elem is not None and desc_elem.text else ""
                
                # Strict point-in-time data cutoff check: reject future leaks
                if cutoff_dt and pub_dt and pub_dt > cutoff_dt:
                    continue
                
                if clean_title:
                    articles.append({
                        "title": clean_title,
                        "description": description,
                        "source": source_name,
                        "url": link,
                        "pub_date": pub_dt.isoformat() if pub_dt else datetime.now(timezone.utc).isoformat(),
                        "pub_timestamp": pub_dt.timestamp() if pub_dt else datetime.now(timezone.utc).timestamp(),
                        "query": query
                    })
                
                if len(articles) >= max_items:
                    break
    except Exception:
        pass
        
    return articles


def fetch_stock_news(symbol: str, max_items: int = 15, cutoff_dt: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Fetch aggregated news for a specific Nifty 50 stock across its key search terms with strict cutoff.
    """
    stock_info = NIFTY50_UNIVERSE.get(symbol)
    if not stock_info:
        clean_sym = symbol.replace(".NS", "")
        queries = [f"{clean_sym} NSE stock news"]
    else:
        queries = [
            f"{stock_info['short_name']} share price NSE",
            f"{stock_info['name']} quarterly results revenue profit",
        ]
    
    all_articles = []
    seen_titles = set()
    
    for q in queries:
        items = fetch_google_news_rss(q, max_items=max_items, cutoff_dt=cutoff_dt)
        for item in items:
            norm_title = re.sub(r'[^a-zA-Z0-9]', '', item['title'].lower())
            if norm_title and norm_title not in seen_titles:
                seen_titles.add(norm_title)
                item["symbol"] = symbol
                all_articles.append(item)
                
    # Sort descending by publication date
    all_articles.sort(key=lambda x: x.get("pub_timestamp", 0), reverse=True)
    return all_articles[:max_items]


def fetch_macro_news(max_items: int = 10, cutoff_dt: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Fetch broad Indian macroeconomic and market-wide headlines with strict cutoff.
    """
    all_macro = []
    seen = set()
    
    for q in MACRO_SEARCH_TERMS[:3]:
        items = fetch_google_news_rss(q, max_items=5, cutoff_dt=cutoff_dt)
        for item in items:
            norm_title = re.sub(r'[^a-zA-Z0-9]', '', item['title'].lower())
            if norm_title and norm_title not in seen:
                seen.add(norm_title)
                item["symbol"] = "NIFTY50_MACRO"
                all_macro.append(item)
                
    all_macro.sort(key=lambda x: x.get("pub_timestamp", 0), reverse=True)
    return all_macro[:max_items]
