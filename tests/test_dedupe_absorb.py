from aggregator.dedupe import dedupe
from aggregator.models import Event


def _ev(**kw):
    base = dict(id="x", title="t", start="2026-07-01", source="s")
    base.update(kw)
    return Event(**base)


def test_duplicate_survivor_gains_precise_time_and_venue():
    # Same event, two listings: first is date-only + no venue; second has a
    # tz-aware time + venue + speakers. The survivor should be the most complete.
    a = _ev(id="itif-x", title="How to Protect Kids From Chatbots", start="2026-07-01",
            source="itif")
    b = _ev(id="cdt-x", title="How to Protect Kids From Chatbots",
            start="2026-07-01T12:00:00-04:00", source="cdt",
            venue_name="CDT", address="1401 K St NW, Washington, DC",
            speakers=["Jane Doe"], description="A longer blurb about AI chatbots.")
    out, removed = dedupe([a, b])
    assert removed == 1
    surv = out[0]
    assert surv.start == "2026-07-01T12:00:00-04:00"      # upgraded to precise time
    assert surv.address == "1401 K St NW, Washington, DC"  # filled venue
    assert surv.speakers == ["Jane Doe"]
    assert "also_sources" in surv.raw and "cdt" in surv.raw["also_sources"]


def test_absorb_never_overwrites_existing_canonical_fields():
    a = _ev(id="a-1", title="Same Event Today", source="a",
            address="100 First St NW", description="Canonical blurb is rich.")
    b = _ev(id="b-1", title="Same Event Today", source="b",
            address="999 Other Ave", description="short")
    out, _ = dedupe([a, b])
    assert out[0].address == "100 First St NW"            # canonical address preserved
    assert out[0].description == "Canonical blurb is rich."


def test_absorb_merges_remote_and_watch_url():
    from aggregator.dedupe import _absorb_fields
    from aggregator.models import Event
    a = Event(id="a", title="AI Forum", start="2026-07-01", source="csis")
    b = Event(id="b", title="AI Forum", start="2026-07-01", source="brookings",
              raw={"remote": True, "watch_url": "https://zoom.us/j/1"})
    _absorb_fields(a, b)
    assert a.raw.get("remote") is True
    assert a.raw.get("watch_url") == "https://zoom.us/j/1"


def test_absorb_keeps_existing_watch_url():
    from aggregator.dedupe import _absorb_fields
    from aggregator.models import Event
    a = Event(id="a", title="t", start="2026-07-01", source="csis",
              raw={"watch_url": "https://a.example/keep"})
    b = Event(id="b", title="t", start="2026-07-01", source="x",
              raw={"remote": True, "watch_url": "https://b.example/other"})
    _absorb_fields(a, b)
    assert a.raw.get("watch_url") == "https://a.example/keep"
    assert a.raw.get("remote") is True


def test_absorb_replaces_invalid_watch_url_with_valid():
    from aggregator.dedupe import _absorb_fields
    from aggregator.models import Event
    a = Event(id="a", title="t", start="2026-07-01", source="csis",
              raw={"remote": True, "watch_url": "javascript:alert(1)"})
    b = Event(id="b", title="t", start="2026-07-01", source="x",
              raw={"remote": True, "watch_url": "https://zoom.us/j/1"})
    _absorb_fields(a, b)
    assert a.raw.get("watch_url") == "https://zoom.us/j/1"   # invalid replaced by valid
