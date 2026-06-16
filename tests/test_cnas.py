import os

from aggregator.config import Source
from aggregator.fetchers.cnas import parse_cnas_listing, _parse_date

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cnas_listing.html")
SRC = Source("cnas", "CNAS", "cnas", 2, True, url="https://www.cnas.org/events")


def _events():
    with open(FIXTURE, encoding="utf-8") as f:
        return parse_cnas_listing(SRC, f.read())


def test_parse_date_abbrev_month():
    assert _parse_date("Event Defense Jun 16, 2026") == "2026-06-16"
    assert _parse_date("... May 26, 2026 ...") == "2026-05-26"


def test_parse_date_none_when_absent():
    assert _parse_date("no date here") is None


def test_parses_event_cards_from_fixture():
    evs = _events()
    # the live fixture had 18 figure.photo-listing__item cards, all dated
    assert len(evs) >= 12


def test_all_events_well_formed():
    for e in _events():
        assert e.id.startswith("cnas-")
        assert e.title and not e.title.lower().startswith("event")
        assert e.start and len(e.start) == 10           # ISO date
        assert e.source == "cnas"
        assert e.source_url.startswith("https://www.cnas.org/events/")
        assert e.organizer == "CNAS"


def test_unique_ids():
    evs = _events()
    ids = [e.id for e in evs]
    assert len(ids) == len(set(ids))


def test_nav_and_pagination_links_excluded():
    evs = _events()
    slugs = {e.id for e in evs}
    # pagination link /events/p2 must not become an event
    assert "cnas-p2" not in slugs
    # the megamenu nav link (national security conference) is outside events-landing
    titles = " ".join(e.title for e in evs)
    assert "Next Up" not in titles


def test_cnas_hq_address_is_correct():
    # CNAS HQ is the map-pin fallback for CNAS events that don't scrape a venue.
    # Real address per cnas.org/contact is 1701 Pennsylvania Ave NW (1899 was wrong).
    from aggregator.config import SOURCE_HQ
    assert "1701 Pennsylvania Ave NW" in SOURCE_HQ["cnas"]
    assert "1899" not in SOURCE_HQ["cnas"]


def test_real_ai_policy_events_present_and_on_topic():
    evs = _events()
    titles = [e.title for e in evs]
    # the marquee AI events from the live slate
    assert any("AI Competition" in t for t in titles)
    assert any("Pentagon and Silicon Valley" in t for t in titles)
    # and they detect an AI/tech topic from the title
    ai = [e for e in evs if any(not t.startswith("big:") for t in e.topics)]
    assert ai, "expected at least one on-topic CNAS event"
    pentagon = next(e for e in evs if "Pentagon and Silicon Valley" in e.title)
    assert "ai" in pentagon.topics
