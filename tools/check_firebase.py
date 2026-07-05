"""Check Firebase Realtime Database connectivity using a service account.

Usage:
    python tools/check_firebase.py

It will look for FIREBASE_SERVICE_ACCOUNT_PATH env var or .streamlit/serviceAccountKey.json
and FIREBASE_DATABASE_URL env var (or .streamlit/secrets.toml entry).
"""
import json
import os
import sys
from pathlib import Path

import requests
from google.oauth2 import service_account
import google.auth.transport.requests


def find_service_account_path():
    env = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    if env and Path(env).exists():
        return env
    local = Path.cwd() / ".streamlit" / "serviceAccountKey.json"
    if local.exists():
        return str(local)
    return None


def find_database_url():
    env = os.getenv("FIREBASE_DATABASE_URL")
    if env:
        return env
    # try reading .streamlit/secrets.toml if present
    toml_path = Path.cwd() / ".streamlit" / "secrets.toml"
    if toml_path.exists():
        try:
            import toml

            data = toml.load(toml_path)
            firebase = data.get("firebase", {})
            url = firebase.get("database_url") or firebase.get("databaseUrl")
            if url:
                return url
        except Exception:
            pass
    return None


def main():
    sa_path = find_service_account_path()
    db_url = find_database_url()

    if not db_url:
        print("ERROR: Could not find FIREBASE_DATABASE_URL. Set env var or .streamlit/secrets.toml")
        sys.exit(2)

    if not sa_path:
        print("ERROR: Could not find service account JSON (set FIREBASE_SERVICE_ACCOUNT_PATH or place .streamlit/serviceAccountKey.json)")
        sys.exit(2)

    print(f"Using service account: {sa_path}")
    print(f"Connecting to database: {db_url}")

    try:
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=["https://www.googleapis.com/auth/firebase.database", "https://www.googleapis.com/auth/userinfo.email"])
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        token = creds.token
        if not token:
            print("ERROR: Failed to obtain access token")
            sys.exit(2)

        # fetch top-level leads node
        url = db_url.rstrip("/") + "/leads.json"
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        print("SUCCESS: Connected to Realtime Database. Response status:", r.status_code)
        print("Sample payload keys:", list(r.json().keys()) if isinstance(r.json(), dict) else type(r.json()))
    except Exception as e:
        print("ERROR connecting to Firebase:", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
