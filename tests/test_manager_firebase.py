from scout import manager


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("request failed")

    def json(self):
        return self._payload


def test_upsert_lead_uses_firebase_when_configured(monkeypatch):
    calls = []

    def fake_request(method, url, params=None, json=None, timeout=10):
        calls.append((method, url, params, json))
        if method == "POST":
            return FakeResponse({"name": "lead-123"})
        if method == "GET":
            return FakeResponse({})
        return FakeResponse({})

    monkeypatch.setenv("FIREBASE_DATABASE_URL", "https://example.firebaseio.com")
    monkeypatch.setenv("FIREBASE_DATABASE_SECRET", "secret")
    monkeypatch.setattr(manager.requests, "request", fake_request)

    lead = manager.upsert_lead(lead_data={"company_name": "Acme", "stage": "New"})

    assert lead["id"] == "lead-123"
    assert lead["company_name"] == "Acme"
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/leads.json")
