"""Layer-2 adapter: Atlantic Council events.

Atlantic Council is behind a WAF that fingerprints plain httpx, so we fetch with
curl_cffi (Chrome TLS impersonation), like CSET. Its listing renders event cards
as `div.gta-event-embed--container`; each has an `a[href*='/event/']` detail link
(singular `/event/`), a heading title, and an inline date with a weekday prefix
("Public Event  Mon, June 1, 2026 • 2:45 pm ET ..."). Atlantic Council HQ is in DC
(1400 L St NW) -> dc_curated. Cards with no parseable date are skipped.
`parse_ac_listing` is pure (offline-tested against a saved fixture).
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

BASE = "https://www.atlanticcouncil.org"
TIMEOUT = 30.0
# Full-month date as it appears after the weekday prefix: "June 1, 2026".
_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _parse_date(text: str) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_ac_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for card in tree.css("div.gta-event-embed--container"):
        a = card.css_first("a[href*='/event/']")
        if a is None:
            continue
        href = (a.attributes.get("href") or "").split("?")[0]
        m = re.search(r"/event/([^/?#]+)", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue

        h = card.css_first("h1,h2,h3,h4,h5")
        title = _clean(h.text() if h else "")
        if not title:
            continue

        start = _parse_date(_clean(card.text(separator=" ")))
        if not start:
            continue
        seen.add(slug)

        url = href if href.startswith("http") else BASE + href
        events.append(
            Event(
                id=f"atlanticcouncil-{slug}",
                title=title,
                start=start,
                source=source.slug,
                source_url=url,
                organizer="Atlantic Council",
                topics=detect_topics(title),
            )
        )
    return events


def _curl_get(url: str) -> tuple[int, str]:
    from curl_cffi import requests as creq
    r = creq.Session(impersonate="chrome").get(url, timeout=TIMEOUT)
    return r.status_code, (r.text or "")


async def fetch_atlanticcouncil(source: Source) -> SourceResult:
    try:
        code, html = await asyncio.to_thread(_curl_get, source.url)
    except Exception as e:
        return SourceResult(source, [], None, repr(e))
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    return SourceResult(source, parse_ac_listing(source, html), code, None)
