# =============================================================================
# event_agent/storage/__init__.py
# =============================================================================

from .ledger import (
    init_db,
    save_prediction,
    save_news_article,
    get_latest_predictions,
    get_historical_predictions,
    reconcile_predictions,
    get_performance_scorecard,
    get_all_news
)
