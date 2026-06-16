import os

from aggregator.config import Source
from aggregator.fetchers.nist import parse_nist_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "nist_listing.html")
SRC = Source("nist", "NIST", "nist", 2, False, url="https://www.nist.gov/news-events/events")


def _events():
    with open(FIX, encoding="utf-8") as f:
        return parse_nist_listing(SRC, f.read())


def test_parses_real_events():
    assert len(_events()) >= 5


def test_events_well_formed():
    for e in _events():
        assert e.id.startswith("nist-")
        assert e.start and len(e.start) == 10           # ISO date
        assert e.source == "nist"
        assert e.source_url.startswith("https://www.nist.gov/news-events/events/")
        assert e.organizer == "NIST"


def test_unique_ids():
    evs = _events()
    assert len({e.id for e in evs}) == len(evs)


def test_aims_ai_event_present_and_on_topic():
    evs = _events()
    aims = next((e for e in evs if "Artificial Intelligence for Materials" in e.title), None)
    assert aims is not None
    assert aims.start == "2026-06-16"
    assert "ai" in aims.topics
