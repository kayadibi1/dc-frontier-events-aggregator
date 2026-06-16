"""Layer-2 adapter: National Academies of Sciences, Engineering, and Medicine.

NASEM runs many high-signal AI / computing / semiconductor studies and workshops
(CSTB, the Intelligence Community Studies Board, chip-workforce roundtables), often
at its DC venues (Keck Center, NAS building on Constitution Ave NW) -- but ALSO at
the Beckman Center in Irvine CA and elsewhere, so this source is NOT dc_curated:
an event is kept only via a real DC venue/text, so a California workshop can't slip
in. Listing cards are `a[href*='/event/<id>']` with an `h2` title and a date string
("June 3 - 4, 2026"). curl_cffi (Chrome impersonation). Detail pages carry
og:description (enriched + topic-recomputed). `parse_nasem_listing` is pure
(offline-tested against a saved REAL fixture).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime

from selectolax.parser import HTMLParser

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

BASE = "https://www.nationalacademies.org"
TIMEOUT = 30.0
_WS = re.compile(r"\s+")
_EVENT_ID = re.compile(r"/event/(\d+)")
_MONTH_DAY = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2})\b")
_YEAR = re.compile(r"\b(20\d{2})\b")


def _clean(t: str) -> str:
    return _WS.sub(" ", t or "").strip()


def _parse_date(text: str) -> str | None:
    """First 'Month DD ... YYYY' in the card -> the start date. Handles single
    ('June 3, 2026'), same-month range ('June 3 - 4, 2026') and cross-month range
    ('June 30 - July 1, 2026') by taking the FIRST month/day and the year."""
    md = _MONTH_DAY.search(text)
    if not md:
        return None
    # Take the year that FOLLOWS the month/day, not the first 4-digit year in the
    # card -- a year in the TITLE ("The 2030 Project") must not override the date.
    yr = _YEAR.search(text, md.end())
    if not yr:
        return None
    try:
        return datetime.strptime(
            f"{md.group(1)} {md.group(2)} {yr.group(1)}", "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def parse_nasem_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for a in tree.css("a[href*='/event/']"):
        href = (a.attributes.get("href") or "").split("?")[0]
        m = _EVENT_ID.search(href)
        if not m:
            continue
        eid = m.group(1)
        if eid in seen:
            continue
        h = a.css_first("h2") or a.css_first("h1,h3")
        if h is None:
            continue
        title = _clean(h.text())
        if not title or len(title) < 6:
            continue
        start = _parse_date(_clean(a.text()))
        if not start:
            continue
        seen.add(eid)
        url = href if href.startswith("http") else BASE + href
        events.append(Event(
            id=f"nasem-{eid}",
            title=title,
            start=start,
            source=source.slug,
            source_url=url,
            organizer="National Academies",
            topics=detect_topics(title),
        ))
    return events


def _curl_get(url: str) -> tuple[int, str]:
    from curl_cffi import requests as creq
    r = creq.Session(impersonate="chrome").get(url, timeout=TIMEOUT)
    return r.status_code, (r.text or "")


async def fetch_nasem(source: Source) -> SourceResult:
    try:
        code, html = await asyncio.to_thread(_curl_get, source.url)
    except Exception as e:  # noqa: BLE001
        return SourceResult(source, [], None, repr(e))
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    return SourceResult(source, parse_nasem_listing(source, html), code, None)
