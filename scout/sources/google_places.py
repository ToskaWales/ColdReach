import time
from typing import List, Optional

import requests

from scout.config import REQUEST_TIMEOUT, USER_AGENT
from scout.models import Business
from scout.sources.base import BusinessSource
from scout.sources.osm import geocode_location

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
MAX_PAGES = 3  # Google returns up to 20 results per page, 3 pages max (60 results)


class GooglePlacesSource(BusinessSource):
    """Supplements OSM coverage with Google's much more complete (but paid)
    business listings, including websites/phone numbers OSM often lacks."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_businesses(self, query: str, location: str, radius: int) -> List[Business]:
        lat, lon = geocode_location(location)

        results = []
        page_token: Optional[str] = None
        for _ in range(MAX_PAGES):
            if page_token:
                time.sleep(2)  # next_page_token isn't valid until a short delay has passed
                params = {"pagetoken": page_token, "key": self.api_key}
            else:
                params = {
                    "query": f"{query} in {location}",
                    "location": f"{lat},{lon}",
                    "radius": radius,
                    "key": self.api_key,
                }

            try:
                resp = requests.get(
                    TEXT_SEARCH_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise RuntimeError(f"Google Places Suche fehlgeschlagen: {exc}") from exc

            data = resp.json()
            status = data.get("status")
            if status not in ("OK", "ZERO_RESULTS"):
                raise RuntimeError(f"Google Places Fehler: {status} - {data.get('error_message', '')}")

            results.extend(data.get("results", []))
            page_token = data.get("next_page_token")
            if not page_token:
                break

        businesses = []
        for place in results:
            place_id = place.get("place_id")
            if not place_id:
                continue
            details = self._fetch_details(place_id)
            businesses.append(
                Business(
                    name=place.get("name") or details.get("name") or "",
                    address=details.get("formatted_address") or place.get("formatted_address") or "",
                    phone=details.get("formatted_phone_number"),
                    website=details.get("website"),
                    source="google_places",
                    raw_id=place_id,
                )
            )
        return businesses

    def _fetch_details(self, place_id: str) -> dict:
        params = {
            "place_id": place_id,
            "fields": "name,formatted_address,formatted_phone_number,website",
            "key": self.api_key,
        }
        try:
            resp = requests.get(
                DETAILS_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException:
            return {}
        data = resp.json()
        if data.get("status") != "OK":
            return {}
        return data.get("result", {})
