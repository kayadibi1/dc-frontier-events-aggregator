import os

from aggregator.config import Source
from aggregator.fetchers.atlanticcouncil import parse_ac_listing, _parse_date

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "atlanticcouncil_listing.html")
SRC = Source("atlanticcouncil", "Atlantic Council", "atlanticcouncil", 2, True,
             url="https://www.atlanticcouncil.org/events/")


def _events():
    with open(FIXTURE, encoding="utf-8") as f:
        return parse_ac_listing(SRC, f.read())


def test_parse_date_strips_weekday_prefix():
    assert _parse_date("Public Event Mon, June 1, 2026 • 2:45 pm ET") == "2026-06-01"
    assert _parse_date("Thu, June 4, 2026 • 10:00 am ET") == "2026-06-04"


def test_parse_date_none_when_absent():
    assert _parse_date("no date here") is None


def test_parses_event_cards_from_fixture():
    evs = _events()
    assert len(evs) >= 3


def test_all_events_well_formed():
    for e in _events():
        assert e.id.startswith("atlanticcouncil-")
        assert e.title
        assert e.start and len(e.start) == 10
        assert e.source == "atlanticcouncil"
        assert e.source_url.startswith("https://www.atlanticcouncil.org/event/")
        assert e.organizer == "Atlantic Council"


def test_unique_ids():
    ids = [e.id for e in _events()]
    assert len(ids) == len(set(ids))


def test_real_ai_events_present_and_on_topic():
    evs = _events()
    titles = [e.title for e in evs]
    assert any("AI era" in t for t in titles), f"got: {titles}"
    ai = next(e for e in evs if "AI era" in e.title)
    assert "ai" in ai.topics
    # the AI/bio event too
    assert any("Pandora" in t for t in titles)


def test_nav_and_menu_links_excluded():
    # menu links like /events/galas-and-flagships/ must not become events
    ids = {e.id for e in _events()}
    assert not any("galas" in i for i in ids)
