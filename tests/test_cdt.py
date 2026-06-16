import os

from aggregator.config import Source
from aggregator.fetchers.cdt import parse_cdt_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "cdt_listing.html")
SRC = Source("cdt", "CDT", "cdt", 2, True, url="https://cdt.org/events/")


def _events():
    with open(FIX, encoding="utf-8") as f:
        return parse_cdt_listing(SRC, f.read())


def test_parses_real_events():
    assert len(_events()) >= 3


def test_events_well_formed():
    for e in _events():
        assert e.id.startswith("cdt-")
        assert e.start[:4].isdigit() and len(e.start) >= 10     # ISO date or datetime
        assert e.source == "cdt"
        assert e.source_url.startswith("https://cdt.org/event/")
        assert e.organizer == "CDT"


def test_unique_ids():
    evs = _events()
    assert len({e.id for e in evs}) == len(evs)


def test_chatbots_event_has_tz_aware_start():
    evs = _events()
    cb = next((e for e in evs if "Chatbots" in e.title), None)
    assert cb is not None
    assert cb.start == "2026-06-16T12:00:00-04:00"          # tz-aware from dt-start
    assert cb.id == "cdt-how-to-protect-kids-from-chatbots-without-bans"


class _FakeResp:
    def __init__(self, status: int, text: str):
        self.status_code, self.text = status, text


def _fake_session(attempts: list[str], responses: dict[str, _FakeResp]):
    class FakeSession:
        def __init__(self, impersonate: str):
            attempts.append(impersonate)
            self._prof = impersonate

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, timeout=None):
            return responses[self._prof]

    return FakeSession


def test_curl_get_falls_back_to_next_tls_profile_on_challenge(monkeypatch):
    # Cloudflare challenges per TLS fingerprint: chrome blocked, safari passes.
    from curl_cffi import requests as creq

    from aggregator.fetchers import cdt

    attempts: list[str] = []
    responses = {
        "safari": _FakeResp(403, "Just a moment..."),
        "firefox": _FakeResp(200, "<div class='h-event'>ok</div>"),
        "chrome": _FakeResp(403, "Just a moment..."),
    }
    monkeypatch.setattr(creq, "Session", _fake_session(attempts, responses))
    code, html = cdt._curl_get("https://cdt.org/events/")
    assert code == 200
    assert "h-event" in html
    assert attempts == ["safari", "firefox"]   # stopped at first 200


def test_curl_get_returns_last_status_when_all_profiles_blocked(monkeypatch):
    from curl_cffi import requests as creq

    from aggregator.fetchers import cdt

    attempts: list[str] = []
    responses = {p: _FakeResp(403, "Just a moment...") for p in ("safari", "firefox", "chrome")}
    monkeypatch.setattr(creq, "Session", _fake_session(attempts, responses))
    code, _ = cdt._curl_get("https://cdt.org/events/")
    assert code == 403
    assert attempts == ["safari", "firefox", "chrome"]   # tried every profile
