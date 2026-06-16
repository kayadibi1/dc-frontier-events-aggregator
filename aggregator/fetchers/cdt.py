"""Layer-2 adapter: CDT (Center for Democracy & Technology).

CDT is a DC tech-policy nonprofit (1401 K St NW) working on AI governance, kids'
online safety, privacy, and platform policy. Its events listing uses clean h-event
microformats: each `div.event-archive-item.h-event` has an `a.u-url` (detail link),
a `time.dt-start[datetime]` (a tz-aware ISO start), and an `h3.p-name` (title) -- so
no fragile date parsing. CDT detail pages carry little structured data, so topics
come from the title; off-topic / non-DC items (e.g. an EU-policy event in Brussels)
are dropped by the topic gate. httpx-accessible. `parse_cdt_listing` is pure
(offline-tested against a saved REAL fixture).
"""
from __future__ import annotations

import asyncio
import re

from selectolax.parser import HTMLParser

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

BASE = "https://cdt.org"
_WS = re.compile(r"\s+")
_SLUG = re.compile(r"/event/([^/?#]+)/?")


def _clean(t: str) -> str:
    return _WS.sub(" ", t or "").strip()


def parse_cdt_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for card in tree.css("div.h-event"):
        a = card.css_first("a.u-url") or card.css_first("a[href*='/event/']")
        if a is None:
            continue
        href = (a.attributes.get("href") or "").split("?")[0]
        m = _SLUG.search(href)
        if not m:
            continue
        slug = m.group(1)
        if not slug or slug in seen:
            continue
        h = card.css_first("h3.p-name") or card.css_first(".p-name") or card.css_first("h1,h2,h3,h4")
        title = _clean(h.text() if h else "")
        if not title:
            continue
        t = card.css_first("time.dt-start") or card.css_first("time[datetime]")
        start = (t.attributes.get("datetime") if t else "") or ""
        start = start.strip()
        if not (start[:4].isdigit() and len(start) >= 10):
            continue
        seen.add(slug)
        events.append(Event(
            id=f"cdt-{slug}",
            title=title,
            start=start,
            source=source.slug,
            source_url=href if href.startswith("http") else BASE + href,
            organizer="CDT",
            topics=detect_topics(title),
        ))
    return events


# Cloudflare challenges TLS fingerprints per site+IP -> shared profile-fallback
# helper (exception-tolerant per profile, first 200 wins).
from .waf import curl_get as _curl_get  # noqa: E402


async def fetch_cdt(source: Source) -> SourceResult:
    # CDT is behind Cloudflare (plain httpx 403s) -> curl_cffi with TLS-profile fallback.
    try:
        code, html = await asyncio.to_thread(_curl_get, source.url)
    except Exception as e:  # noqa: BLE001
        return SourceResult(source, [], None, repr(e))
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    return SourceResult(source, parse_cdt_listing(source, html), code, None)
