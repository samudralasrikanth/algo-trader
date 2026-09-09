# =============================================================================
# event_agent/jobs/__init__.py — V3.6.1 Overnight Jobs & Data Ingestion
# =============================================================================
"""
NEXUS V3.6.1 Production Operations, After-Market Job Scheduler, and Data Collection.
Provides truthful, persistent job execution history, readable analyzed news,
overnight international market tracking, and live Gold/Silver commodity feeds.
"""

from .job_ledger import JobLedger, JobRunRecord
from .scheduler import OvernightScheduler, ScheduleWindow
from .market_collection import MarketCloseCollector
from .international_collection import InternationalDataCollector
from .commodity_collection import CommodityDataCollector
from .news_collection import NewsIntelligenceCollector, NewsArticleRecord
from .intelligence_collection import OvernightIntelligenceEngine

__all__ = [
    "JobLedger",
    "JobRunRecord",
    "OvernightScheduler",
    "ScheduleWindow",
    "MarketCloseCollector",
    "InternationalDataCollector",
    "CommodityDataCollector",
    "NewsIntelligenceCollector",
    "NewsArticleRecord",
    "OvernightIntelligenceEngine",
]
