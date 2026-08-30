# =============================================================================
# auth/token_manager.py — Daily Access Token Generator
# =============================================================================
"""
Run this ONCE each trading morning before starting main.py:

    python3 auth/token_manager.py

It will:
    1. Open the Kite login URL in your browser
    2. Ask you to paste the redirect URL
    3. Exchange the request_token for an access_token
    4. Save it to .env (auto-loaded by settings.py)

Requirements:
    pip install python-dotenv
"""

import os
import sys
import webbrowser
from pathlib import Path

# ── try to load dotenv ───────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv, set_key
    load_dotenv()
except ImportError:
    print("Install python-dotenv first:  pip install python-dotenv")
    sys.exit(1)

from kiteconnect import KiteConnect

ENV_FILE = Path(__file__).parent.parent / ".env"

# ── read credentials from .env ───────────────────────────────────────────────
API_KEY    = os.getenv("KITE_API_KEY", "")
API_SECRET = os.getenv("KITE_API_SECRET", "")

if not API_KEY or not API_SECRET:
    print("""
[!] Missing credentials in .env

Create a file called .env in the algo-trader/ root:

    KITE_API_KEY=your_api_key_here
    KITE_API_SECRET=your_api_secret_here

Get these from: https://developers.kite.trade/apps
""")
    sys.exit(1)


def get_access_token() -> str:
    kite = KiteConnect(api_key=API_KEY)

    # Step 1: Open login URL
    login_url = kite.login_url()
    print(f"\n[1] Opening Kite login in your browser...")
    print(f"    URL: {login_url}\n")
    webbrowser.open(login_url)

    # Step 2: User pastes redirect URL
    print("[2] After logging in, Zerodha redirects you to a URL like:")
    print("    https://your-redirect/?request_token=XXXXXX&action=login&status=success\n")
    redirect_url = input("    Paste the full redirect URL here: ").strip()

    # Extract request_token from URL
    if "request_token=" not in redirect_url:
        print("[!] Could not find request_token in that URL. Try again.")
        sys.exit(1)

    request_token = redirect_url.split("request_token=")[1].split("&")[0]
    print(f"\n[3] Got request_token: {request_token[:8]}...")

    # Step 3: Generate session
    try:
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]
    except Exception as e:
        print(f"[!] Failed to generate session: {e}")
        sys.exit(1)

    # Step 4: Save to .env
    set_key(str(ENV_FILE), "KITE_ACCESS_TOKEN", access_token)
    print(f"\n[✓] Access token saved to .env")
    print(f"    Token: {access_token[:12]}...{access_token[-4:]}")
    print(f"\n[✓] You can now run:  python3 main.py\n")

    return access_token


if __name__ == "__main__":
    get_access_token()
