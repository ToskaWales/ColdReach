import os

import pandas as pd
import streamlit as st
import json
import urllib.parse

from scout.export import build_dataframe
from scout.manager import (
    get_settings,
    init_db,
    is_firebase_enabled,
    list_leads,
    get_lead,
    add_activity,
    save_settings,
    upsert_lead,
    update_lead_details,
    update_lead_stage,
)
from scout.pipeline import evaluate_businesses, find_businesses
from scout.sources.osm import BRANCHE_TAG_MAP

st.set_page_config(page_title="ColdReach CRM", page_icon="🔍", layout="wide")

DB_PATH = os.path.join(os.getcwd(), "data", "leads.db")
init_db(DB_PATH)

# If the Streamlit secrets contain the Firebase service-account JSON, write it
# to a local file and expose its path via environment variable so the manager
# can load it (useful for Streamlit Cloud where files cannot be uploaded).
firebase_secrets = {}
try:
    firebase_secrets = st.secrets.get("firebase", {}) if hasattr(st, "secrets") else {}
except Exception:
    firebase_secrets = {}

service_account_path = None
if firebase_secrets:
    sa = firebase_secrets.get("service_account_json") or firebase_secrets.get("service_account")
    if sa:
        try:
            os.makedirs(os.path.join(os.getcwd(), ".streamlit"), exist_ok=True)
            service_account_path = os.path.join(os.getcwd(), ".streamlit", "serviceAccountKey.json")
            # sa may be a dict or a JSON string
            if isinstance(sa, dict):
                with open(service_account_path, "w", encoding="utf-8") as fh:
                    json.dump(sa, fh)
            else:
                # write raw text
                with open(service_account_path, "w", encoding="utf-8") as fh:
                    fh.write(sa)
            os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"] = service_account_path
        except Exception:
            service_account_path = None

settings = get_settings(DB_PATH)

st.title("🔍 ColdReach — CRM")
st.caption("Finde lokale Unternehmen, prüfe deren Website und pflege sie direkt als Leads in einer Firebase-basierten CRM-Datenbank.")

if is_firebase_enabled():
    st.success("Firebase-Datenbank verbunden. Leads und Status werden dort gespeichert.")
else:
    st.info("Firebase ist noch nicht konfiguriert. Die App läuft dann weiter lokal mit SQLite.")

if "rows" not in st.session_state:
    st.session_state.rows = None
if "businesses_count" not in st.session_state:
    st.session_state.businesses_count = None

stage_options = ["New", "Analyzed", "Email Drafted", "Sent", "Replied", "Demo Call", "Won", "Lost"]

with st.sidebar:
    st.header("Einstellungen")
    business_name = st.text_input("Firmenname", value=settings.get("business_name", "ColdReach"))
    contact_person = st.text_input("Ansprechpartner", value=settings.get("contact_person", ""))
    contact_email = st.text_input("E-Mail", value=settings.get("contact_email", ""))
    contact_phone = st.text_input("Telefon", value=settings.get("contact_phone", ""))
    signature = st.text_area("Signatur", value=settings.get("signature", ""), height=120)
    if st.button("Einstellungen speichern", use_container_width=True):
        save_settings(
            DB_PATH,
            {
                "business_name": business_name,
                "contact_person": contact_person,
                "contact_email": contact_email,
                "contact_phone": contact_phone,
                "signature": signature,
            },
        )
        st.success("Einstellungen gespeichert.")

    st.header("Suchparameter")
    branchen_options = sorted(BRANCHE_TAG_MAP.keys())
    branchen = st.multiselect(
        "Branche(n)",
        options=branchen_options,
        default=["friseur"],
        format_func=lambda k: k.capitalize(),
    )
    ort = st.text_input("Ort", value="Bayreuth")
    radius = st.number_input("Suchradius (Meter)", min_value=500, max_value=50000, value=5000, step=500)
    limit = st.number_input(
        "Limit (0 = alle)", min_value=0, value=0, step=5,
        help="Zum Testen die Anzahl geprüfter Firmen begrenzen.",
    )
    start = st.button("Suche starten", type="primary", use_container_width=True)

if start:
    if not branchen:
        st.error("Bitte mindestens eine Branche auswählen.")
    else:
        with st.spinner(f"Suche Firmen für {', '.join(branchen)} in {ort} ..."):
            try:
                businesses = find_businesses(branchen, ort, int(radius))
            except Exception as e:
                st.error(f"Fehler bei der Firmensuche: {e}")
                businesses = []

        if limit:
            businesses = businesses[: int(limit)]

        st.session_state.businesses_count = len(businesses)

        if businesses:
            progress_bar = st.progress(0, text="Starte Website-Prüfung ...")

            def on_progress(i, total, name):
                progress_bar.progress(i / total, text=f"Prüfe {i}/{total}: {name}")

            rows = evaluate_businesses(businesses, csv_path=None, on_progress=on_progress)
            progress_bar.empty()
            st.session_state.rows = rows
            error_count = sum(1 for row in rows if row.get("status") == "ERROR" or row.get("status_detail"))
            if error_count:
                st.warning(
                    f"{error_count} Einträge konnten nicht zuverlässig geprüft werden. "
                    "Details sind in der Tabelle sichtbar."
                )

            for row in rows:
                upsert_lead(
                    DB_PATH,
                    {
                        "company_name": row.get("name"),
                        "website": row.get("website"),
                        "address": row.get("adresse"),
                        "phone": row.get("telefon"),
                        "stage": "New",
                        "score": row.get("score"),
                        "notes": row.get("status_detail") or "",
                        "metadata": {"status": row.get("status")},
                    },
                )
        else:
            st.warning("Keine Firmen gefunden.")
            st.session_state.rows = None

