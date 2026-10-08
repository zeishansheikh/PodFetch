"""
One-time OAuth 2.0 authorization helper to generate token.json with refresh token.
Run this once on your desktop machine or locally:
    python setup_oauth.py
"""

import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


def main():
    creds_file = Path("credentials.json")
    if not creds_file.exists():
        print("[ERROR] credentials.json file not found in current directory!")
        print("Please ensure credentials.json is saved in the project root.")
        return

    print("Starting one-time OAuth authentication flow...")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)

    try:
        # Tries running local server (opens browser automatically if on desktop)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    except Exception as e:
        print(f"Local server failed ({e}), falling back to console authorization...")
        creds = flow.run_console(access_type="offline")

    token_file = Path("token.json")
    token_file.write_text(creds.to_json(), encoding="utf-8")
    print("\n" + "=" * 60)
    print("SUCCESS: token.json generated successfully!")
    print("=" * 60)

    token_data = json.loads(creds.to_json())
    refresh_token = token_data.get("refresh_token")
    client_id = token_data.get("client_id")
    client_secret = token_data.get("client_secret")

    if refresh_token:
        print("\nIf deploying to a cloud server, you can also add these to your .env:\n")
        print(f'GOOGLE_CLIENT_ID="{client_id}"')
        print(f'GOOGLE_CLIENT_SECRET="{client_secret}"')
        print(f'GOOGLE_REFRESH_TOKEN="{refresh_token}"')
        print("=" * 60 + "\n")
    else:
        print("\nNote: Google did not return a new refresh token.")
        print("If needed, revoke access in your Google Account security settings and re-run.")


if __name__ == "__main__":
    main()
