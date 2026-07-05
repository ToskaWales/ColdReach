import time
from typing import List, Optional, Tuple

import requests

from scout.config import OVERPASS_MIRRORS, USER_AGENT
from scout.models import Business
from scout.sources.base import BusinessSource

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Maps a German Branche search term to one or more OSM tag filters (key, value).
# value "*" means "any value for this key".
BRANCHE_TAG_MAP = {
    "restaurant": [("amenity", "restaurant")],
    "gaststaette": [("amenity", "restaurant")],
    "friseur": [("shop", "hairdresser")],
    "frisoer": [("shop", "hairdresser")],
    "handwerker": [("craft", "*")],
    "handwerk": [("craft", "*")],
    "baecker": [("shop", "bakery")],
    "baeckerei": [("shop", "bakery")],
    "metzger": [("shop", "butcher")],
    "metzgerei": [("shop", "butcher")],
    "zahnarzt": [("amenity", "dentist")],
    "arzt": [("amenity", "doctors")],
    "anwalt": [("office", "lawyer")],
    "rechtsanwalt": [("office", "lawyer")],
    "steuerberater": [("office", "tax_advisor")],
    "hotel": [("tourism", "hotel")],
    "pension": [("tourism", "guest_house")],
    "cafe": [("amenity", "cafe")],
    "café": [("amenity", "cafe")],
    "physiotherapie": [("healthcare", "physiotherapist"), ("amenity", "physiotherapist")],
    "kfz": [("shop", "car_repair")],
    "autowerkstatt": [("shop", "car_repair")],
    "immobilienmakler": [("office", "estate_agent")],
    "makler": [("office", "estate_agent")],
    "optiker": [("shop", "optician")],
    "blumenladen": [("shop", "florist")],
    "florist": [("shop", "florist")],
    "elektriker": [("craft", "electrician")],
    "sanitaer": [("craft", "plumber")],
    "installateur": [("craft", "plumber")],
    "maler": [("craft", "painter")],
    "tischler": [("craft", "carpenter")],
    "schreiner": [("craft", "carpenter")],
}


def _normalize_branche(branche: str) -> str:
    replacements = {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        "Ä": "ae", "Ö": "oe", "Ü": "ue",
    }
    normalized = branche.strip().lower()
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)
    return normalized


def resolve_branche_tags(branche: str) -> List[Tuple[str, str]]:
    key = _normalize_branche(branche)
    if key in BRANCHE_TAG_MAP:
        return BRANCHE_TAG_MAP[key]
    raise ValueError(
        f"Unbekannte Branche '{branche}'. Unterstützt: {', '.join(sorted(BRANCHE_TAG_MAP.keys()))}. "
        "Alternativ direkt ein OSM-Tag als 'key=value' übergeben."
    )


def geocode_location(place_name: str) -> Tuple[float, float]:
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": place_name, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Ort '{place_name}' konnte nicht geokodiert werden: {exc}") from exc

    results = resp.json()
    if not results:
        raise ValueError(f"Ort '{place_name}' konnte nicht geokodiert werden.")
    return float(results[0]["lat"]), float(results[0]["lon"])


def _build_overpass_query(tags: List[Tuple[str, str]], lat: float, lon: float, radius: int) -> str:
    filters = []
    for key, value in tags:
        if value == "*":
            filters.append(f'node["{key}"](around:{radius},{lat},{lon});')
            filters.append(f'way["{key}"](around:{radius},{lat},{lon});')
        else:
            filters.append(f'node["{key}"="{value}"](around:{radius},{lat},{lon});')
            filters.append(f'way["{key}"="{value}"](around:{radius},{lat},{lon});')
    body = "\n  ".join(filters)
    return f"""
[out:json][timeout:25];
(
  {body}
);
out center tags;
""".strip()


def _compose_address(tags: dict) -> str:
    parts = []
    street = tags.get("addr:street")
    housenumber = tags.get("addr:housenumber")
    if street:
        parts.append(f"{street} {housenumber}".strip() if housenumber else street)
    postcode = tags.get("addr:postcode")
    city = tags.get("addr:city")
    if postcode or city:
        parts.append(f"{postcode or ''} {city or ''}".strip())
    return ", ".join(p for p in parts if p)


def _extract_website(tags: dict) -> Optional[str]:
    for key in ("website", "contact:website", "url"):
        if tags.get(key):
            return tags[key]
    return None


def _extract_phone(tags: dict) -> Optional[str]:
    for key in ("phone", "contact:phone"):
        if tags.get(key):
            return tags[key]
    return None


def _query_overpass(overpass_query: str, max_retries: int = 3) -> dict:
    last_error = None
    for mirror in OVERPASS_MIRRORS:
        delay = 5
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    mirror,
                    data={"data": overpass_query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=30,
                )
            except requests.RequestException as exc:
                last_error = f"{mirror} (Versuch {attempt + 1}/{max_retries}) -> {exc}"
                break
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else delay
                time.sleep(wait)
                delay *= 2
                last_error = f"{mirror} -> HTTP 429"
                continue
            try:
                resp.raise_for_status()
            except requests.RequestException as exc:
                last_error = f"{mirror} -> {exc}"
                break
            return resp.json()
    raise RuntimeError(
        "Overpass API nicht erreichbar (auch nach Retries/Mirrors). Letzter Fehler: "
        f"{last_error}"
    )


class OSMSource(BusinessSource):
    def get_businesses(self, query: str, location: str, radius: int) -> List[Business]:
        tags = resolve_branche_tags(query)
        lat, lon = geocode_location(location)
        time.sleep(1)  # Nominatim usage policy: max 1 req/s

        overpass_query = _build_overpass_query(tags, lat, lon, radius)
        data = _query_overpass(overpass_query)
        elements = data.get("elements", [])

        businesses = []
        for el in elements:
            el_tags = el.get("tags", {})
            name = el_tags.get("name")
            if not name:
                continue
            businesses.append(
                Business(
                    name=name,
                    address=_compose_address(el_tags),
                    phone=_extract_phone(el_tags),
                    website=_extract_website(el_tags),
                    source="osm",
                    raw_id=f"{el.get('type')}/{el.get('id')}",
                )
            )
        return businesses
