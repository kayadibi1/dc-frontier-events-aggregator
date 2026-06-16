import asyncio
import json
import os

from aggregator.config import Source
from aggregator.fetchers.luma import event_from_json, fetch_luma, fetch_luma_discover
from aggregator.provenance import prov_get

SRC = Source("DC2", "DC Data & AI Events", "luma", 1, True, cal_id="cal-x")

ENTRY = {
    "event": {
        "api_id": "evt-uAm3FAMHeYgxVNx",
        "name": "Side Projects: AI Meetup",
        "start_at": "2026-06-10T22:00:00.000Z",
        "end_at": "2026-06-11T00:00:00.000Z",
        "timezone": "America/New_York",
        "location_type": "offline",
        "url": "thq3hut1",
        "geo_address_info": {
            "address": "2112 Pennsylvania Ave NW",
            "city_state": "Washington, District of Columbia",
            "full_address": "2112 Pennsylvania Ave NW, Washington, DC 20037, USA",
        },
        "coordinate": {"longitude": -77.0479011, "latitude": 38.9014337},
    }
}


def test_maps_core_fields():
    ev = event_from_json(SRC, ENTRY)
    assert ev.id == "evt-uAm3FAMHeYgxVNx"          # same id the ICS UID normalized to
    assert ev.title == "Side Projects: AI Meetup"
    assert ev.source == "DC2"
    assert ev.source_url == "https://lu.ma/thq3hut1"
    assert ev.organizer == "DC Data & AI Events"
    assert "ai" in ev.topics


def test_start_is_venue_local_tz_aware():
    ev = event_from_json(SRC, ENTRY)
    assert ev.start == "2026-06-10T18:00:00-04:00"   # 22:00 UTC -> 18:00 ET
    assert ev.end == "2026-06-10T20:00:00-04:00"
    assert ev.tz == "America/New_York"


def test_structured_location_and_coords():
    ev = event_from_json(SRC, ENTRY)
    assert ev.address == "2112 Pennsylvania Ave NW, Washington, DC 20037, USA"
    assert ev.venue_name == "2112 Pennsylvania Ave NW"
    assert ev.lat == 38.9014337 and ev.lng == -77.0479011
    assert prov_get(ev, "location") == "structured"
    assert not ev.raw.get("virtual")


def test_online_event_is_virtual_with_no_address():
    entry = json.loads(json.dumps(ENTRY))
    entry["event"]["location_type"] = "online"
    entry["event"]["geo_address_info"] = None
    entry["event"]["coordinate"] = None
    ev = event_from_json(SRC, entry)
    assert ev.raw.get("virtual") is True
    assert ev.address == "" and ev.lat is None


def test_unusable_entry_returns_none():
    assert event_from_json(SRC, {"event": {"api_id": "evt-x"}}) is None      # no title/start
    assert event_from_json(SRC, {}) is None


def test_real_fixture_parses():
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "luma_get_items.json")
    with open(fix, encoding="utf-8") as f:
        entries = json.load(f)["entries"]
    evs = [event_from_json(SRC, e) for e in entries]
    evs = [e for e in evs if e is not None]
    assert len(evs) >= 1
    for e in evs:
        assert e.id.startswith("evt-")
        assert "T" in e.start and ("+" in e.start or "-" in e.start[10:])    # tz-aware


DISC = Source("luma-dc", "Luma DC (city-wide)", "luma-discover", 1, False,
              cal_id="discplace-AANPgOymN6bqFn8")


def _pages(responses):
    """get_json fake: pops canned (status, data) per call, records URLs."""
    calls = []

    async def get_json(url):
        calls.append(url)
        return responses.pop(0)

    return get_json, calls


def test_fetch_luma_paginates_until_has_more_false():
    p1 = {"entries": [ENTRY], "has_more": True, "next_cursor": "cur+1="}
    p2 = {"entries": [ENTRY], "has_more": False, "next_cursor": None}
    get_json, calls = _pages([(200, p1), (200, p2)])
    res = asyncio.run(fetch_luma(SRC, get_json=get_json))
    assert res.ok and len(res.events) == 2
    assert "calendar_api_id=cal-x" in calls[0] and "period=future" in calls[0]
    assert "pagination_cursor=cur%2B1%3D" in calls[1]          # cursor URL-quoted


def test_fetch_luma_http_error_quarantines():
    get_json, _ = _pages([(404, {})])
    res = asyncio.run(fetch_luma(SRC, get_json=get_json))
    assert not res.ok and res.status == 404 and res.reason == "HTTP 404"


def test_fetch_luma_empty_is_clean_empty():
    get_json, _ = _pages([(200, {"entries": [], "has_more": False})])
    res = asyncio.run(fetch_luma(SRC, get_json=get_json))
    assert res.error is None and res.status == 200 and res.events == []


def test_fetch_discover_hits_place_endpoint():
    get_json, calls = _pages([(200, {"entries": [ENTRY], "has_more": False})])
    res = asyncio.run(fetch_luma_discover(DISC, get_json=get_json))
    assert res.ok and len(res.events) == 1
    assert "discover/get-paginated-events" in calls[0]
    assert "discover_place_api_id=discplace-AANPgOymN6bqFn8" in calls[0]


def test_luma_dc_discover_source_registered():
    from aggregator.config import SOURCES
    from aggregator.fetchers import ADAPTERS
    dc = next(s for s in SOURCES if s.slug == "luma-dc")
    assert dc.kind == "luma-discover"
    assert dc.cal_id == "discplace-AANPgOymN6bqFn8"
    assert dc.dc_curated is False                  # strict filter applies
    assert ADAPTERS["luma-discover"] is fetch_luma_discover


def test_malformed_start_skipped_not_fatal():
    bad = json.loads(json.dumps(ENTRY))
    bad["event"]["start_at"] = "not-a-date"
    assert event_from_json(SRC, bad) is None       # skip the entry, not the source


def test_malformed_timezone_falls_back_to_utc():
    odd = json.loads(json.dumps(ENTRY))
    odd["event"]["timezone"] = "America/../New_York"   # ZoneInfo raises ValueError
    ev = event_from_json(SRC, odd)
    assert ev is not None
    assert ev.start == "2026-06-10T22:00:00+00:00"     # kept, in UTC


def test_fetch_discover_requests_future_only():
    get_json, calls = _pages([(200, {"entries": [], "has_more": False})])
    asyncio.run(fetch_luma_discover(DISC, get_json=get_json))
    assert "period=future" in calls[0]
