import os

from aggregator.config import Source
from aggregator.fetchers.umdcs import parse_umdcs_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "umdcs_listing.html")
SRC = Source("umdcs", "University of Maryland (CS)", "umdcs", 3, True,
             url="https://www.cs.umd.edu/events")


def _events():
    with open(FIX, encoding="utf-8") as f:
        return parse_umdcs_listing(SRC, f.read())


def test_parses_real_events():
    assert len(_events()) >= 1


def test_events_well_formed():
    for e in _events():
        assert e.id.startswith("umdcs-")
        assert e.start[:4].isdigit() and len(e.start) >= 16   # tz-aware ISO datetime
        assert e.source == "umdcs"
        assert e.source_url.startswith("https://www.cs.umd.edu/event/")
        assert e.organizer == "University of Maryland"


def test_unique_ids():
    evs = _events()
    assert len({e.id for e in evs}) == len(evs)


def test_ai_agents_event_present_with_tz_start():
    evs = _events()
    ai = next((e for e in evs if "Principled AI Agents" in e.title), None)
    assert ai is not None
    assert ai.start == "2026-06-01T14:30:00-04:00"          # from the dc:date content attr
    assert "ai" in ai.topics
