from scout.config import NO_WEBSITE_SCORE, SCORE_WEIGHTS
from scout.errors import format_error_details
from scout.fetcher import WebsiteFetcher
from scout.heuristics import run_heuristics
from scout.models import Business, WebsiteCheckResult

# Fetch statuses that mean the URL is permanently unreachable (dead domain,
# 404, DNS failure, ...) -> treated like "keine Website" per PRD Abschnitt 7.
UNREACHABLE_STATUSES = {"DNS_ERROR", "HTTP_4XX", "HTTP_5XX", "CONNECTION_ERROR", "TIMEOUT"}


def compute_score(signals: dict) -> int:
    score = sum(SCORE_WEIGHTS[key] for key, present in signals.items() if present)
    return min(score, 100)


def evaluate_business(business: Business, fetcher: WebsiteFetcher) -> WebsiteCheckResult:
    try:
        if not business.website:
            return WebsiteCheckResult(
                status="NO_WEBSITE",
                score=NO_WEBSITE_SCORE,
                error_detail="Keine Website hinterlegt.",
            )

        fetch_result = fetcher.fetch(business.website)

        if fetch_result.status == "OK":
            signals, raw_values = run_heuristics(fetch_result.html, fetch_result.final_url)
            return WebsiteCheckResult(
                status="OK",
                signals=signals,
                raw_values=raw_values,
                score=compute_score(signals),
            )

        if fetch_result.status == "SSL_ERROR":
            signals = {"no_https": True}
            return WebsiteCheckResult(
                status="SSL_ERROR",
                signals=signals,
                raw_values={"no_https": "ssl_error", "detail": fetch_result.error_detail},
                score=compute_score(signals),
                error_detail=fetch_result.error_detail,
            )

        if fetch_result.status == "ROBOTS_DISALLOWED":
            return WebsiteCheckResult(
                status="ROBOTS_DISALLOWED",
                score=None,
                error_detail="Website blockiert den Zugriff über robots.txt.",
            )

        if fetch_result.status in UNREACHABLE_STATUSES:
            return WebsiteCheckResult(
                status=fetch_result.status,
                raw_values={"detail": fetch_result.error_detail},
                score=NO_WEBSITE_SCORE,
                error_detail=fetch_result.error_detail,
            )

        return WebsiteCheckResult(status=fetch_result.status, score=None, error_detail=fetch_result.error_detail)
    except Exception as exc:
        return WebsiteCheckResult(
            status="ERROR",
            score=None,
            error_detail=format_error_details(
                exc,
                context=f"Prüfung fehlgeschlagen für {business.name} ({business.website})",
            ),
        )
