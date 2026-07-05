import datetime
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scout.config import CURRENT_YEAR_STALE_THRESHOLD, OLD_CMS_SIGNATURES

COPYRIGHT_RE = re.compile(r"(?:©|\(c\)|copyright)\s*[\-:]?\s*(\d{4})", re.IGNORECASE)
IMPRESSUM_RE = re.compile(r"impressum", re.IGNORECASE)


def check_no_https(final_url: Optional[str]) -> Tuple[bool, Optional[str]]:
    if not final_url:
        return True, None
    scheme = urlparse(final_url).scheme
    return scheme != "https", scheme


def check_no_viewport(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    tag = soup.find("meta", attrs={"name": re.compile("^viewport$", re.IGNORECASE)})
    return tag is None, (tag.get("content") if tag else None)


def check_old_copyright(soup: BeautifulSoup) -> Tuple[bool, Optional[int]]:
    text = soup.get_text(" ", strip=True)
    matches = [int(y) for y in COPYRIGHT_RE.findall(text)]
    if not matches:
        return False, None
    newest_year = max(matches)
    current_year = datetime.date.today().year
    is_old = newest_year < current_year - CURRENT_YEAR_STALE_THRESHOLD
    return is_old, newest_year


def check_no_impressum(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    for a in soup.find_all("a"):
        link_text = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if IMPRESSUM_RE.search(link_text) or IMPRESSUM_RE.search(href):
            return False, href
    return True, None


def check_old_cms(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    tag = soup.find("meta", attrs={"name": re.compile("^generator$", re.IGNORECASE)})
    generator = tag.get("content") if tag else None
    if not generator:
        return False, None
    generator_lower = generator.lower()
    for signature in OLD_CMS_SIGNATURES:
        if signature in generator_lower:
            return True, generator
    return False, generator


def check_frames_or_tables(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    if soup.find("frameset") is not None:
        return True, "frameset"
    table_count = len(soup.find_all("table"))
    if table_count >= 4:
        return True, f"{table_count} <table> tags"
    return False, None


def check_single_page(soup: BeautifulSoup, base_url: str) -> Tuple[bool, Optional[int]]:
    base_domain = urlparse(base_url).netloc
    internal_links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != base_domain:
            continue
        internal_links.add(parsed.path or "/")
    count = len(internal_links)
    return count < 3, count


def run_heuristics(html: str, final_url: str) -> Tuple[dict, dict]:
    soup = BeautifulSoup(html, "lxml")

    signals = {}
    raw_values = {}

    for key, (present, raw) in {
        "no_https": check_no_https(final_url),
        "no_viewport": check_no_viewport(soup),
        "old_copyright": check_old_copyright(soup),
        "no_impressum": check_no_impressum(soup),
        "old_cms": check_old_cms(soup),
        "frames_or_tables": check_frames_or_tables(soup),
        "single_page": check_single_page(soup, final_url),
    }.items():
        signals[key] = present
        raw_values[key] = raw

    return signals, raw_values
