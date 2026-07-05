from scout.heuristics import run_heuristics
from scout.scoring import compute_score

MODERN_HTML = """
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="WordPress 6.7.5">
</head>
<body>
<p>&copy; 2026 Musterfirma</p>
<a href="/impressum">Impressum</a>
<a href="/leistungen">Leistungen</a>
<a href="/kontakt">Kontakt</a>
</body></html>
"""

OLD_HTML = """
<html><head><meta name="generator" content="Wordpress 3.5.1"></head>
<frameset rows="100,*"><frame src="a.html"><frame src="b.html"></frameset>
<body>
<table><tr><td><table><tr><td><table><tr><td><table><tr><td>
&copy; 2014 Musterfirma GmbH.
<a href="kontakt.html">Kontakt</a>
</td></tr></table></td></tr></table></td></tr></table></td></tr></table>
</body></html>
"""


def test_modern_site_has_no_signals():
    signals, _ = run_heuristics(MODERN_HTML, "https://modernfirma.de/")
    assert not any(signals.values())
    assert compute_score(signals) == 0


def test_old_site_triggers_all_signals():
    signals, raw = run_heuristics(OLD_HTML, "http://alte-firma.de/")
    assert signals["no_https"] is True
    assert signals["no_viewport"] is True
    assert signals["old_copyright"] is True
    assert signals["no_impressum"] is True
    assert signals["old_cms"] is True
    assert signals["frames_or_tables"] is True
    assert signals["single_page"] is True
    assert raw["old_copyright"] == 2014
    assert compute_score(signals) == 100


def test_score_caps_at_100():
    all_true = {k: True for k in [
        "no_https", "no_viewport", "old_copyright", "no_impressum",
        "old_cms", "frames_or_tables", "single_page",
    ]}
    assert compute_score(all_true) == 100
