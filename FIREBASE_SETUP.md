Firebase setup for ColdReach

1) Create a Firebase project
- Go to https://console.firebase.google.com/ and create or select a project.

2) Enable Realtime Database
- In the console, open "Realtime Database" and create a database (choose a location and start in locked mode or test mode as you prefer).
- Note the Database URL (e.g. https://coldreach-54f8d-default-rtdb.firebaseio.com).

3) Create a service account key (recommended)
- Project Settings → Service accounts → Generate new private key. This downloads a JSON file.
- Keep this file private. Do NOT commit it to Git.

4) Local development: use `.streamlit/secrets.toml`
- Put the JSON file at `.streamlit/serviceAccountKey.json` and update `.streamlit/secrets.toml` like this:

```toml
[firebase]
database_url = "https://<YOUR_DATABASE>.firebaseio.com"
service_account_path = "./.streamlit/serviceAccountKey.json"
```

Or set environment variables:

```bash
export FIREBASE_DATABASE_URL="https://<YOUR_DATABASE>.firebaseio.com"
export FIREBASE_SERVICE_ACCOUNT_PATH="/path/to/serviceAccountKey.json"
```

5) Streamlit Community Cloud (recommended approach)
- In the Streamlit app dashboard, go to "Settings → Secrets".
- Add a secret named `firebase` with the following fields:
  - `database_url`: the Realtime DB URL
  - `service_account_json`: the full JSON contents of the service account file (paste it as a value)

Example `secrets.toml` structure used by the app:

```toml
[firebase]
service_account_json = "{ ... entire JSON here ... }"
```

The app writes this secret into `.streamlit/serviceAccountKey.json` at startup and sets an environment variable so the manager can read it.

6) Verify the connection locally with the provided script:

```bash
python tools/check_firebase.py
```

This will try to read `FIREBASE_SERVICE_ACCOUNT_PATH` or `.streamlit/serviceAccountKey.json` and connect to the Database URL defined in `.streamlit/secrets.toml` or `FIREBASE_DATABASE_URL` env var.

7) Security notes
- Never commit service account JSON to Git. If you accidentally commit it, revoke the key in the Firebase Console and rotate credentials.
- Streamlit Secrets are private to your app and not exposed in the repo.

If you want, I can write the `service_account_json` into a file at runtime on Streamlit Cloud (the app already supports this). If you'd like, supply the Realtime Database URL and I can run the test connection for you now.