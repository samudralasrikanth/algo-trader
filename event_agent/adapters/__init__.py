# =============================================================================
# event_agent/adapters — Data Adapter Layer
# =============================================================================
"""
Data adapters normalize external data sources into a standard interface.
Each adapter implements BaseAdapter and provides point-in-time aware data access.

Central Invariant:
    Every prediction must be reproducible from exactly the information
    that existed at the moment the prediction was locked.
"""
