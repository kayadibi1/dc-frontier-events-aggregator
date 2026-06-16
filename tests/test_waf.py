import pytest

from aggregator.fetchers import waf


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


def _session_factory(attempts, behaviors):
    """behaviors: profile -> (status, text) tuple, or an Exception to raise."""
    class FakeSession:
        def __init__(self, impersonate, proxies=None):
            attempts.append(impersonate)
            self._b = behaviors[impersonate]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, timeout=None):
            if isinstance(self._b, Exception):
                raise self._b
            return _Resp(*self._b)

    return FakeSession


def test_exception_on_one_profile_falls_through(monkeypatch):
    # Cloudflare often rejects a scored fingerprint at the connection level;
    # the chain must survive that and try the next profile.
    from curl_cffi import requests as creq
    attempts = []
    monkeypatch.setattr(creq, "Session", _session_factory(attempts, {
        "safari": ConnectionError("reset"),
        "firefox": (200, "<html>ok</html>"),
        "chrome": (200, "x"),
    }))
    code, text = waf.curl_get("https://x.test/")
    assert code == 200 and "ok" in text
    assert attempts == ["safari", "firefox"]


def test_all_profiles_raising_reraises_last(monkeypatch):
    from curl_cffi import requests as creq
    attempts = []
    monkeypatch.setattr(creq, "Session", _session_factory(attempts, {
        p: ConnectionError(p) for p in ("safari", "firefox", "chrome")
    }))
    with pytest.raises(ConnectionError):
        waf.curl_get("https://x.test/")
    assert attempts == ["safari", "firefox", "chrome"]


def test_non_challenge_status_short_circuits(monkeypatch):
    # A 404/500 is the origin answering; a new fingerprint can't change it.
    from curl_cffi import requests as creq
    attempts = []
    monkeypatch.setattr(creq, "Session", _session_factory(attempts, {
        "safari": (404, "nope"), "firefox": (200, "x"), "chrome": (200, "x"),
    }))
    code, _ = waf.curl_get("https://x.test/")
    assert code == 404
    assert attempts == ["safari"]


def test_challenge_403_tries_every_profile(monkeypatch):
    from curl_cffi import requests as creq
    attempts = []
    monkeypatch.setattr(creq, "Session", _session_factory(attempts, {
        p: (403, "Just a moment...") for p in ("safari", "firefox", "chrome")
    }))
    code, _ = waf.curl_get("https://x.test/")
    assert code == 403
    assert attempts == ["safari", "firefox", "chrome"]


def test_redact_scrubs_url_credentials():
    assert waf._redact("http://user:pass@gw.example.com:8000") == "http://***@gw.example.com:8000"
    assert waf._redact("err socks5://u:p@h:1 boom") == "err socks5://***@h:1 boom"
