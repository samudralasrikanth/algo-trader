# =============================================================================
# event_agent/collectors/__init__.py
# =============================================================================

from .news_collector import fetch_stock_news, fetch_macro_news
from .event_calendar import get_stock_events, get_macro_events, scan_all_upcoming_events
