import re
from typing import Callable, Dict, List, Optional, Tuple

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


def dedupe_businesses(businesses: List[Business]) -> List[Business]:
    """Drop exact re-fetches of the same element (e.g. a business matched by
    two overlapping Branche filters, or returned by two different sources).
    Dedup by (source, raw_id) rather than name+address: many entries lack
    address tags, and name-based dedup was silently collapsing distinct
    branches of the same chain (same name, no address) into a single result.

    Additionally, merge cross-source duplicates of the same real-world
    business (matching name + non-empty address) so a website/phone missing
    from one source (commonly OSM) can be filled in by another (e.g. Google
    Places) instead of creating a second, incomplete lead."""
    seen_ids = set()
    by_fingerprint: Dict[Tuple[str, str], Business] = {}
    deduped: List[Business] = []
    for b in businesses:
        id_key = (b.source, b.raw_id)
        if id_key in seen_ids:
            continue
        seen_ids.add(id_key)

        address_key = _normalize(b.address)
        fingerprint = (re.sub(r"[^a-z0-9]", "", _normalize(b.name)), address_key) if address_key else None

        existing = by_fingerprint.get(fingerprint) if fingerprint else None
        if existing is not None:
            existing.website = existing.website or b.website
            existing.phone = existing.phone or b.phone
            continue

        if fingerprint:
            by_fingerprint[fingerprint] = b
        deduped.append(b)
    return deduped


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