if st.session_state.rows is not None:
    st.success(f"{st.session_state.businesses_count} Firmen geprüft.")

    min_score = st.slider("Minimaler Score (Filter)", 0, 100, 0)
    df = build_dataframe(st.session_state.rows, min_score)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Keine Website / nicht erreichbar", int((df["score"] == 100).sum()))
    with col2:
        st.metric("Wirkt aktuell (Score < 20)", int((df["score"] < 20).sum()))

    st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()
st.subheader("CRM-Übersicht")
leads = list_leads(DB_PATH)
if leads:
    lead_df = pd.DataFrame(leads)
    selected_stage_filter = st.selectbox("Status filtern", options=["Alle", *stage_options])
    if selected_stage_filter != "Alle":
        lead_df = lead_df[lead_df["stage"] == selected_stage_filter]

    if lead_df.empty:
        st.info("Keine Leads für diesen Status vorhanden.")
    else:
        st.dataframe(
            lead_df[["company_name", "website", "stage", "score", "updated_at", "next_follow_up"]],
            use_container_width=True,
            hide_index=True,
        )

    lead_options = [(lead["id"], lead["company_name"] or f"Lead {lead['id']}") for lead in leads]
    selected_lead_id = st.selectbox(
        "Lead bearbeiten",
        options=[lead_id for lead_id, _ in lead_options],
        format_func=lambda lead_id: next(name for current_id, name in lead_options if current_id == lead_id),
    )
    selected_lead = get_lead(DB_PATH, selected_lead_id)

    with st.form("lead_editor"):
        company_name = st.text_input("Unternehmen", value=selected_lead.get("company_name") or "")
        website = st.text_input("Website", value=selected_lead.get("website") or "")
        email = st.text_input("E-Mail", value=selected_lead.get("email") or "")
        phone = st.text_input("Telefon", value=selected_lead.get("phone") or "")
        stage = st.selectbox(
            "Stage",
            options=stage_options,
            index=stage_options.index(selected_lead.get("stage") or "New"),
        )
        notes = st.text_area("Notizen", value=selected_lead.get("notes") or "")
        next_follow_up = st.text_input("Nächster Follow-up", value=selected_lead.get("next_follow_up") or "")
        submitted = st.form_submit_button("Änderungen speichern")

        if submitted:
            update_lead_details(
                DB_PATH,
                selected_lead_id,
                {
                    "company_name": company_name,
                    "website": website,
                    "email": email,
                    "phone": phone,
                    "stage": stage,
                    "notes": notes,
                    "next_follow_up": next_follow_up,
                },
            )
            st.success("Lead aktualisiert.")
            st.rerun()
    st.markdown("---")
    st.subheader("Aktivitäten / Historie")
    activities = selected_lead.get("activities") or []
    if activities:
        # Provide simple filtering controls
        actors = sorted({a.get("actor") or "" for a in activities})
        actions = sorted({a.get("action") or "" for a in activities})
        colf1, colf2 = st.columns(2)
        with colf1:
            selected_actors = st.multiselect("Filter nach Akteur", options=actors, default=actors)
        with colf2:
            selected_actions = st.multiselect("Filter nach Aktion", options=actions, default=actions)

        filtered = [a for a in activities if (a.get("actor") or "") in selected_actors and (a.get("action") or "") in selected_actions]
        # show most recent first
        act_df = pd.DataFrame(sorted(filtered, key=lambda r: r.get("timestamp", ""), reverse=True))
        st.dataframe(act_df, use_container_width=True)
    else:
        st.info("Noch keine Aktivitäten geloggt.")

    st.subheader("Neue Aktivität hinzufügen")
    with st.form("activity_form"):
        actor = settings.get("contact_person") or "Ich"
        st.write(f"Als: **{actor}**")
        action_type = st.selectbox("Aktion", options=["Email Sent", "Call", "Note", "Meeting", "Stage Change", "Other"])
        action_notes = st.text_area("Notizen")
        change_stage = None
        if action_type == "Stage Change":
            change_stage = st.selectbox("Neue Stage", options=stage_options, index=0)
        activity_submit = st.form_submit_button("Aktivität speichern")

        if activity_submit:
            add_activity(DB_PATH, selected_lead_id, actor=actor, action=action_type, notes=action_notes)
            if change_stage:
                update_lead_stage(DB_PATH, selected_lead_id, change_stage)
            st.success("Aktivität gespeichert.")
            st.rerun()
    if selected_lead.get("email"):
        # Build an email draft using signature and lead data
        subject = f"Hallo {selected_lead.get('company_name') or ''}"
        body_lines = [f"Hallo {selected_lead.get('company_name') or ''},", "", "[Hier deine Nachricht einfügen]", "", settings.get("signature", "")]
        body = "\n".join(body_lines)
        mailto = f"mailto:{selected_lead.get('email')}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
        st.markdown(f"[E-Mail verfassen]({mailto})")
else:
    st.info("Noch keine Leads gespeichert.")

st.divider()
st.subheader("Neuen Lead anlegen")
with st.form("new_lead"):
    new_company = st.text_input("Unternehmen")
    new_website = st.text_input("Website")
    new_email = st.text_input("E-Mail")
    new_phone = st.text_input("Telefon")
    new_stage = st.selectbox("Stage", options=stage_options)
    new_notes = st.text_area("Notizen")
    new_submit = st.form_submit_button("Lead speichern")
    if new_submit:
        upsert_lead(
            DB_PATH,
            {
                "company_name": new_company,
                "website": new_website,
                "email": new_email,
                "phone": new_phone,
                "stage": new_stage,
                "notes": new_notes,
            },
        )
        st.success("Lead gespeichert.")
        st.rerun()


