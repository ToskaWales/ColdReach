import os

USER_AGENT = "ColdReachScoutBot/0.1 (+contact: local scouting tool, respects robots.txt)"
REQUEST_TIMEOUT = 9  # seconds
MIN_DELAY_PER_DOMAIN = 1.0  # seconds, rate limiting

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Fallback mirrors used if the main instance rate-limits us (HTTP 429) or is down.
OVERPASS_MIRRORS = [
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")

SCORE_WEIGHTS = {
    "no_https": 25,
    "no_viewport": 20,
    "old_copyright": 15,
    "no_impressum": 15,
    "old_cms": 10,
    "frames_or_tables": 10,
    "single_page": 5,
}

NO_WEBSITE_SCORE = 100
CURRENT_YEAR_STALE_THRESHOLD = 2  # copyright year older than (current year - N) counts as stale

# Known outdated CMS/generator signatures (substring match, case-insensitive)
OLD_CMS_SIGNATURES = [
    "typo3 4.",
    "typo3 6.",
    "wordpress 3.",
    "wordpress 4.",
    "joomla! 1.",
    "joomla! 2.",
    "jimdo",
    "wix.com website builder",
    "frontpage",
    "microsoft frontpage",
]
