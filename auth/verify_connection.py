# =============================================================================
# auth/verify_connection.py — Kite Connect Connection Verifier
# =============================================================================
"""
Run: python3 auth/verify_connection.py

Tests:
    1. Credentials loaded from .env
    2. Profile API call (confirms access token is valid)
    3. LTP fetch for each configured symbol
    4. Margins fetch (confirms trading account accessible)
"""

import sys
import os
from pathlib import Path

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

API_KEY      = os.getenv("KITE_API_KEY", "")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "")

print("=" * 55)
print("  algo-trader  |  Connection Verification")
print("=" * 55)

# ── Step 1: Credentials present? ─────────────────────────────
broker_name = os.getenv('BROKER', 'kite').lower().strip()

print("\n[1] Checking credentials...")
if broker_name == "kite":
    if not API_KEY:
        print("    ❌  KITE_API_KEY is missing in .env")
        sys.exit(1)
    if not ACCESS_TOKEN:
        print("    ❌  KITE_ACCESS_TOKEN is missing in .env")
        print("       Run: python3 auth/token_manager.py")
        sys.exit(1)
    print(f"    ✅  API Key     : {API_KEY[:6]}...{API_KEY[-4:]}")
    print(f"    ✅  Access Token: {ACCESS_TOKEN[:6]}...{ACCESS_TOKEN[-4:]}")
elif broker_name == "shoonya":
    if not os.getenv("SHOONYA_USER_ID"):
        print("    ❌  SHOONYA_USER_ID missing in .env")
        sys.exit(1)
    print(f"    ✅  Shoonya Auth: Present")
elif broker_name == "yfinance":
    print(f"    ✅  YFinance: No credentials required")


# ── Step 2: Connect via broker adapter ───────────────────────
print(f"\n[2] Connecting to {broker_name.upper()}...")
try:
    from data.provider import get_broker
    broker = get_broker()
    profile = broker.get_profile()
    print(f"    ✅  Name    : {profile.get('user_name')}")
    print(f"    ✅  User ID : {profile.get('user_id')}")
    print(f"    ✅  Email   : {profile.get('email')}")
    print(f"    ✅  Broker  : {profile.get('broker', broker_name)}")
except Exception as e:
    print(f"    ❌  Connection failed: {e}")
    if 'kite' in str(e).lower() or 'access' in str(e).lower():
        print("       Run: python3 auth/token_manager.py")
    elif 'shoonya' in broker_name.lower():
        print("       Run: python3 auth/shoonya_login.py")
    sys.exit(1)

# ── Step 3: LTP for each symbol ──────────────────────────────
from config.settings import SYMBOLS, EXCHANGE

print(f"\n[3] Fetching LTP for configured symbols: {SYMBOLS}")
ltp_ok = True
for sym in SYMBOLS:
    try:
        ltp = broker.get_ltp(sym)
        print(f"    ✅  {sym:<12} LTP = ₹{ltp:,.2f}")
    except Exception as e:
        print(f"    ❌  {sym:<12} Error: {e}")
        ltp_ok = False

# ── Step 4: Margins ───────────────────────────────────────────
print("\n[4] Fetching account margins...")
try:
    margins = broker.get_margins()
    print(f"    ✅  Net margin       : ₹{margins.get('net', 0):,.2f}")
    print(f"    ✅  Available balance: ₹{margins.get('available', 0):,.2f}")
except Exception as e:
    print(f"    ⚠️   Margins fetch failed: {e}  (non-critical)")

# ── Summary ───────────────────────────────────────────────────
print("\n" + "=" * 55)
if ltp_ok:
    print("  ✅  ALL CHECKS PASSED — ready to run main.py")
else:
    print("  ⚠️   PARTIAL — some symbols failed LTP fetch")
print("=" * 55 + "\n")
