"""Layer-2 adapter: Council on Strategic Risks (events RSS + detail pages).

CoSR posts events as WordPress posts; the RSS `category/events/feed/` is a clean
discovery surface, but its `pubDate` is the PUBLISH date, not the event date
(e.g. a webinar published May 22 is held June 4). The event date is bolded in the
post body as `<strong>Weekday, Month DD, YYYY</strong>`, which is a reliable,
publish-date-distinct signal. We use date-only (the body states a time RANGE like
"12:00 to 1:00 pm ET" -- parsing it risks grabbing the end time). CoSR runs global
events (London/virtual), so it is NOT dc_curated; a window of body text becomes
the description so the normal DC filter can drop non-DC items. Posts without the
bolded date (analyses, report launches) are skipped -- never fabricated. The pure
parsers are offline-tested against saved REAL fixtures.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

TIMEOUT = 30.0
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Every weekday ends in "day" (Monday..Sunday), so this matches the bolded event
# date without enumerating names, and is distinct from the byline publish date.
_BOLD_DATE = re.compile(r"<strong>\s*[A-Z][a-z]+day,\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(20\d{2})")
_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
           "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
           "december": 12}


def parse_cosr_rss(xml_text: str) -> list[tuple[str, str]]:
    """(title, link) for every <item> in the events RSS feed."""
    out: list[tuple[str, str]] = []
    root = ET.fromstring(xml_text)
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if title and link:
            out.append((title, link))
    return out


def parse_cosr_detail(source: Source, title: str, link: str, html: str,
                      today: str) -> Event | None:
    """A post -> Event using the bolded event date; None if undated or past."""
    m = _BOLD_DATE.search(html or "")
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    date = f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    if date < today:
        return None
    url = link.split("?", 1)[0]
    slug = [p for p in url.split("/") if p][-1]
    scope = html[m.start():m.end() + 300]
    window = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", scope)).strip()
    virtual = bool(re.search(r"\b(webinar|virtual|online|zoom)\b", scope, re.I))
    return Event(
        id=f"cosr-{slug}",
        title=title.strip(),
        start=date,
        source=source.slug,
        source_url=url,
        description=window,
        topics=detect_topics(title),
        raw={"virtual": virtual},
    )


async def fetch_cosr(source: Source, today: str | None = None) -> SourceResult:
    today = today or datetime.now(timezone.utc).date().isoformat()
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=TIMEOUT,
                                     follow_redirects=True) as c:
            r = await c.get(source.url)
            if r.status_code != 200:
                return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
            events = []
            for title, link in parse_cosr_rss(r.text):
                d = await c.get(link)
                if d.status_code != 200:
                    continue
                ev = parse_cosr_detail(source, title, link, d.text, today)
                if ev:
                    events.append(ev)
    except Exception as e:  # noqa: BLE001
        return SourceResult(source, [], None, repr(e))
    return SourceResult(source, events, 200, None)
