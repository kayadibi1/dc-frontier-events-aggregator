from aggregator.models import Event
from aggregator.provenance import marker, notes, prov_clear, prov_get, prov_set


def _ev(**kw):
    kw.setdefault("title", "x"); kw.setdefault("source", "csis"); kw.setdefault("start", "2026-06-10")
    return Event(id="e1", **kw)


def test_set_get_clear():
    ev = _ev()
    prov_set(ev, "location", "hq")
    assert prov_get(ev, "location") == "hq"
    prov_clear(ev, "location")
    assert prov_get(ev, "location") is None


def test_marker_only_for_addressed_hq():
    ev = _ev(address="CNAS, 1701 Pennsylvania Ave NW, Washington, DC 20006")
    prov_set(ev, "location", "hq")
    assert marker(ev) == "📍approx"
    ev.address = ""
    assert marker(ev) == ""


def test_marker_empty_for_high_confidence():
    ev = _ev(address="123 Real St")
    prov_set(ev, "location", "scraped")
    assert marker(ev) == ""


def test_notes_lists_all_derived_defensively():
    ev = _ev(address="HQ addr", start="2026-06-10T10:00:00", speakers=["A B"])
    prov_set(ev, "location", "hq"); prov_set(ev, "time", "assumed_et"); prov_set(ev, "speakers", "extracted")
    n = notes(ev)
    assert "location approximate (host venue)" in n
    assert "time assumed ET" in n
    assert "speakers auto-extracted" in n
    ev.speakers = []
    assert "speakers auto-extracted" not in notes(ev)
