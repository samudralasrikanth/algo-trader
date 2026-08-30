# =============================================================================
# auth/shoonya_login.py — Finvasia / Shoonya Login (OTP-first flow)
# =============================================================================
"""
Run:  python3 auth/shoonya_login.py

Supports login with:
    1. OTP only      (new account / no password set yet)
    2. Password + OTP
    3. Password + DOB (DDMMYYYY)
"""

import sys
import hashlib
import getpass
import os
from pathlib import Path

try:
    from dotenv import load_dotenv, set_key
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    print("Run: pip install python-dotenv")
    sys.exit(1)

ENV_FILE = Path(__file__).parent.parent / ".env"

user_id     = os.getenv("SHOONYA_USER_ID", "")
vendor_code = os.getenv("SHOONYA_VENDOR_CODE", "")
api_secret  = os.getenv("SHOONYA_API_SECRET", "")
imei        = os.getenv("SHOONYA_IMEI", "algo-trader-1.0")


def _try_login(api, pwd_hash: str, twofa: str) -> dict:
    api_hash = hashlib.sha256(api_secret.encode()).hexdigest()
    return api.login(
        userid=user_id,
        password=pwd_hash,
        twoFA=twofa,
        vendor_code=vendor_code,
        api_secret=api_hash,
        imei=imei,
    )


def main():
    print("=" * 55)
    print("  Shoonya Login  |  OTP Flow")
    print("=" * 55)
    print(f"\n  User ID     : {user_id}")
    print(f"  Vendor Code : {vendor_code}")
    print(f"  IMEI        : {imei}\n")

    if not all([user_id, vendor_code, api_secret]):
        print("  ❌  SHOONYA_USER_ID / VENDOR_CODE / API_SECRET missing in .env")
        sys.exit(1)

    # Build API client
    try:
        from NorenRestApiPy.NorenApi import NorenApi
    except ImportError:
        print("  ❌  Run: pip install NorenRestApiPy websocket-client")
        sys.exit(1)

    class _Api(NorenApi):
        def __init__(self):
            super().__init__(
                host="https://api.shoonya.com/NorenWClientTP/",
                websocket="wss://api.shoonya.com/NorenWSTP/",
            )

    api = _Api()

    # --- Get OTP first ---
    print("  ⚡  Open your Shoonya app — an OTP will be sent to your")
    print("      registered mobile number.\n")
    otp = getpass.getpass("  Enter OTP from phone : ").strip()
    if not otp:
        print("  ❌  OTP required.")
        sys.exit(1)

    # --- Password (optional for new accounts) ---
    print()
    pwd_raw = getpass.getpass("  Password (press Enter to skip if not set yet) : ").strip()

    # Try strategies in order
    strategies = []

    if pwd_raw:
        # Strategy 1: hashed password + OTP
        strategies.append((hashlib.sha256(pwd_raw.encode()).hexdigest(), otp, "password+OTP"))
        # Strategy 2: plain password + OTP (some implementations)
        strategies.append((pwd_raw, otp, "plain-password+OTP"))

    # Strategy 3: empty password hash + OTP (new account / OTP-only)
    strategies.append((hashlib.sha256(b"").hexdigest(), otp, "empty-password+OTP"))
    # Strategy 4: user_id as password (some broker defaults)
    strategies.append((hashlib.sha256(user_id.encode()).hexdigest(), otp, "userid-as-password+OTP"))

    print("\n  Attempting login...")
    resp = None
    for pwd_hash, twofa, label in strategies:
        print(f"    Trying [{label}]...", end=" ", flush=True)
        try:
            resp = _try_login(api, pwd_hash, twofa)
            if resp and resp.get("stat") == "Ok":
                print("✅")
                break
            else:
                print(f"❌  {resp.get('emsg', resp) if resp else 'No response'}")
                resp = None
        except Exception as e:
            print(f"❌  {e}")
            resp = None

    if not resp:
        print("""
  ❌  All login attempts failed.

  Next steps:
    1. Set your password in the Shoonya mobile app:
       App → Profile → Change Password
    2. Or contact Finvasia support: support@finvasia.com
    3. Try again after setting password
""")
        sys.exit(1)

    print(f"\n  ✅  Logged in! Welcome {resp.get('uname', user_id)}")

    # Save what we know to .env
    set_key(str(ENV_FILE), "BROKER",           "shoonya")
    set_key(str(ENV_FILE), "SHOONYA_USER_ID",  user_id)
    set_key(str(ENV_FILE), "SHOONYA_IMEI",     imei)
    if pwd_raw:
        set_key(str(ENV_FILE), "SHOONYA_PASSWORD", pwd_raw)

    print("  ✅  Saved to .env\n")
    print("  Run: python3 auth/verify_connection.py")
    print("  Run: python3 main.py\n")


if __name__ == "__main__":
    main()
