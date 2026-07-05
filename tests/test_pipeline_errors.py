from scout.models import Business
from scout.pipeline import evaluate_businesses


class DummyFetcher:
    def fetch(self, url):
        raise RuntimeError("boom")


def test_evaluate_businesses_reports_exception_details(monkeypatch):
    business = Business(
        name="Test GmbH",
        address="Musterstr. 1",
        phone=None,
        website="https://example.com",
        source="osm",
        raw_id="1",
    )

    monkeypatch.setattr("scout.pipeline.WebsiteFetcher", lambda: DummyFetcher())

    rows = evaluate_businesses([business])

    assert len(rows) == 1
    assert rows[0]["status"] == "ERROR"
    assert "RuntimeError" in rows[0]["status_detail"]
    assert "boom" in rows[0]["status_detail"]
