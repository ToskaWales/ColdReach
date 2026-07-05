import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

DEFAULT_SETTINGS = {
    "business_name": "ColdReach",
    "contact_person": "",
    "contact_email": "",
    "contact_phone": "",
    "signature": "",
    "default_stage": "New",
    "email_subject_template": "Kurze Frage zu Ihrer Website – {company_name}",
    "email_body_template": (
        "Hallo {company_name} Team,\n\n"
        "mir ist aufgefallen, dass Ihre Website Verbesserungspotenzial hat "
        "(z.B. bei Aktualität, Sicherheit oder mobiler Darstellung). "
        "[Hier deine Nachricht einfügen]\n\n"
        "Beste Grüße\n"
        "{signature}"
    ),
    "anthropic_api_key": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "sender_email": "",
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


def get_lead(db_path: Optional[str] = None, lead_id: Optional[str] = None) -> Dict[str, Any]:
    """Return a single lead with its activities."""
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
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM leads ORDER BY updated_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_lead_stage(db_path: Optional[str] = None, lead_id: int = None, stage: str = None) -> Dict[str, Any]:
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
