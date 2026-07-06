import re
from typing import Callable, List, Optional

from scout.errors import format_error_details
from scout.export import IncrementalCSVWriter, build_row
from scout.fetcher import WebsiteFetcher
from scout.models import Business, WebsiteCheckResult
from scout.scoring import evaluate_business
from scout.sources.base import BusinessSource
from scout.sources.google_places import GooglePlacesSource
from scout.sources.osm import OSMSource

ProgressCallback = Callable[[int, int, str], None]


def _normalize(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _name_key(name: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", _normalize(name))


def _addresses_match(a: str, b: str) -> bool:
    """Loose containment match rather than equality: OSM composes addresses as
    "Street 12, 12345 City" while Google's formatted_address for the same
    place is usually "Street 12, 12345 City, Deutschland" (plus other minor
    formatting differences) — an exact-equality check almost never merges
    the same real-world business found via both sources."""
    if not a or not b:
        return False
    return a in b or b in a


def dedupe_businesses(businesses: List[Business]) -> List[Business]:
    """Drop exact re-fetches of the same element (e.g. a business matched by
    two overlapping Branche filters, or returned by two different sources).
    Dedup by (source, raw_id) rather than name+address: many entries lack
    address tags, and name-based dedup was silently collapsing distinct
    branches of the same chain (same name, no address) into a single result.

    Additionally, merge cross-source duplicates of the same real-world
    business (matching name + overlapping non-empty address) so a
    website/phone missing from one source (commonly OSM) can be filled in by
    another (e.g. Google Places) instead of creating a second, incomplete
    lead that looks like it has "no website" when it really does."""
    seen_ids = set()
    kept: List[Business] = []
    for b in businesses:
        id_key = (b.source, b.raw_id)
        if id_key in seen_ids:
            continue
        seen_ids.add(id_key)

        name_key = _name_key(b.name)
        address_key = _normalize(b.address)

        match = None
        if address_key:
            for existing in kept:
                if _name_key(existing.name) == name_key and _addresses_match(address_key, _normalize(existing.address)):
                    match = existing
                    break

        if match is not None:
            match.website = match.website or b.website
            match.phone = match.phone or b.phone
            continue

        kept.append(b)
    return kept


def find_businesses(
    branches: List[str], ort: str, radius: int, google_places_api_key: Optional[str] = None
) -> List[Business]:
    sources: List[BusinessSource] = [OSMSource()]
    if google_places_api_key:
        sources.append(GooglePlacesSource(google_places_api_key))

    all_businesses: List[Business] = []
    errors: List[str] = []
    for source in sources:
        for branche in branches:
            try:
                all_businesses.extend(source.get_businesses(branche, ort, radius))
            except Exception as exc:
                errors.append(str(exc))

    if errors and not all_businesses:
        raise RuntimeError("; ".join(errors))

    return dedupe_businesses(all_businesses)


def evaluate_businesses(
    businesses: List[Business],
    csv_path: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> List[dict]:
    fetcher = WebsiteFetcher()
    writer = IncrementalCSVWriter(csv_path) if csv_path else None
    rows = []
    total = len(businesses)
    try:
        for i, business in enumerate(businesses, start=1):
            try:
                result = evaluate_business(business, fetcher)
            except Exception as exc:
                result = WebsiteCheckResult(
                    status="ERROR",
                    score=None,
                    error_detail=format_error_details(
                        exc,
                        context=f"Prüfung fehlgeschlagen für {business.name} ({business.website})",
                    ),
                )
            row = build_row(business, result)
            rows.append(row)
            if writer:
                writer.write_row(row)
            if on_progress:
                on_progress(i, total, business.name)
    finally:
        if writer:
            writer.close()
    return rows
