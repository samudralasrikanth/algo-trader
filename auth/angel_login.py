#!/usr/bin/env python3
# =============================================================================
# auth/angel_login.py — Angel One SmartAPI Interactive Login & Test
# =============================================================================
"""
Run:  python3 auth/angel_login.py

Prompts for any missing Angel One credentials, generates an active session,
tests connection with Angel One SmartAPI, and saves credentials to .env.
"""

import os
import sys
import getpass
from pathlib import Path

try:
    from dotenv import load_dotenv, set_key
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    print("Run: pip install python-dotenv")
    sys.exit(1)

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def main():
    print("=" * 60)
    print("  Angel One SmartAPI  |  Interactive Login & Verification")
    print("=" * 60)

    api_key = os.getenv("ANGEL_API_KEY", "")
    client_code = os.getenv("ANGEL_CLIENT_CODE", "")
    pin = os.getenv("ANGEL_PIN", "")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET", "")

    if not api_key:
        api_key = input("\n  Enter Angel One SmartAPI Key: ").strip()
    else:
        print(f"\n  API Key     : {api_key}")

    if not client_code:
        client_code = input("  Enter Angel One Client Code (e.g. S123456): ").strip().upper()
    else:
        print(f"  Client Code : {client_code}")

    if not pin:
        pin = getpass.getpass("  Enter Angel One Login PIN (4-digit MPIN): ").strip()

    if not totp_secret:
        print("\n  Tip: Enable TOTP at https://smartapi.angelone.in -> 'Enable TOTP'")
        totp_secret = input("  Enter TOTP Secret Key (or press Enter to enter a 6-digit OTP directly): ").strip().replace(" ", "")

    # Generate 6-digit OTP code
    otp = ""
    if totp_secret:
        try:
            import pyotp
            otp = pyotp.TOTP(totp_secret).now()
            print(f"  ⚡  Auto-generated 2FA code from TOTP Secret: {otp}")
        except Exception as e:
            print(f"  ⚠️  Invalid TOTP Secret: {e}. Falling back to manual code entry.")
            totp_secret = ""

    if not otp:
        otp = input("  Enter 6-digit code from Google Authenticator: ").strip()
        if not otp:
            print("  ❌  2FA OTP is required.")
            sys.exit(1)

    print("\n  Connecting to Angel One SmartAPI...")

    try:
        from SmartApi import SmartConnect
    except ImportError:
        print("  ❌  smartapi-python not installed. Run: pip install smartapi-python logzero")
        sys.exit(1)

    smart_api = SmartConnect(api_key=api_key)

    try:
        res = smart_api.generateSession(client_code, pin, otp)
    except Exception as e:
        print(f"  ❌  Connection failed: {e}")
        sys.exit(1)

    if not res or not res.get("status"):
        msg = res.get("message", res) if res else "No response"
        print(f"  ❌  Login failed: {msg}")
        sys.exit(1)

    auth_data = res.get("data", {})
    refresh_token = auth_data.get("refreshToken", "")
    feed_token = smart_api.getfeedToken()

    print(f"  ✅  Login Successful! Session generated.")

    # Fetch Profile
    try:
        prof = smart_api.getProfile(refresh_token)
        if prof and prof.get("status") and prof.get("data"):
            name = prof["data"].get("name", "Angel Trader")
            email = prof["data"].get("email", "")
            print(f"  👤  Account Name : {name} ({email})")
    except Exception:
        pass

    # Fetch Margin
    try:
        rms = smart_api.rmsLimit()
        if rms and rms.get("status") and rms.get("data"):
            avail = rms["data"].get("availablecash", "0.00")
            print(f"  💰  Available Cash: ₹{avail}")
    except Exception:
        pass

    # Save to .env
    set_key(str(ENV_FILE), "BROKER", "angel")
    set_key(str(ENV_FILE), "ANGEL_API_KEY", api_key)
    set_key(str(ENV_FILE), "ANGEL_CLIENT_CODE", client_code)
    if pin:
        set_key(str(ENV_FILE), "ANGEL_PIN", pin)
    if totp_secret:
        set_key(str(ENV_FILE), "ANGEL_TOTP_SECRET", totp_secret)

    print("\n  ✅  Saved Angel One credentials to .env (BROKER=angel)")
    print("  Ready to trade with Angel One SmartAPI!\n")


if __name__ == "__main__":
    main()
