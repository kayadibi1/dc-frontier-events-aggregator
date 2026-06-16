"""Layer-2 adapter: CSET (Georgetown) events.

CSET's events listing sits behind a WAF that 403s plain httpx (TLS fingerprint),
so we fetch with curl_cffi impersonating Chrome. The listing cards carry
everything we need (title, date, location, excerpt), so no per-event detail
fetch is required. Parsing is split out as `parse_cset_listing` for offline tests.
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

TIMEOUT = 30.0
_MONTH_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _parse_date(text: str) -> str | None:
    m = _MONTH_DATE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _slug(href: str) -> str:
    return href.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


def parse_cset_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for top in tree.css("div.teaser__top"):
        a = top.css_first("h4 a") or top.css_first("a[href*='/event/']")
        if a is None:
            continue
        href = (a.attributes.get("href") or "").split("?")[0]
        if "/event/" not in href or href in seen:
            continue

        date_node = top.css_first(".teaser__dates")
        start = _parse_date(date_node.text()) if date_node else None
        if not start:
            continue  # an event with no parseable date is unusable
        seen.add(href)

        title = _clean(a.text())
        loc_node = top.css_first(".teaser__location")
        loc = _clean(loc_node.text()) if loc_node else ""
        virtual = "online" in loc.lower()
        address = "" if virtual else loc

        # Excerpt: only when the card is a single-event container (guard against
        # grabbing the whole grid's text if .teaser__top sits directly in it).
        desc = ""
        card = top.parent
        if card is not None and len(card.css(".teaser__dates")) == 1:
            full = _clean(card.text())
            if loc and loc in full:
                desc = full.split(loc, 1)[1].strip()

        events.append(
            Event(
                id=f"cset-{_slug(href)}",
                title=title,
                start=start,
                source=source.slug,
                source_url=href,
                description=desc,
                venue_name="" if virtual else loc.split(",")[0],
                address=address,
                organizer="CSET",
                topics=detect_topics(f"{title} {desc} {loc}"),
                raw={"location": loc, "virtual": virtual},
            )
        )
    return events


async def fetch_cset(source: Source) -> SourceResult:
    def _go() -> tuple[int, str]:
        from curl_cffi import requests as creq  # browser TLS impersonation

        s = creq.Session(impersonate="chrome")
        r = s.get(source.url, timeout=TIMEOUT)
        return r.status_code, r.text

    status, html = await asyncio.to_thread(_go)
    if status != 200:
        return SourceResult(source, [], status, f"HTTP {status}")
    return SourceResult(source, parse_cset_listing(source, html), status, None)
