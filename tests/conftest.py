# =============================================================================
# tests/conftest.py — Shared Test Configuration
# =============================================================================
"""
Ensures .env credentials are loaded into os.environ for ALL test modules.
This is the single authoritative credential propagation point for pytest.

SECURITY: .env is in .gitignore. Secrets never enter source control.
"""

from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(_env_path, override=False)
except ImportError:
    pass
