"""Layer-3 adapter: Georgetown Law events (The Events Calendar REST).

law.georgetown.edu runs WordPress + The Events Calendar, which exposes a clean
JSON feed at /wp-json/tribe/events/v1/events (id/title/start_date/timezone/venue/
url). It is the WHOLE law-school calendar -- alumni receptions, moot court, and
some out-of-DC events (Bay Area receptions) -- so this source is NOT dc_curated
and is held to the strict TITLE topic gate: only events whose TITLE names an
AI/chip topic AND that read as DC survive the downstream filter (that is where
the Tech Institute's AI-governance events come through). `parse_gtlaw` is pure
(offline-tested against a saved REAL response fixture).
"""
from __future__ import annotations

import html as _html
from datetime import datetime, timezone

import httpx

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

TIMEOUT = 30.0
PER_PAGE = 50
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _venue_address(v: dict) -> tuple[str, str]:
    """(venue_name, full address) from a Tribe venue object; ('', '') if none."""
    if not isinstance(v, dict):
        return "", ""
    name = _html.unescape((v.get("venue") or "").strip())
    parts = [name] + [(v.get(k) or "").strip() for k in ("address", "city", "state", "zip")]
    return name, ", ".join(p for p in parts if p)


def parse_gtlaw(source: Source, payload: dict) -> list[Event]:
    """A Tribe events response -> Event list. Skips drafts and entries missing a
    title or start; topics come from the title (the strict gate re-checks them)."""
    out: list[Event] = []
    for e in (payload.get("events") or []):
        if not isinstance(e, dict):
            continue
        title = _html.unescape((e.get("title") or "").strip())
        start = (e.get("start_date") or "").strip()        # "YYYY-MM-DD HH:MM:SS", venue-local
        eid = e.get("id")
        if not title or not start or eid is None:
            continue
        if (e.get("status") or "publish") != "publish":
            continue
        name, addr = _venue_address(e.get("venue") or {})
        out.append(Event(
            id=f"gtlaw-{eid}",
            title=title,
            start=start.replace(" ", "T"),
            tz=(e.get("timezone") or "").strip() or None,
            source=source.slug,
            source_url=(e.get("url") or "").strip(),
            venue_name=name,
            address=addr,
            topics=detect_topics(title),
            raw={"virtual": bool(e.get("is_virtual"))},
        ))
    return out


async def fetch_gtlaw(source: Source, today: str | None = None) -> SourceResult:
    today = today or datetime.now(timezone.utc).date().isoformat()
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=TIMEOUT,
                                     follow_redirects=True) as c:
            r = await c.get(source.url, params={"per_page": PER_PAGE, "start_date": today})
        if r.status_code != 200:
            return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
        events = parse_gtlaw(source, r.json())
    except Exception as e:  # noqa: BLE001
        return SourceResult(source, [], None, repr(e))
    return SourceResult(source, events, 200, None)
