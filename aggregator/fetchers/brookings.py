"""Layer-2 adapter: Brookings Institution events.

Brookings is httpx-accessible (no WAF). Its listing renders `article` cards; the
title is in a heading, the date is free text in the card ("June 10 2026", or with
a comma), and the event link is an `a[href*='/events/']` (Brookings-proper;
sub-brand cards like hamiltonproject.org use `/event/` singular and are excluded).
Brookings HQ is in DC (1775 Massachusetts Ave NW) -> dc_curated. A card with no
parseable date is skipped. `parse_brookings_listing` is pure for offline testing.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx
from selectolax.parser import HTMLParser

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

BASE = "https://www.brookings.edu"
TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2},? \d{4})")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _parse_date(text: str) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(",", "")          # "June 10 2026" and "July 15, 2026"
    try:
        return datetime.strptime(raw, "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def parse_brookings_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for card in tree.css("article"):
        a = card.css_first("a[href*='/events/']")
        if a is None:
            continue
        href = (a.attributes.get("href") or "").split("?")[0]
        if "/events/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if slug in seen:
            continue

        h = card.css_first("h1,h2,h3,h4")
        title = _clean(h.text() if h else a.text())
        if not title:
            continue

        start = _parse_date(_clean(card.text(separator=" ")))
        if not start:
            continue
        seen.add(slug)

        events.append(
            Event(
                id=f"brookings-{slug}",
                title=title,
                start=start,
                source=source.slug,
                source_url=href if href.startswith("http") else BASE + href,
                organizer="Brookings",
                topics=detect_topics(title),
            )
        )
    return events


async def fetch_brookings(source: Source) -> SourceResult:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(
        headers=headers, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        r = await client.get(source.url)
        if r.status_code != 200:
            return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
        return SourceResult(source, parse_brookings_listing(source, r.text), r.status_code, None)
