import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from scout.config import MIN_DELAY_PER_DOMAIN, REQUEST_TIMEOUT, USER_AGENT
from scout.models import FetchResult


def _domain_of(url: str) -> str:
    return urlparse(url).netloc


class WebsiteFetcher:
    """Fetches websites politely: respects robots.txt, rate-limits per domain,
    and caches results so businesses sharing a domain (e.g. franchise branches)
    are only fetched once per run."""

    def __init__(self):
        self._robots_cache: dict = {}
        self._last_request_at: dict = {}
        self._result_cache: dict = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _is_allowed(self, url: str) -> bool:
        domain = _domain_of(url)
        if domain not in self._robots_cache:
            parser = urllib.robotparser.RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
            try:
                resp = self.session.get(robots_url, timeout=REQUEST_TIMEOUT)
                if resp.status_code >= 400:
                    parser.parse([])  # no robots.txt => allow all
                else:
                    parser.parse(resp.text.splitlines())
            except requests.RequestException:
                parser.parse([])  # unreachable robots.txt => allow all
            self._robots_cache[domain] = parser
        return self._robots_cache[domain].can_fetch(USER_AGENT, url)

    def _respect_rate_limit(self, domain: str):
        last = self._last_request_at.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < MIN_DELAY_PER_DOMAIN:
                time.sleep(MIN_DELAY_PER_DOMAIN - elapsed)
        self._last_request_at[domain] = time.monotonic()

    def fetch(self, url: str) -> FetchResult:
        if not url:
            return FetchResult(status="DNS_ERROR", error_detail="empty url")

        domain = _domain_of(url)
        if domain in self._result_cache:
            return self._result_cache[domain]

        if not self._is_allowed(url):
            result = FetchResult(status="ROBOTS_DISALLOWED")
            self._result_cache[domain] = result
            return result

        self._respect_rate_limit(domain)

        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        except requests.exceptions.SSLError as e:
            result = FetchResult(status="SSL_ERROR", error_detail=str(e))
        except requests.exceptions.Timeout as e:
            result = FetchResult(status="TIMEOUT", error_detail=str(e))
        except requests.exceptions.ConnectionError as e:
            msg = str(e).lower()
            if "name or service not known" in msg or "getaddrinfo failed" in msg or "nodename nor servname" in msg:
                result = FetchResult(status="DNS_ERROR", error_detail=str(e))
            else:
                result = FetchResult(status="CONNECTION_ERROR", error_detail=str(e))
        except requests.RequestException as e:
            result = FetchResult(status="CONNECTION_ERROR", error_detail=str(e))
        else:
            if 400 <= resp.status_code < 500:
                status = "HTTP_4XX"
            elif resp.status_code >= 500:
                status = "HTTP_5XX"
            else:
                status = "OK"
            result = FetchResult(
                status=status,
                html=resp.text if status == "OK" else None,
                headers=dict(resp.headers),
                final_url=resp.url,
            )

        self._result_cache[domain] = result
        return result
