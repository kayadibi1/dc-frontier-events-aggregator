"""Layer-2 adapter: CNAS (Center for a New American Security) events.

CNAS is httpx-accessible (no WAF). Its listing has an awkward DOM -- no `article`
cards and the page is full of nav/megamenu `/events/` links -- but the real event
cards are `figure.photo-listing__item` inside `div.events-landing`. Each card has a
heading (title), an `a[href*='/events/']` detail link, and a date in abbreviated
form ("Jun 16, 2026"). CNAS HQ is in DC (1701 Pennsylvania Ave NW) -> dc_curated.
Cards with no parseable date are skipped. `parse_cnas_listing` is pure (offline-tested).
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

BASE = "https://www.cnas.org"
TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Abbreviated-month date as it appears in the card text: "Jun 16, 2026".
_DATE = re.compile(r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4})")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _parse_date(text: str) -> str | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "")
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_cnas_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    # Scope to the listing region so nav/megamenu /events/ links are excluded.
    root = tree.css_first("div.events-landing") or tree
    events: list[Event] = []
    seen: set[str] = set()
    for card in root.css("figure.photo-listing__item"):
        a = card.css_first("a[href*='/events/']")
        if a is None:
            continue
        href = (a.attributes.get("href") or "").split("?")[0]
        m = re.search(r"/events/([^/?#]+)/?$", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen or re.fullmatch(r"p\d+", slug):  # skip pagination /events/p2
            continue

        h = card.css_first("h1,h2,h3,h4,h5")
        title = _clean(h.text() if h else a.text())
        if not title or title.lower() in ("event", "next up"):
            continue

        start = _parse_date(_clean(card.text(separator=" ")))
        if not start:
            continue
        seen.add(slug)

        url = href if href.startswith("http") else BASE + href
        events.append(
            Event(
                id=f"cnas-{slug}",
                title=title,
                start=start,
                source=source.slug,
                source_url=url,
                organizer="CNAS",
                topics=detect_topics(title),
            )
        )
    return events


async def fetch_cnas(source: Source) -> SourceResult:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(
        headers=headers, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        r = await client.get(source.url)
        if r.status_code != 200:
            return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
        return SourceResult(source, parse_cnas_listing(source, r.text), r.status_code, None)
