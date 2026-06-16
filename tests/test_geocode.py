from aggregator.geocode import _norm, geocode_events
from aggregator.models import Event


def _ev(id, address=None, lat=None, lng=None):
    return Event(id=id, title=id, start="2026-06-01", source="x",
                 address=address, lat=lat, lng=lng)


def test_geocode_sets_coords_caches_and_skips(tmp_path):
    cache = tmp_path / "gc.json"
    calls = []

    def fake_query(addr):
        calls.append(addr)
        return (38.9, -77.04) if "1616" in addr else None

    evs = [
        _ev("a", "CSIS, 1616 Rhode Island Ave NW, Washington, DC 20036"),
        _ev("b", "CSIS, 1616 Rhode Island Ave NW, Washington, DC 20036"),  # same -> cache hit
        _ev("c", "Nowhere Plaza"),                                          # geocoder miss
        _ev("d"),                                                           # no address -> skip
        _ev("e", "123 Foo St", lat=1.0, lng=2.0),                          # already pinned -> skip
    ]
    n = geocode_events(evs, cache_path=str(cache), query=fake_query, sleep=lambda *_: None)

    assert n == 2                                   # only a, b get coords
    assert (evs[0].lat, evs[0].lng) == (38.9, -77.04)
    assert (evs[1].lat, evs[1].lng) == (38.9, -77.04)   # from cache, no 2nd live call
    assert evs[2].lat is None                       # miss stays pin-less
    assert evs[3].lat is None                       # no address
    assert (evs[4].lat, evs[4].lng) == (1.0, 2.0)   # feed GEO untouched
    # one live call per UNIQUE address only (the duplicate hit the cache)
    assert calls == ["CSIS, 1616 Rhode Island Ave NW, Washington, DC 20036", "Nowhere Plaza"]


def test_geocode_reuses_persisted_cache(tmp_path):
    cache = tmp_path / "gc.json"
    geocode_events([_ev("a", "Same Place")], cache_path=str(cache),
                   query=lambda a: (10.0, 20.0), sleep=lambda *_: None)

    def must_not_query(addr):
        raise AssertionError("should have used the cached result, not queried")

    e2 = [_ev("b", "Same Place")]
    n = geocode_events(e2, cache_path=str(cache), query=must_not_query, sleep=lambda *_: None)
    assert n == 1 and (e2[0].lat, e2[0].lng) == (10.0, 20.0)


def test_geocode_miss_is_cached_not_requeried(tmp_path):
    cache = tmp_path / "gc.json"
    geocode_events([_ev("a", "Unmappable")], cache_path=str(cache),
                   query=lambda a: None, sleep=lambda *_: None)

    def must_not_query(addr):
        raise AssertionError("a cached miss must not be re-queried")

    geocode_events([_ev("b", "Unmappable")], cache_path=str(cache),
                   query=must_not_query, sleep=lambda *_: None)


def test_geocode_network_error_not_cached_and_retried(tmp_path):
    cache = tmp_path / "gc.json"

    def boom(addr):
        raise OSError("network down")

    e1 = [_ev("a", "Flaky Place")]
    n = geocode_events(e1, cache_path=str(cache), query=boom, sleep=lambda *_: None)
    assert n == 0 and e1[0].lat is None
    # a transient failure must NOT be cached as a miss -> a later build retries it
    e2 = [_ev("b", "Flaky Place")]
    n = geocode_events(e2, cache_path=str(cache), query=lambda a: (5.0, 6.0),
                       sleep=lambda *_: None)
    assert n == 1 and (e2[0].lat, e2[0].lng) == (5.0, 6.0)


def test_geocode_retries_street_core_when_full_misses(tmp_path):
    cache = tmp_path / "gc.json"
    seen = []

    def q(addr):
        seen.append(addr)
        return (38.9, -77.04) if addr == "1775 Massachusetts Ave NW Washington, D.C. 20036" else None

    ev = [_ev("a", "The Brookings Institution Saul Auditorium 1775 Massachusetts Ave NW Washington, D.C. 20036")]
    n = geocode_events(ev, cache_path=str(cache), query=q, sleep=lambda *_: None)
    assert n == 1 and (ev[0].lat, ev[0].lng) == (38.9, -77.04)
    assert seen[0].startswith("The Brookings")                       # full tried first
    assert "1775 Massachusetts Ave NW Washington, D.C. 20036" in seen  # then the street core


def test_geocode_drops_leading_org_prefix(tmp_path):
    cache = tmp_path / "gc.json"

    def q(addr):
        return (38.9, -77.07) if addr == "Georgetown University, Washington, DC" else None

    ev = [_ev("a", "CSET, Georgetown University, Washington, DC")]
    n = geocode_events(ev, cache_path=str(cache), query=q, sleep=lambda *_: None)
    assert n == 1 and ev[0].lat == 38.9


def test_geocode_strips_trailing_room(tmp_path):
    cache = tmp_path / "gc.json"

    def q(addr):
        return (38.9, -77.02) if addr == "Martin Luther King Jr. Memorial Library" else None

    ev = [_ev("a", "Martin Luther King Jr. Memorial Library, Room 401-E")]
    n = geocode_events(ev, cache_path=str(cache), query=q, sleep=lambda *_: None)
    assert n == 1 and ev[0].lat == 38.9


def test_nominatim_query_constrains_to_dc(monkeypatch):
    import json as _json

    import aggregator.geocode as g
    captured = {}

    class _Resp:
        def __init__(self, data):
            self._d = _json.dumps(data).encode()

        def read(self, *a):
            return self._d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _Resp([{"lat": "38.9", "lon": "-77.0"}])

    monkeypatch.setattr(g.urllib.request, "urlopen", fake_urlopen)
    assert g.nominatim_query("CSIS, Washington DC") == (38.9, -77.0)
    # constrained to the DC metro so an ambiguous variant can't pin the wrong place
    assert "countrycodes=us" in captured["url"]
    assert "bounded=1" in captured["url"]
    assert "viewbox=" in captured["url"]


def test_norm_collapses_whitespace_and_case():
    assert _norm("  CSIS,   1616  Rhode  Island ") == "csis, 1616 rhode island"


def test_scrub_far_geo_nulls_out_of_bbox_pins():
    from aggregator.geocode import scrub_far_geo
    evs = [
        _ev("dc", lat=38.9, lng=-77.04),         # inside DC metro bbox -> kept
        _ev("pacific", lat=-8.52, lng=179.20),   # junk feed GEO (S. Pacific) -> nulled
        _ev("none"),                             # no coords at all -> untouched
    ]
    n = scrub_far_geo(evs)
    assert n == 1
    assert (evs[0].lat, evs[0].lng) == (38.9, -77.04)    # DC pin untouched
    assert evs[1].lat is None and evs[1].lng is None      # ocean pin scrubbed
    assert evs[2].lat is None and evs[2].lng is None      # no-coords untouched
