import json
import os

from aggregator.config import Source
from aggregator.fetchers.gtlaw import parse_gtlaw

SRC = Source("gtlaw", "Georgetown Law (Tech Institute)", "gtlaw", 3, False,
             url="https://www.law.georgetown.edu/wp-json/tribe/events/v1/events")


def _load():
    p = os.path.join(os.path.dirname(__file__), "fixtures", "gtlaw_events.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_parses_tribe_events():
    evs = parse_gtlaw(SRC, _load())
    assert len(evs) == 3
    bay = next(e for e in evs if "Bay Area" in e.title)
    assert bay.start == "2025-01-09T18:00:00"          # space -> T, local wall time
    assert bay.tz == "UTC-8"                            # venue tz passed through
    assert "San Francisco" in bay.address               # venue address built
    assert bay.source == "gtlaw"
    assert bay.id == "gtlaw-" + str(bay.id.split("-", 1)[1])
    assert bay.source_url.startswith("https://www.law.georgetown.edu/event/")
    assert any(e.tz == "America/New_York" for e in evs)  # a DC-tz event present


def test_ai_title_tagged_with_dc_venue():
    payload = {"events": [{
        "id": 99, "title": "Building an AI-Ready Bar", "status": "publish",
        "start_date": "2026-09-10 12:00:00", "timezone": "America/New_York",
        "url": "https://www.law.georgetown.edu/event/ai-ready-bar/",
        "venue": {"venue": "Hart Auditorium", "address": "600 New Jersey Ave NW",
                  "city": "Washington", "state": "DC", "zip": "20001"},
    }]}
    ev = parse_gtlaw(SRC, payload)[0]
    assert "ai" in ev.topics
    assert ev.venue_name == "Hart Auditorium"
    assert "Washington" in ev.address and "20001" in ev.address


def test_skips_titleless_or_dateless():
    payload = {"events": [
        {"id": 1, "title": "", "start_date": "2026-09-10 12:00:00"},
        {"id": 2, "title": "No date here", "start_date": ""},
    ]}
    assert parse_gtlaw(SRC, payload) == []
