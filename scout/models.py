from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Business:
    name: str
    address: str
    phone: Optional[str]
    website: Optional[str]
    source: str  # "osm" | "google_places"
    raw_id: str  # ID from source system, used for dedup/re-runs


@dataclass
class FetchResult:
    status: str  # OK | TIMEOUT | DNS_ERROR | HTTP_4XX | HTTP_5XX | SSL_ERROR | CONNECTION_ERROR | ROBOTS_DISALLOWED
    html: Optional[str] = None
    headers: dict = field(default_factory=dict)
    final_url: Optional[str] = None
    error_detail: Optional[str] = None


@dataclass
class WebsiteCheckResult:
    status: str  # OK | TIMEOUT | DNS_ERROR | HTTP_4XX | HTTP_5XX | SSL_ERROR | ROBOTS_DISALLOWED | NO_WEBSITE | ERROR
    signals: dict = field(default_factory=dict)  # signal_name -> True/False
    raw_values: dict = field(default_factory=dict)  # signal_name -> raw evidence (e.g. detected year)
    score: int = 0
    error_detail: Optional[str] = None
