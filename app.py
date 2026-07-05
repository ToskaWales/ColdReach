import os
import urllib.parse

import pandas as pd
import streamlit as st

from scout.ai_email import generate_email_draft
from scout.export import build_dataframe
from scout.mailer import send_email
from scout.manager import (
    get_settings,
    init_db,
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

DEFAULT_APP_PASSWORD = "123admin"
try:
    _auth_secrets = st.secrets.get("auth", {}) if hasattr(st, "secrets") else {}
except Exception:
    _auth_secrets = {}
APP_PASSWORD = _auth_secrets.get("password", DEFAULT_APP_PASSWORD)


def _check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.title("🔍 ColdReach — CRM")
    st.text_input("Passwort", type="password", key="login_password")
    if st.button("Anmelden", type="primary"):
        if st.session_state.get("login_password") == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Falsches Passwort.")
    return False


if not _check_password():
    st.stop()

DB_PATH = os.path.join(os.getcwd(), "data", "leads.db")
init_db(DB_PATH)

settings = get_settings(DB_PATH)

STAGE_OPTIONS = ["New", "Analyzed", "Email Drafted", "Sent", "Replied", "Demo Call", "Won", "Lost"]
STAGE_BADGES = {
    "New": "🔵 New",
    "Analyzed": "🟣 Analyzed",
    "Email Drafted": "🟡 Email Drafted",
    "Sent": "🟠 Sent",
    "Replied": "🟢 Replied",
    "Demo Call": "🟢 Demo Call",
    "Won": "✅ Won",
    "Lost": "⚫ Lost",
}

st.title("🔍 ColdReach — CRM")
st.caption("Finde lokale Unternehmen, prüfe deren Website und pflege sie als Leads.")

if "rows" not in st.session_state:
    st.session_state.rows = None
if "businesses_count" not in st.session_state:
    st.session_state.businesses_count = None

tab_search, tab_crm, tab_settings = st.tabs(["🔎 Firmen finden", "📇 CRM", "⚙️ Einstellungen"])

# ----------------------------------------------------------------------------
# Firmensuche
# ----------------------------------------------------------------------------
with tab_search:
    st.subheader("Suchparameter")
    branchen_options = sorted(BRANCHE_TAG_MAP.keys())
    col1, col2 = st.columns([2, 1])
    with col1:
        branchen = st.multiselect(
            "Branche(n)",
            options=branchen_options,
            default=["friseur"],
            format_func=lambda k: k.capitalize(),
        )
        ort = st.text_input("Ort", value="Bayreuth")
    with col2:
        radius = st.number_input("Suchradius (Meter)", min_value=500, max_value=50000, value=5000, step=500)
        limit = st.number_input(
            "Limit (0 = alle)", min_value=0, value=0, step=5,
            help="Zum Testen die Anzahl geprüfter Firmen begrenzen.",
        )
    start = st.button("Suche starten", type="primary")

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
                            "email": row.get("email"),
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
        st.success(f"{st.session_state.businesses_count} Firmen geprüft und in die CRM-Liste übernommen.")

        min_score = st.slider("Minimaler Score (Filter)", 0, 100, 0)
        df = build_dataframe(st.session_state.rows, min_score)

        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric("Geprüfte Firmen", len(df))
        metric_col2.metric("Keine Website / nicht erreichbar", int((df["score"] == 100).sum()))
        metric_col3.metric("Wirkt aktuell (Score < 20)", int((df["score"] < 20).sum()))

        st.dataframe(df, width="stretch", hide_index=True)

# ----------------------------------------------------------------------------
# CRM
# ----------------------------------------------------------------------------
with tab_crm:
    leads = list_leads(DB_PATH)

    if not leads:
        st.info("Noch keine Leads gespeichert. Starte eine Suche im Tab 'Firmen finden' oder lege unten einen Lead manuell an.")
    else:
        lead_df = pd.DataFrame(leads)
        stage_counts = lead_df["stage"].value_counts()

        metric_cols = st.columns(4)
        metric_cols[0].metric("Leads gesamt", len(lead_df))
        metric_cols[1].metric("Neu", int(stage_counts.get("New", 0)))
        metric_cols[2].metric("Kontaktiert", int(stage_counts.get("Email Drafted", 0) + stage_counts.get("Sent", 0)))
        metric_cols[3].metric("Gewonnen", int(stage_counts.get("Won", 0)))

        st.divider()

        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            search_text = st.text_input("🔍 Firma suchen", placeholder="Nach Name filtern ...")
        with filter_col2:
            stage_filter = st.selectbox("Status filtern", options=["Alle", *STAGE_OPTIONS])

        filtered_df = lead_df
        if stage_filter != "Alle":
            filtered_df = filtered_df[filtered_df["stage"] == stage_filter]
        if search_text:
            filtered_df = filtered_df[filtered_df["company_name"].str.contains(search_text, case=False, na=False)]

        if filtered_df.empty:
            st.info("Keine Leads für diese Filter.")
        else:
            display_df = filtered_df.copy()
            display_df["Status"] = display_df["stage"].map(STAGE_BADGES).fillna(display_df["stage"])
            st.dataframe(
                display_df[["company_name", "Status", "email", "website", "score", "next_follow_up"]],
                width="stretch",
                hide_index=True,
                column_config={
                    "company_name": "Unternehmen",
                    "email": "E-Mail",
                    "website": "Website",
                    "score": "Score",
                    "next_follow_up": "Follow-up",
                },
            )

        st.divider()
        st.subheader("Lead-Details")
        lead_options = [(lead["id"], lead["company_name"] or f"Lead {lead['id']}") for lead in leads]
        selected_lead_id = st.selectbox(
            "Lead auswählen",
            options=[lead_id for lead_id, _ in lead_options],
            format_func=lambda lead_id: next(name for current_id, name in lead_options if current_id == lead_id),
        )
        selected_lead = get_lead(DB_PATH, selected_lead_id)

        with st.container(border=True):
            header_col1, header_col2 = st.columns([3, 1])
            with header_col1:
                st.markdown(f"### {selected_lead.get('company_name') or 'Lead'}")
                if selected_lead.get("website"):
                    st.caption(selected_lead.get("website"))
            with header_col2:
                st.markdown(f"**{STAGE_BADGES.get(selected_lead.get('stage'), selected_lead.get('stage') or '')}**")
                if selected_lead.get("score") is not None:
                    st.caption(f"Score: {selected_lead.get('score')}")

            detail_tab_info, detail_tab_activity, detail_tab_email = st.tabs(
                ["📝 Daten", "🕘 Aktivitäten", "✉️ E-Mail-Entwurf"]
            )

            with detail_tab_info:
                with st.form("lead_editor"):
                    company_name = st.text_input("Unternehmen", value=selected_lead.get("company_name") or "")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        website = st.text_input("Website", value=selected_lead.get("website") or "")
                        email = st.text_input("E-Mail", value=selected_lead.get("email") or "")
                    with col_b:
                        phone = st.text_input("Telefon", value=selected_lead.get("phone") or "")
                        next_follow_up = st.text_input("Nächster Follow-up", value=selected_lead.get("next_follow_up") or "")
                    stage = st.selectbox(
                        "Stage",
                        options=STAGE_OPTIONS,
                        index=STAGE_OPTIONS.index(selected_lead.get("stage") or "New"),
                    )
                    notes = st.text_area("Notizen", value=selected_lead.get("notes") or "")
                    submitted = st.form_submit_button("Änderungen speichern", type="primary")

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

            with detail_tab_activity:
                activities = selected_lead.get("activities") or []
                if activities:
                    actors = sorted({a.get("actor") or "" for a in activities})
                    actions = sorted({a.get("action") or "" for a in activities})
                    colf1, colf2 = st.columns(2)
                    with colf1:
                        selected_actors = st.multiselect("Filter nach Akteur", options=actors, default=actors)
                    with colf2:
                        selected_actions = st.multiselect("Filter nach Aktion", options=actions, default=actions)

                    filtered_acts = [
                        a for a in activities
                        if (a.get("actor") or "") in selected_actors and (a.get("action") or "") in selected_actions
                    ]
                    act_df = pd.DataFrame(sorted(filtered_acts, key=lambda r: r.get("timestamp", ""), reverse=True))
                    st.dataframe(act_df, width="stretch", hide_index=True)
                else:
                    st.info("Noch keine Aktivitäten geloggt.")

                st.markdown("##### Neue Aktivität")
                with st.form("activity_form"):
                    actor = settings.get("contact_person") or "Ich"
                    st.caption(f"Als: **{actor}**")
                    action_type = st.selectbox("Aktion", options=["Email Sent", "Call", "Note", "Meeting", "Stage Change", "Other"])
                    action_notes = st.text_area("Notizen")
                    change_stage = None
                    if action_type == "Stage Change":
                        change_stage = st.selectbox("Neue Stage", options=STAGE_OPTIONS, index=0)
                    activity_submit = st.form_submit_button("Aktivität speichern")

                    if activity_submit:
                        add_activity(DB_PATH, selected_lead_id, actor=actor, action=action_type, notes=action_notes)
                        if change_stage:
                            update_lead_stage(DB_PATH, selected_lead_id, change_stage)
                        st.success("Aktivität gespeichert.")
                        st.rerun()

            with detail_tab_email:
                if not selected_lead.get("email"):
                    st.warning(
                        "Für diesen Lead ist keine E-Mail-Adresse hinterlegt. "
                        "Trage sie im Tab 'Daten' ein — ColdReach übernimmt sie sonst automatisch, "
                        "wenn eine Adresse auf der Website gefunden wird."
                    )
                else:
                    ai_draft_key = f"ai_draft_{selected_lead_id}"

                    if st.button("🤖 KI-Entwurf erstellen (durchsucht die Website erneut)", width="stretch"):
                        if not settings.get("anthropic_api_key"):
                            st.error("Bitte zuerst einen Anthropic API-Key unter 'Einstellungen' hinterlegen.")
                        else:
                            with st.spinner("KI analysiert die Website und verfasst einen Entwurf ..."):
                                try:
                                    known_issues = []
                                    metadata = selected_lead.get("metadata")
                                    if isinstance(metadata, str):
                                        import json as _json
                                        try:
                                            metadata = _json.loads(metadata)
                                        except Exception:
                                            metadata = {}
                                    if isinstance(metadata, dict) and metadata.get("status"):
                                        known_issues.append(str(metadata["status"]))
                                    if selected_lead.get("notes"):
                                        known_issues.append(selected_lead["notes"])

                                    draft = generate_email_draft(
                                        api_key=settings["anthropic_api_key"],
                                        lead=selected_lead,
                                        settings=settings,
                                        known_issues=known_issues,
                                    )
                                    st.session_state[ai_draft_key] = draft
                                except Exception as e:
                                    st.error(f"KI-Entwurf fehlgeschlagen: {e}")

                    context = {
                        "company_name": selected_lead.get("company_name") or "",
                        "contact_person": settings.get("contact_person") or "",
                        "business_name": settings.get("business_name") or "",
                        "signature": settings.get("signature") or "",
                    }
                    ai_draft = st.session_state.get(ai_draft_key)
                    if ai_draft:
                        default_subject = ai_draft["subject"]
                        default_body = ai_draft["body"]
                    else:
                        try:
                            default_subject = settings.get("email_subject_template", "").format(**context)
                        except Exception:
                            default_subject = settings.get("email_subject_template", "")
                        try:
                            default_body = settings.get("email_body_template", "").format(**context)
                        except Exception:
                            default_body = settings.get("email_body_template", "")

                    st.caption(f"An: {selected_lead.get('email')}")
                    subject = st.text_input("Betreff", value=default_subject, key=f"subject_{selected_lead_id}")
                    body = st.text_area("Nachricht", value=default_body, height=220, key=f"body_{selected_lead_id}")

                    mailto = f"mailto:{selected_lead.get('email')}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
                    btn_col1, btn_col2, btn_col3 = st.columns(3)
                    with btn_col1:
                        smtp_ready = bool(
                            settings.get("smtp_host") and settings.get("smtp_username")
                            and settings.get("smtp_password") and (settings.get("sender_email") or settings.get("contact_email"))
                        )
                        if st.button("📤 Senden", type="primary", width="stretch", disabled=not smtp_ready):
                            try:
                                send_email(
                                    smtp_host=settings["smtp_host"],
                                    smtp_port=int(settings.get("smtp_port") or 587),
                                    username=settings["smtp_username"],
                                    password=settings["smtp_password"],
                                    sender=settings.get("sender_email") or settings.get("contact_email"),
                                    to=selected_lead["email"],
                                    subject=subject,
                                    body=body,
                                )
                                update_lead_stage(DB_PATH, selected_lead_id, "Sent")
                                add_activity(
                                    DB_PATH, selected_lead_id,
                                    actor=settings.get("contact_person") or "Ich",
                                    action="Email Sent",
                                    notes=subject,
                                )
                                st.success("E-Mail versendet.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Versand fehlgeschlagen: {e}")
                        if not smtp_ready:
                            st.caption("SMTP-Zugangsdaten fehlen (siehe Einstellungen).")
                    with btn_col2:
                        st.link_button("📧 E-Mail-Client öffnen", mailto, width="stretch")
                    with btn_col3:
                        if st.button("Als 'Email Drafted' markieren", width="stretch"):
                            update_lead_stage(DB_PATH, selected_lead_id, "Email Drafted")
                            add_activity(
                                DB_PATH, selected_lead_id,
                                actor=settings.get("contact_person") or "Ich",
                                action="Note",
                                notes="Email-Entwurf erstellt.",
                            )
                            st.success("Stage aktualisiert.")
                            st.rerun()

    st.divider()
    with st.expander("➕ Neuen Lead manuell anlegen"):
        with st.form("new_lead"):
            new_company = st.text_input("Unternehmen")
            new_website = st.text_input("Website")
            new_email = st.text_input("E-Mail")
            new_phone = st.text_input("Telefon")
            new_stage = st.selectbox("Stage", options=STAGE_OPTIONS, key="new_lead_stage")
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

# ----------------------------------------------------------------------------
# Einstellungen
# ----------------------------------------------------------------------------
with tab_settings:
    st.subheader("Firmenprofil")
    business_name = st.text_input("Firmenname", value=settings.get("business_name", "ColdReach"))
    contact_person = st.text_input("Ansprechpartner", value=settings.get("contact_person", ""))
    contact_email = st.text_input("E-Mail", value=settings.get("contact_email", ""))
    contact_phone = st.text_input("Telefon", value=settings.get("contact_phone", ""))
    signature = st.text_area("Signatur", value=settings.get("signature", ""), height=120)

    st.subheader("E-Mail-Vorlage")
    st.caption("Platzhalter: {company_name}, {contact_person}, {business_name}, {signature}. Wird verwendet, wenn kein KI-Entwurf erstellt wurde.")
    email_subject_template = st.text_input("Betreff-Vorlage", value=settings.get("email_subject_template", ""))
    email_body_template = st.text_area("Nachrichten-Vorlage", value=settings.get("email_body_template", ""), height=200)

    st.subheader("KI-Entwürfe")
    st.caption("Wird verwendet, um automatisch personalisierte E-Mail-Entwürfe zu verfassen (analysiert dafür die Website erneut).")
    anthropic_api_key = st.text_input(
        "Anthropic API-Key", value=settings.get("anthropic_api_key", ""), type="password"
    )

    st.subheader("E-Mail-Versand (SMTP)")
    st.caption("Zugangsdaten, damit E-Mails direkt aus ColdReach per Knopfdruck verschickt werden können.")
    smtp_col1, smtp_col2 = st.columns(2)
    with smtp_col1:
        smtp_host = st.text_input("SMTP-Server", value=settings.get("smtp_host", ""), placeholder="smtp.gmail.com")
        smtp_username = st.text_input("SMTP-Benutzername", value=settings.get("smtp_username", ""))
        sender_email = st.text_input(
            "Absenderadresse", value=settings.get("sender_email", ""),
            placeholder="Standard: E-Mail oben",
        )
    with smtp_col2:
        smtp_port = st.text_input("SMTP-Port", value=settings.get("smtp_port", "587"))
        smtp_password = st.text_input("SMTP-Passwort", value=settings.get("smtp_password", ""), type="password")

    if st.button("Einstellungen speichern", type="primary"):
        save_settings(
            DB_PATH,
            {
                "business_name": business_name,
                "contact_person": contact_person,
                "contact_email": contact_email,
                "contact_phone": contact_phone,
                "signature": signature,
                "email_subject_template": email_subject_template,
                "email_body_template": email_body_template,
                "anthropic_api_key": anthropic_api_key,
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "smtp_username": smtp_username,
                "smtp_password": smtp_password,
                "sender_email": sender_email,
            },
        )
        st.success("Einstellungen gespeichert.")
        st.rerun()
