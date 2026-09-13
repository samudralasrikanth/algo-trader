#!/usr/bin/env python3
# =============================================================================
# services/video-report/youtube_auth.py — Interactive YouTube OAuth2 Helper
# =============================================================================
"""
One-time interactive OAuth2 helper to authorize YouTube channel uploads.
Features:
1. Auto-loads .env and checks for existing client credentials.
2. Accepts Google client_secret_*.json downloaded from Google Cloud Console.
3. Interactively prompts for Client ID & Client Secret if not found in .env.
4. Spins up a local loopback server on http://localhost:8080 or allows manual code paste.
5. Automatically saves YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN to .env.
"""

import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
TOKEN_PATH = Path(__file__).resolve().parents[2] / "token.json"

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
LOCAL_REDIRECT_URI = "http://localhost:8080/"
OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def load_env_file():
    """Load key-values from .env if present."""
    if not ENV_PATH.exists():
        return
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def update_env_variable(key: str, value: str):
    """Safely updates or appends a key in .env."""
    if not ENV_PATH.exists():
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
        return

    content = ENV_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()
    updated = False
    new_lines = []

    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip() == key:
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def load_credentials_from_json(json_path: Path):
    """Extract client_id and client_secret from Google JSON credentials file."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        creds = data.get("installed") or data.get("web") or data
        client_id = creds.get("client_id")
        client_secret = creds.get("client_secret")
        return client_id, client_secret
    except Exception as e:
        print(f"[!] Error parsing JSON file {json_path}: {e}")
        return None, None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="font-family:sans-serif; text-align:center; padding:50px; background:#0B132B; color:#FFFFFF;">
                <h1 style="color:#4ADE80;">&#10004; Authorization Successful</h1>
                <p>NEXUS has received your YouTube authorization token. You may close this window and return to your terminal.</p>
            </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization failed or code missing.")

    def log_message(self, format, *args):
        # Suppress standard HTTP request logging
        pass


def get_auth_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": YOUTUBE_UPLOAD_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description="NEXUS YouTube One-Time OAuth Setup")
    parser.add_argument("--client-id", help="Google Cloud OAuth Client ID")
    parser.add_argument("--client-secret", help="Google Cloud OAuth Client Secret")
    parser.add_argument("--credentials-file", help="Path to Google client_secret_*.json")
    args = parser.parse_args()

    client_id = args.client_id or os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = args.client_secret or os.environ.get("YOUTUBE_CLIENT_SECRET")

    # Check for credentials file
    if args.credentials_file:
        c_id, c_secret = load_credentials_from_json(Path(args.credentials_file))
        if c_id and c_secret:
            client_id, client_secret = c_id, c_secret

    # If still not found, search current directory for any client_secret*.json
    if not client_id or not client_secret:
        found_json = list(Path(".").glob("client_secret*.json"))
        if found_json:
            print(f"[*] Found credentials file: {found_json[0].name}")
            c_id, c_secret = load_credentials_from_json(found_json[0])
            if c_id and c_secret:
                client_id, client_secret = c_id, c_secret

    # Interactive prompt if still missing
    print("\n" + "=" * 70)
    print("      ⚡ NEXUS YOUTUBE OAUTH SETUP (ONE-TIME AUTHORIZATION) ⚡")
    print("=" * 70)

    if not client_id or not client_secret:
        print("\nTo upload reports to YouTube, Google requires an OAuth 2.0 Client ID.")
        print("Steps in Google Cloud Console (https://console.cloud.google.com):")
        print("  1. Enable 'YouTube Data API v3'.")
        print("  2. Create Credentials -> OAuth client ID (Application type: Desktop App).")
        print("  3. Copy your Client ID and Client Secret, or provide the JSON file path.\n")

        inp = input("Enter Client ID (or path to client_secret_*.json): ").strip().strip("'\"")
        if inp.endswith(".json") and Path(inp).exists():
            client_id, client_secret = load_credentials_from_json(Path(inp))
        else:
            client_id = inp
            client_secret = input("Enter Client Secret: ").strip().strip("'\"")

    if not client_id or not client_secret:
        print("\n[!] Client ID and Client Secret are required. Aborting setup.")
        return

    # Persist client credentials to .env
    update_env_variable("YOUTUBE_CLIENT_ID", client_id)
    update_env_variable("YOUTUBE_CLIENT_SECRET", client_secret)
    print("\n[✓] Client ID & Secret configured and saved to .env")

    # Start local loopback server to receive callback
    server = None
    redirect_uri = LOCAL_REDIRECT_URI
    try:
        server = HTTPServer(("localhost", 8080), OAuthCallbackHandler)
        server_thread = threading.Thread(target=server.handle_request)
        server_thread.daemon = True
        server_thread.start()
        print("[*] Local authorization listener started on http://localhost:8080/")
    except Exception as e:
        # Fallback to manual verification code
        server = None
        redirect_uri = OOB_REDIRECT_URI

    auth_url = get_auth_url(client_id, redirect_uri)

    print("\n" + "-" * 70)
    print("AUTHORIZATION STEP:")
    print("Open the following URL in your browser to sign in with your YouTube channel:\n")
    print(auth_url)
    print("-" * 70 + "\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    auth_code = None
    if server:
        print("[*] Waiting for browser authorization (or you can paste the code below)...")
        # Give up to 120 seconds for browser callback, or prompt
        server_thread.join(timeout=30)
        auth_code = OAuthCallbackHandler.auth_code

    if not auth_code:
        auth_code = input("\nEnter verification code (or full redirect URL): ").strip()
        if "code=" in auth_code:
            parsed = urllib.parse.urlparse(auth_code)
            params = urllib.parse.parse_qs(parsed.query)
            auth_code = params.get("code", [auth_code])[0]

    if not auth_code:
        print("[!] No authorization code received. Aborting.")
        return

    try:
        print("[*] Exchanging authorization code for persistent refresh token...")
        token_data = exchange_code(client_id, client_secret, auth_code, redirect_uri)

        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)
        print(f"[✓] Token credentials written to {TOKEN_PATH.name}")

        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            update_env_variable("YOUTUBE_REFRESH_TOKEN", refresh_token)
            print("[✓] YOUTUBE_REFRESH_TOKEN saved to .env!")
            print("\n🎉 SETUP COMPLETE! Future 18:30 IST daily runs will publish automatically.")
        else:
            print("[!] Warning: Google did not return a refresh token.")
            print("    If you already authorized this app, go to https://myaccount.google.com/permissions,")
            print("    revoke access, and rerun this script to get a fresh refresh token.")

    except Exception as e:
        print(f"[!] Token exchange error: {e}")


if __name__ == "__main__":
    main()
