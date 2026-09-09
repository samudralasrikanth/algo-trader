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
    global user_id, vendor_code, api_secret, imei

    print("=" * 55)
    print("  Shoonya (Finvasia) Login  |  API Setup & OTP Flow")
    print("=" * 55)

    if not user_id:
        user_id = input("\n  Enter Shoonya User ID (Client Code, e.g. FA12345): ").strip()
    else:
        print(f"\n  User ID     : {user_id}")

    if not vendor_code:
        default_vc = f"{user_id}_U" if user_id else "algo_U"
        entered_vc = input(f"  Enter Vendor Code (Press Enter for '{default_vc}'): ").strip()
        vendor_code = entered_vc or default_vc
    else:
        print(f"  Vendor Code : {vendor_code}")

    if not api_secret:
        print("  (Get API Secret from: https://prism.finvasia.com -> API section)")
        api_secret = getpass.getpass("  Enter API Secret / API Key: ").strip()

    if not imei:
        imei = "algo-trader-1.0"
    print(f"  IMEI        : {imei}\n")

    if not all([user_id, vendor_code, api_secret]):
        print("  ❌  User ID, Vendor Code, and API Secret are required to proceed.")
        print("      Please check https://prism.finvasia.com for your API credentials.")
        sys.exit(1)

    # Save configuration to .env immediately
    set_key(str(ENV_FILE), "SHOONYA_USER_ID",     user_id)
    set_key(str(ENV_FILE), "SHOONYA_VENDOR_CODE", vendor_code)
    set_key(str(ENV_FILE), "SHOONYA_API_SECRET",  api_secret)
    set_key(str(ENV_FILE), "SHOONYA_IMEI",        imei)

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

    # --- Password ---
    pwd_raw = os.getenv("SHOONYA_PASSWORD", "")
    if not pwd_raw:
        pwd_raw = getpass.getpass("  Enter Shoonya Login Password: ").strip()

    # --- 2FA: TOTP Secret or 6-digit OTP ---
    totp_secret = os.getenv("SHOONYA_TOTP_SECRET", "")
    if not totp_secret:
        totp_secret = input("  Enter TOTP Secret Key (from Authenticator setup, or press Enter to skip): ").strip().replace(" ", "")

    if totp_secret:
        try:
            import pyotp
            otp = pyotp.TOTP(totp_secret).now()
            print(f"  ⚡  Auto-generated 2FA code from TOTP Secret: {otp}\n")
            set_key(str(ENV_FILE), "SHOONYA_TOTP_SECRET", totp_secret)
        except Exception as e:
            print(f"  ⚠️  Invalid TOTP Secret ({e}). Falling back to manual OTP.")
            totp_secret = ""

    if not totp_secret:
        print("  ⚡  Open your Shoonya Authenticator app (or check phone SMS for OTP)")
        otp = input("  Enter 6-digit OTP / TOTP code: ").strip()
        if not otp:
            print("  ❌  OTP required.")
            sys.exit(1)

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
