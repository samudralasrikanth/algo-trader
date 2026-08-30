# =============================================================================
# main.py — Entry Point
# =============================================================================
"""
Usage:
    python main.py                  # tick-level runner (WebSocket)
    python main.py --poll           # fallback: 60s polling runner
    streamlit run dashboard.py      # live dashboard
"""

import sys
from config.settings import SYMBOLS

if __name__ == "__main__":
    poll_mode = "--poll" in sys.argv

    if poll_mode:
        from scheduler.runner import run
        print("Starting polling runner (60s interval)...")
    else:
        from scheduler.tick_runner import run
        print("Starting tick-level WebSocket runner...")

    run(SYMBOLS)
