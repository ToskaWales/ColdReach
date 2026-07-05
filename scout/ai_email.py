import json
import re
from typing import List, Optional

import anthropic
from bs4 import BeautifulSoup

from scout.fetcher import WebsiteFetcher

MODEL_ID = "claude-opus-4-8"
MAX_PAGE_CHARS = 6000

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return text[:MAX_PAGE_CHARS]


def generate_email_draft(
    api_key: str,
    lead: dict,
    settings: dict,
    known_issues: Optional[List[str]] = None,
) -> dict:
    """Re-scrape the lead's website and have Claude draft a personalized
    German cold-outreach email that references concrete, current findings
    rather than a generic template."""
    website = lead.get("website") or ""
    page_text = ""
    if website:
        result = WebsiteFetcher().fetch(website)
        if result.status == "OK" and result.html:
            page_text = _extract_visible_text(result.html)

    context_lines = [
        f"Firma: {lead.get('company_name') or 'unbekannt'}",
        f"Website: {website or 'keine'}",
    ]
    if known_issues:
        context_lines.append("Bereits bekannte Probleme: " + ", ".join(known_issues))
    if page_text:
        context_lines.append(f"Aktueller Text-Auszug der Website:\n{page_text}")
    else:
        context_lines.append("Die Website konnte gerade nicht abgerufen werden oder es existiert keine.")

    absender = settings.get("contact_person") or settings.get("business_name") or "Ich"
    signature = settings.get("signature") or absender

    system_prompt = (
        "Du bist ein deutschsprachiger Vertriebstexter fuer eine Agentur, die lokalen "
        "Unternehmen hilft, ihre Website zu modernisieren. Du schreibst kurze, konkrete "
        "Cold-Outreach-E-Mails. Nenne 1-2 spezifische, aus dem gelieferten Text oder den "
        "bekannten Problemen belegbare Schwachstellen der Website (z.B. veraltetes Design, "
        "fehlendes Impressum, keine mobile Ansicht, fehlendes Kontaktformular, alte "
        "Copyright-Jahreszahl, kein HTTPS) statt generischer Floskeln. Erfinde keine "
        "Probleme, die nicht belegt sind. Ton: freundlich, professionell, kurz "
        "(max. 120 Woerter Fliesstext)."
    )

    user_prompt = (
        "\n".join(context_lines)
        + f"\n\nAbsender: {absender}\nSignatur fuer die E-Mail:\n{signature}\n\n"
        "Verfasse Betreff und Nachricht einer Cold-Outreach-E-Mail auf Deutsch. "
        "Schliesse die Signatur am Ende der Nachricht mit ein."
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return {"subject": data["subject"], "body": data["body"]}
