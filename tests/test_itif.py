import os

from aggregator.config import Source
from aggregator.fetchers.itif import parse_itif_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "itif_listing.html")
SRC = Source("itif", "ITIF", "itif", 2, True, url="https://itif.org/events/")


def _events():
    with open(FIX, encoding="utf-8") as f:
        return parse_itif_listing(SRC, f.read())


def test_parses_upcoming_events():
    assert len(_events()) >= 3


def test_events_well_formed():
    for e in _events():
        assert e.id.startswith("itif-")
        assert e.start and len(e.start) == 10            # ISO date
        assert e.source == "itif"
        assert e.source_url.startswith("https://itif.org/events/")
        assert e.organizer == "ITIF"


def test_unique_ids():
    evs = _events()
    assert len({e.id for e in evs}) == len(evs)


def test_url_constructed_from_date_and_slug():
    evs = _events()
    cloud = next((e for e in evs if "Cloud Sovereignty" in e.title), None)
    assert cloud is not None
    assert cloud.start == "2026-06-09"
    assert cloud.source_url == (
        "https://itif.org/events/2026/06/09/"
        "canadas-cloud-sovereignty-where-should-the-lines-fall/")


def test_future_conference_present():
    evs = _events()
    arvr = next((e for e in evs if "AR/VR Policy Conference" in e.title), None)
    assert arvr is not None
    assert arvr.start == "2026-09-24"
