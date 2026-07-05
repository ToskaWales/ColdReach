from typing import Callable, List, Optional

from scout.errors import format_error_details
from scout.export import IncrementalCSVWriter, build_row
from scout.fetcher import WebsiteFetcher
from scout.models import Business, WebsiteCheckResult
from scout.scoring import evaluate_business
from scout.sources.osm import OSMSource

ProgressCallback = Callable[[int, int, str], None]


def dedupe_businesses(businesses: List[Business]) -> List[Business]:
    seen = set()
    deduped = []
    for b in businesses:
        key = (b.name.strip().lower(), b.address.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(b)
    return deduped


def find_businesses(branches: List[str], ort: str, radius: int) -> List[Business]:
    source = OSMSource()
    all_businesses = []
    for branche in branches:
        all_businesses.extend(source.get_businesses(branche, ort, radius))
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
