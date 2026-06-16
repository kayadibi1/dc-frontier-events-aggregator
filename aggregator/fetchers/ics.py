"""Generic iCal adapter (async httpx + icalendar).

Fetches any iCal URL and normalizes via parse_ics. Used by `kind="ics"` sources
(Meetup per-group, university Localist/Trumba feeds, Google calendars).
"""

from __future__ import annotations

import httpx

from ..config import Source
from ..normalize import parse_ics
from .base import SourceResult

TIMEOUT = 30.0
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


async def fetch_ics_url(source: Source, url: str, user_agent: str = DEFAULT_UA) -> SourceResult:
    headers = {"User-Agent": user_agent, "Accept": "text/calendar, */*"}
    async with httpx.AsyncClient(
        headers=headers, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
        if "BEGIN:VEVENT" not in r.text:
            return SourceResult(source, [], 200, None)  # fetched fine, just empty
        return SourceResult(source, parse_ics(source, r.text), 200, None)


async def fetch_ics(source: Source) -> SourceResult:
    return await fetch_ics_url(source, source.url)
