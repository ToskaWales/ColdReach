from scout.manager import get_settings, init_db, list_leads, save_settings, upsert_lead, update_lead_details, update_lead_stage


def test_manager_persists_settings_and_leads(tmp_path):
    db_path = tmp_path / "leads.db"
    init_db(str(db_path))

    settings = get_settings(str(db_path))
    assert settings["business_name"] == "ColdReach"

    save_settings(str(db_path), {"business_name": "Acme Studio", "contact_person": "Mina"})
    settings = get_settings(str(db_path))
    assert settings["business_name"] == "Acme Studio"
    assert settings["contact_person"] == "Mina"

    lead = upsert_lead(
        str(db_path),
        {
            "company_name": "Muster GmbH",
            "website": "https://example.com",
            "stage": "New",
            "score": 42,
        },
    )

    rows = list_leads(str(db_path))
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Muster GmbH"
    assert rows[0]["score"] == 42

    update_lead_stage(str(db_path), lead["id"], "Analyzed")
    rows = list_leads(str(db_path))
    assert rows[0]["stage"] == "Analyzed"

    update_lead_details(str(db_path), lead["id"], {"notes": "Follow-up planned", "score": 88})
    rows = list_leads(str(db_path))
    assert rows[0]["notes"] == "Follow-up planned"
    assert rows[0]["score"] == 88


def test_init_db_does_not_wipe_saved_settings_on_restart(tmp_path):
    """init_db() runs on every app start and re-seeds defaults via
    create_missing=True; it must not clobber values the user already saved
    (API keys, SMTP creds, ...) with the blank defaults."""
    db_path = tmp_path / "leads.db"
    init_db(str(db_path))

    save_settings(str(db_path), {"anthropic_api_key": "sk-ant-secret", "smtp_host": "smtp.gmail.com"})

    # Simulate the app restarting: init_db() runs again on the same file.
    init_db(str(db_path))

    settings = get_settings(str(db_path))
    assert settings["anthropic_api_key"] == "sk-ant-secret"
    assert settings["smtp_host"] == "smtp.gmail.com"
