"""Layer-1 adapter: Luma JSON APIs (per-calendar get-items + DC discover feed).

Replaced the per-calendar ICS subscription 2026-06-09: the JSON carries
structured coordinates, the venue IANA timezone, a virtual flag, and a direct
event URL that the ICS lacked (its DESCRIPTION is boilerplate), and the same
shape powers the city-wide discover source that catches DC events on calendars
we never curated. Unofficial API: any breakage quarantines cleanly and the ICS
fetcher is one git-revert away. `period=future` only -- past events archive on
the run after they happen (store + archive.ics retain them).
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from ..provenance import prov_set
from .base import SourceResult

USER_AGENT = "dc-frontier-events/0.4 (+https://lu.ma)"
TIMEOUT = 30.0
API = "https://api.lu.ma"
PAGE_LIMIT = 50
MAX_PAGES = 10      # safety valve; both DC feeds are 1-2 pages today


def _local_iso(utc_iso, tzname):
    """'2026-06-10T22:00:00.000Z' + IANA tz -> tz-aware local ISO (or None).
    Per-entry tolerant: one bad date/tz from the city-wide discover firehose
    must degrade that entry, never crash (and quarantine) the whole source."""
    if not utc_iso:
        return None
    try:
        dt = datetime.fromisoformat(str(utc_iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if tzname:
        try:
            dt = dt.astimezone(ZoneInfo(tzname))
        except (KeyError, ValueError):
            pass     # unknown/malformed tz -> keep UTC rather than drop the event
    return dt.isoformat()


def event_from_json(source: Source, entry: dict) -> Event | None:
    """Luma JSON event (get-items / discover entry) -> normalized Event.
    Returns None for unusable entries (no id/title/start), like parse_ics."""
    ev = entry.get("event") or {}
    eid = ev.get("api_id") or ""
    title = (ev.get("name") or "").strip()
    tzname = ev.get("timezone")
    start = _local_iso(ev.get("start_at"), tzname)
    if not eid or not title or not start:
        return None

    geo = ev.get("geo_address_info") or {}
    address = geo.get("full_address") or geo.get("address") or geo.get("city_state") or ""
    coord = ev.get("coordinate") or {}
    lat, lng = coord.get("latitude"), coord.get("longitude")

    out = Event(
        id=eid,
        title=title,
        start=start,
        end=_local_iso(ev.get("end_at"), tzname),
        tz=tzname,
        source=source.slug,
        source_url=f"https://lu.ma/{ev['url']}" if ev.get("url") else "",
        venue_name=address.split(",")[0].strip() if address else "",
        address=address,
        lat=float(lat) if lat is not None else None,
        lng=float(lng) if lng is not None else None,
        organizer=source.name,
        topics=detect_topics(title),
        raw={"calendar": source.name},
    )
    if ev.get("location_type") == "online":
        out.raw["virtual"] = True
    if address:
        prov_set(out, "location", "structured")
    return out


async def _get_json(url: str) -> tuple[int, dict]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT,
                                 follow_redirects=True) as client:
        r = await client.get(url)
        return r.status_code, (r.json() if r.status_code == 200 else {})


async def _fetch_pages(source: Source, base_url: str, get_json) -> SourceResult:
    events: list[Event] = []
    cursor = None
    for _ in range(MAX_PAGES):
        url = base_url + (f"&pagination_cursor={quote(cursor, safe='')}" if cursor else "")
        code, data = await get_json(url)
        if code != 200:
            return SourceResult(source, [], code, f"HTTP {code}")
        for entry in data.get("entries") or []:
            ev = event_from_json(source, entry)
            if ev is not None:
                events.append(ev)
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            break
    return SourceResult(source, events, 200, None)


async def fetch_luma(source: Source, get_json=_get_json) -> SourceResult:
    url = (f"{API}/calendar/get-items?calendar_api_id={source.cal_id}"
           f"&period=future&pagination_limit={PAGE_LIMIT}")
    return await _fetch_pages(source, url, get_json)


async def fetch_luma_discover(source: Source, get_json=_get_json) -> SourceResult:
    url = (f"{API}/discover/get-paginated-events?discover_place_api_id={source.cal_id}"
           f"&period=future&pagination_limit={PAGE_LIMIT}")
    return await _fetch_pages(source, url, get_json)
