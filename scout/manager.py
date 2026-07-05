import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

import google.auth
import google.auth.transport.requests as google_requests
import requests

DEFAULT_SETTINGS = {
    "business_name": "ColdReach",
    "contact_person": "",
    "contact_email": "",
    "contact_phone": "",
    "signature": "",
    "default_stage": "New",
    "ai_provider": "disabled",
    "anthropic_api_key": "",
    "gmail_credentials_path": "",
}


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or os.path.join(os.getcwd(), "data", "leads.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _get_firebase_config() -> Dict[str, str]:
    try:
        import streamlit as st
    except Exception:  # pragma: no cover - streamlit may be unavailable in tests.
        st = None

    config: Dict[str, str] = {}
    if st is not None:
        try:
            secrets = st.secrets.get("firebase", {}) if hasattr(st, "secrets") else {}
            if isinstance(secrets, dict):
                config.update(
                    {
                        "database_url": str(secrets.get("database_url", "")),
                        "database_secret": str(secrets.get("database_secret", "")),
                        "service_account_path": str(secrets.get("service_account_path", "")),
                    }
                )
        except Exception:
            pass

    database_url = os.getenv("FIREBASE_DATABASE_URL", config.get("database_url", ""))
    database_secret = os.getenv("FIREBASE_DATABASE_SECRET", config.get("database_secret", ""))
    service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", config.get("service_account_path", ""))
    return {
        "database_url": database_url,
        "database_secret": database_secret,
        "service_account_path": service_account_path,
    }


def _firebase_enabled() -> bool:
    config = _get_firebase_config()
    return bool(config.get("database_url"))


def is_firebase_enabled() -> bool:
    return _firebase_enabled()


def _firebase_url(endpoint: str) -> str:
    config = _get_firebase_config()
    base_url = config["database_url"].rstrip("/")
    endpoint = endpoint.lstrip("/")
    if base_url.endswith(".json"):
        return f"{base_url}/{endpoint}" if endpoint else base_url
    return f"{base_url}/{endpoint}.json" if endpoint else f"{base_url}.json"


def _firebase_request(method: str, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    config = _get_firebase_config()
    if not config.get("database_url"):
        return None

    headers = {}
    if config.get("database_secret"):
        params = {"auth": config["database_secret"]}
    else:
        params = None
        if config.get("service_account_path"):
            service_account_path = os.path.expanduser(config["service_account_path"])
            if os.path.exists(service_account_path):
                credentials, _ = google.auth.load_credentials_from_file(service_account_path)
                auth_req = google_requests.Request()
                credentials.before_request(auth_req, "GET", "https://www.googleapis.com/auth/firebase.database")
                headers["Authorization"] = f"Bearer {credentials.token}"

    if headers:
        response = requests.request(method, _firebase_url(endpoint), params=params, headers=headers, json=payload, timeout=10)
    else:
        response = requests.request(method, _firebase_url(endpoint), params=params, json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def _normalize_lead_payload(lead_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if lead_data is None:
        lead_data = {}

    normalized: Dict[str, Any] = {}
    for key in ["company_name", "email", "website", "phone", "address", "niche", "stage", "score", "notes", "metadata", "last_contact", "next_follow_up"]:
        if key in lead_data:
            value = lead_data.get(key)
            if key == "metadata" and isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = {}
            normalized[key] = value

    if "company_name" not in normalized and lead_data.get("name"):
        normalized["company_name"] = lead_data.get("name")
    if "stage" not in normalized:
        normalized["stage"] = None
    if "notes" not in normalized:
        normalized["notes"] = ""
    if "metadata" not in normalized:
        normalized["metadata"] = {}
    return normalized


def _normalize_firebase_lead(lead_id: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    normalized = dict(payload)
    normalized["id"] = str(lead_id)
    if "company_name" not in normalized and "name" in normalized:
        normalized["company_name"] = normalized["name"]
    return normalized


def get_lead(db_path: Optional[str] = None, lead_id: Optional[str] = None) -> Dict[str, Any]:
    """Return a single lead with activities (local or Firebase).

    lead_id: for local DB it's integer-like; for Firebase it's the string key.
    """
    if _firebase_enabled():
        payload = _firebase_request("GET", f"leads/{lead_id}") or {}
        return _normalize_firebase_lead(str(lead_id), payload)

    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if not row:
            return {}
        lead = dict(row)
        activities_raw = lead.get("activities") or "[]"
        try:
            lead["activities"] = json.loads(activities_raw) if isinstance(activities_raw, str) else activities_raw
        except Exception:
            lead["activities"] = []
        return lead
    finally:
        conn.close()


def add_activity(db_path: Optional[str] = None, lead_id: Optional[str] = None, actor: str = "", action: str = "", notes: str = "") -> Dict[str, Any]:
    """Log an activity for a lead. Returns the created activity object."""
    now = datetime.utcnow().isoformat()
    activity = {"id": uuid.uuid4().hex, "actor": actor or "", "action": action or "", "notes": notes or "", "timestamp": now}

    if _firebase_enabled():
        # Post under leads/{lead_id}/activities
        response = _firebase_request("POST", f"leads/{lead_id}/activities", activity)
        activity_id = response.get("name") if isinstance(response, dict) else None
        if activity_id:
            activity["id"] = str(activity_id)
        # also update lead.updated_at
        _firebase_request("PATCH", f"leads/{lead_id}", {"updated_at": now})
        return activity

    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT activities FROM leads WHERE id = ?", (lead_id,)).fetchone()
        current = []
        if row:
            raw = row[0] or "[]"
            try:
                current = json.loads(raw)
            except Exception:
                current = []

        current.append(activity)
        conn.execute("UPDATE leads SET activities = ?, updated_at = ? WHERE id = ?", (json.dumps(current, ensure_ascii=False), now, lead_id))
        conn.commit()
        return activity
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                email TEXT,
                website TEXT,
                phone TEXT,
                address TEXT,
                niche TEXT,
                stage TEXT,
                score INTEGER,
                notes TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "leads", "last_contact", "last_contact TEXT")
        _ensure_column(conn, "leads", "next_follow_up", "next_follow_up TEXT")
        _ensure_column(conn, "leads", "activities", "activities TEXT")
        conn.commit()
    finally:
        conn.close()

    for key, default_value in DEFAULT_SETTINGS.items():
        save_settings(db_path, {key: default_value}, create_missing=True)


def _get_setting_row(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def get_settings(db_path: Optional[str] = None) -> Dict[str, Any]:
    if _firebase_enabled():
        payload = _firebase_request("GET", "settings") or {}
        if isinstance(payload, dict):
            merged = dict(DEFAULT_SETTINGS)
            for key, value in payload.items():
                merged[key] = value
            return merged
        return dict(DEFAULT_SETTINGS)

    conn = _connect(db_path)
    try:
        settings = dict(DEFAULT_SETTINGS)
        for key in DEFAULT_SETTINGS:
            value = _get_setting_row(conn, key)
            if value is not None:
                settings[key] = value
        return settings
    finally:
        conn.close()


def save_settings(db_path: Optional[str] = None, updates: Dict[str, Any] = None, create_missing: bool = False) -> Dict[str, Any]:
    if updates is None:
        updates = {}

    if _firebase_enabled():
        payload = {key: (value if isinstance(value, str) else json.dumps(value) if isinstance(value, (dict, list)) else str(value)) for key, value in updates.items()}
        _firebase_request("PATCH", "settings", payload)
        return get_settings(db_path)

    conn = _connect(db_path)
    try:
        for key, value in updates.items():
            if not isinstance(value, str):
                value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        conn.commit()
        return get_settings(db_path)
    finally:
        conn.close()


def upsert_lead(db_path: Optional[str] = None, lead_data: Dict[str, Any] = None) -> Dict[str, Any]:
    if lead_data is None:
        lead_data = {}

    if _firebase_enabled():
        normalized = _normalize_lead_payload(lead_data)
        normalized.setdefault("stage", lead_data.get("stage") or DEFAULT_SETTINGS.get("default_stage", "New"))
        normalized.setdefault("created_at", datetime.utcnow().isoformat())
        normalized.setdefault("updated_at", datetime.utcnow().isoformat())
        normalized.setdefault("notes", "")
        if lead_data.get("id"):
            response = _firebase_request("PATCH", f"leads/{lead_data['id']}", normalized)
            return _normalize_firebase_lead(str(lead_data["id"]), response)

        response = _firebase_request("POST", "leads", normalized)
        lead_id = response.get("name") if isinstance(response, dict) else None
        if not lead_id:
            return normalized
        return _normalize_firebase_lead(str(lead_id), normalized)

    conn = _connect(db_path)
    try:
        now = datetime.utcnow().isoformat()
        company_name = lead_data.get("company_name") or ""
        website = lead_data.get("website") or None
        email = lead_data.get("email") or None
        phone = lead_data.get("phone") or None
        address = lead_data.get("address") or None
        niche = lead_data.get("niche") or None
        stage = lead_data.get("stage") or get_settings(db_path).get("default_stage", "New")
        score = lead_data.get("score")
        notes = lead_data.get("notes") or ""
        metadata = json.dumps(lead_data.get("metadata") or {}, ensure_ascii=False)

        existing = conn.execute(
            "SELECT id FROM leads WHERE company_name = ? AND COALESCE(website, '') = COALESCE(?, '')",
            (company_name, website),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE leads
                SET email = COALESCE(?, email), website = COALESCE(?, website), phone = COALESCE(?, phone),
                    address = COALESCE(?, address), niche = COALESCE(?, niche), stage = COALESCE(?, stage),
                    score = COALESCE(?, score), notes = COALESCE(?, notes), metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (email, website, phone, address, niche, stage, score, notes, metadata, now, existing[0]),
            )
            lead_id = existing[0]
        else:
            conn.execute(
                """
                INSERT INTO leads(company_name, email, website, phone, address, niche, stage, score, notes, metadata, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (company_name, email, website, phone, address, niche, stage, score, notes, metadata, now, now),
            )
            lead_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_leads(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    if _firebase_enabled():
        payload = _firebase_request("GET", "leads") or {}
        if isinstance(payload, dict):
            return [_normalize_firebase_lead(lead_id, lead_data) for lead_id, lead_data in payload.items()]
        return []

    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM leads ORDER BY updated_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_lead_stage(db_path: Optional[str] = None, lead_id: int = None, stage: str = None) -> Dict[str, Any]:
    if _firebase_enabled():
        response = _firebase_request("PATCH", f"leads/{lead_id}", {"stage": stage, "updated_at": datetime.utcnow().isoformat()})
        return _normalize_firebase_lead(str(lead_id), response)

    conn = _connect(db_path)
    try:
        now = datetime.utcnow().isoformat()
        conn.execute("UPDATE leads SET stage = ?, updated_at = ? WHERE id = ?", (stage, now, lead_id))
        conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def update_lead_details(db_path: Optional[str] = None, lead_id: int = None, updates: Dict[str, Any] = None) -> Dict[str, Any]:
    if updates is None:
        updates = {}

    if _firebase_enabled():
        payload = dict(updates)
        payload["updated_at"] = datetime.utcnow().isoformat()
        response = _firebase_request("PATCH", f"leads/{lead_id}", payload)
        return _normalize_firebase_lead(str(lead_id), response)

    conn = _connect(db_path)
    try:
        now = datetime.utcnow().isoformat()
        fields = []
        values = []
        for key, value in updates.items():
            if key in {"id"}:
                continue
            fields.append(f"{key} = ?")
            values.append(value)
        if not fields:
            return {}
        fields.append("updated_at = ?")
        values.extend([now, lead_id])
        conn.execute(f"UPDATE leads SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()
