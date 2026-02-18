"""
Google Ads OAuth — Refresh Token Generator
Run this once to get your refresh token, then save it in .env

Usage:
    pip install google-auth-oauthlib
    python get_refresh_token.py
"""

from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv
import os, json

load_dotenv()
CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in builder/.env first.")

SCOPES = ["https://www.googleapis.com/auth/adwords"]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

def main():
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    credentials = flow.run_local_server(
        port=8080,
        prompt="consent",
        access_type="offline",
    )

    print("\n" + "="*55)
    print("SUCCESS — copy your refresh token below")
    print("="*55)
    print(f"\nREFRESH_TOKEN={credentials.refresh_token}\n")
    print("Add these 3 lines to builder/.env:")
    print(f"  GOOGLE_CLIENT_ID={CLIENT_ID}")
    print(f"  GOOGLE_CLIENT_SECRET={CLIENT_SECRET}")
    print(f"  GOOGLE_REFRESH_TOKEN={credentials.refresh_token}")
    print("="*55 + "\n")

if __name__ == "__main__":
    main()
