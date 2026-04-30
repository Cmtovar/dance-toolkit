"""One-time setup: authenticate with YouTube API and save refresh token.

Prerequisites:
1. Create a Google Cloud project at https://console.cloud.google.com
2. Enable "YouTube Data API v3"
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download the credentials JSON and save as client_secret.json in this directory

Then run:
    pip install google-api-python-client google-auth-oauthlib
    python setup_youtube_oauth.py

This opens a browser for consent. After authorizing, a token.json file is saved
that the server uses for all subsequent uploads.
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    if not os.path.isfile(CLIENT_SECRET):
        print(f"Missing {CLIENT_SECRET}")
        print("Download OAuth credentials from Google Cloud Console and save as client_secret.json")
        return

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install dependencies first:")
        print("  pip install google-api-python-client google-auth-oauthlib")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"Token saved to {TOKEN_PATH}")
    print("YouTube uploads are now enabled. Restart the server.")


if __name__ == "__main__":
    main()
