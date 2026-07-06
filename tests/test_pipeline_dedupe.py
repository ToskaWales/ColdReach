from scout.models import Business
from scout.pipeline import dedupe_businesses


def _business(**overrides):
    defaults = dict(
        name="Café Central",
        address="Marktplatz 1, 95444 Bayreuth",
        phone=None,
        website=None,
        source="osm",
        raw_id="node/1",
    )
    defaults.update(overrides)
    return Business(**defaults)


def test_same_source_same_raw_id_is_deduped():
    a = _business()
    b = _business()
    result = dedupe_businesses([a, b])
    assert len(result) == 1


def test_cross_source_duplicate_merges_and_fills_missing_fields():
    osm = _business(source="osm", raw_id="node/1", website=None, phone=None)
    google = _business(source="google_places", raw_id="abc123", website="https://cafe-central.de", phone="0921 123456")

    result = dedupe_businesses([osm, google])

    assert len(result) == 1
    merged = result[0]
    assert merged.website == "https://cafe-central.de"
    assert merged.phone == "0921 123456"


def test_distinct_chain_branches_without_address_are_not_dropped():
    branch_a = _business(name="Rossmann", address="", source="osm", raw_id="node/1")
    branch_b = _business(name="Rossmann", address="", source="osm", raw_id="node/2")

    result = dedupe_businesses([branch_a, branch_b])

    assert len(result) == 2
