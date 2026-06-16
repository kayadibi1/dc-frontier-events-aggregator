"""Layer-2 adapter: CSIS events (async httpx + selectolax).

CSIS is httpx-accessible (no WAF block). The listing renders cards as
`article.ts-card-event-*` with an <h3> title, a date+time line
("May 29, 2026 - 9:30 - 10:00 am EDT"), and a "/programs/" host link. CSIS HQ
is in DC -> dc_curated, so its events are kept by curation and the topic filter
extracts the AI/chip ones. Parsing is split out for offline tests.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import httpx
from selectolax.parser import HTMLParser

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from ..provenance import prov_set
from .base import SourceResult

BASE = "https://www.csis.org"
TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_MONTH_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*(?:[–-]\s*\d{1,2}:\d{2}\s*)?(am|pm)\s*(E[SD]T)?", re.I)
_OFFSET = {"EDT": "-04:00", "EST": "-05:00"}
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _us_eastern(d: date) -> tuple[str, str]:
    """US/Eastern label+offset for a date: EDT (-04:00) during DST (2nd Sunday of
    March .. 1st Sunday of November), else EST (-05:00). CSIS is always Eastern, so
    a time with no explicit zone (or a bare "ET") defaults here, not tz-naive."""
    mar1 = date(d.year, 3, 1).weekday()                      # Mon=0 .. Sun=6
    dst_start = date(d.year, 3, 1 + ((6 - mar1) % 7) + 7)    # 2nd Sunday of March
    nov1 = date(d.year, 11, 1).weekday()
    dst_end = date(d.year, 11, 1 + ((6 - nov1) % 7))         # 1st Sunday of November
    return ("EDT", "-04:00") if dst_start <= d < dst_end else ("EST", "-05:00")


def _parse_when(text: str) -> tuple[str | None, str | None]:
    dm = _MONTH_DATE.search(text)
    if not dm:
        return None, None
    try:
        d = datetime.strptime(dm.group(1), "%B %d, %Y").date()
    except ValueError:
        return None, None
    tm = _TIME.search(text)
    if not tm:
        return d.isoformat(), None
    hh, mm = int(tm.group(1)), int(tm.group(2))
    ap = tm.group(3).lower()
    tz = (tm.group(4) or "").upper()
    if ap == "pm" and hh != 12:
        hh += 12
    if ap == "am" and hh == 12:
        hh = 0
    if tz in _OFFSET:
        off = _OFFSET[tz]
    else:                       # bare "ET" or no zone -> CSIS is always Eastern
        tz, off = _us_eastern(d)
    return f"{d.isoformat()}T{hh:02d}:{mm:02d}:00{off}", tz


def parse_csis_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for card in tree.css("article[class*='ts-card-event']"):
        ev_a = card.css_first("a[href*='/events/']")
        if ev_a is None:
            continue
        href = (ev_a.attributes.get("href") or "").split("?")[0]
        if "/events/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if slug in seen:
            continue

        h3 = card.css_first("h3")
        title = _clean(h3.text()) if h3 else _clean(ev_a.text())
        if not title:
            continue

        text = _clean(card.text())
        start, tz = _parse_when(text)
        if not start:
            continue
        seen.add(slug)

        prog_a = card.css_first("a[href*='/programs/']")
        program = _clean(prog_a.text()) if prog_a else ""

        ev = Event(
            id=f"csis-{slug}",
            title=title,
            start=start,
            tz=tz,
            source=source.slug,
            source_url=href if href.startswith("http") else BASE + href,
            organizer=program,
            topics=detect_topics(f"{title} {program}"),
            raw={"program": program},
        )
        if "T" in start:
            prov_set(ev, "time", "explicit" if re.search(r"\bE[SD]T\b", text, re.I) else "assumed_et")
        events.append(ev)
    return events


async def fetch_csis(source: Source) -> SourceResult:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(
        headers=headers, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        r = await client.get(source.url)
        if r.status_code != 200:
            return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
        return SourceResult(source, parse_csis_listing(source, r.text), r.status_code, None)
