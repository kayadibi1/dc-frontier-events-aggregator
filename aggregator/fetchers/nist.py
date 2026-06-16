"""Layer-2 adapter: NIST events.

NIST serves event cards as links to `/news-events/events/YYYY/MM/<slug>` with the
title as the link text and an abbreviated date ("Jun 16 2026") in the card. We use
curl_cffi (Chrome impersonation) since plain httpx can hit the WAF. NIST campuses
span Gaithersburg MD (DC metro) AND Boulder CO, so this source is **NOT**
dc_curated -- an event is kept only via a real DC venue (enriched from the detail
page, which carries schema.org Event JSON-LD) or DC text, so a Boulder event can't
slip through. A card without a parseable day is skipped (never fabricate a date).
`parse_nist_listing` is pure (offline-tested against a saved REAL fixture).
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

BASE = "https://www.nist.gov"
TIMEOUT = 30.0
_HREF = re.compile(r"^/news-events/events/\d{4}/\d{2}/[^/?#]+")
_DATE = re.compile(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4})\b")
_WS = re.compile(r"\s+")


def _clean(t: str) -> str:
    return _WS.sub(" ", t or "").strip()


def _card_date(node) -> str | None:
    """The 'Mon DD YYYY' in the anchor's nearest ancestor that carries one."""
    cur = node
    for _ in range(5):
        if cur is None:
            break
        m = _DATE.search(_clean(cur.text()))
        if m:
            try:
                return datetime.strptime(" ".join(m.groups()), "%b %d %Y").date().isoformat()
            except ValueError:
                return None
        cur = cur.parent
    return None


def parse_nist_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for a in tree.css("a[href*='/news-events/events/']"):
        href = (a.attributes.get("href") or "").split("?")[0]
        if not _HREF.match(href):
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if not slug or slug in seen:
            continue
        title = re.sub(r"\s*Continues?$", "", _clean(a.text()))
        if not title or len(title) < 6:
            continue
        start = _card_date(a)
        if not start:                      # no day shown -> don't invent one
            continue
        seen.add(slug)
        events.append(Event(
            id=f"nist-{slug}",
            title=title,
            start=start,
            source=source.slug,
            source_url=BASE + href,
            organizer="NIST",
            topics=detect_topics(title),
        ))
    return events


def _curl_get(url: str) -> tuple[int, str]:
    from curl_cffi import requests as creq
    r = creq.Session(impersonate="chrome").get(url, timeout=TIMEOUT)
    return r.status_code, (r.text or "")


async def fetch_nist(source: Source) -> SourceResult:
    try:
        code, html = await asyncio.to_thread(_curl_get, source.url)
    except Exception as e:
        return SourceResult(source, [], None, repr(e))
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    return SourceResult(source, parse_nist_listing(source, html), code, None)
