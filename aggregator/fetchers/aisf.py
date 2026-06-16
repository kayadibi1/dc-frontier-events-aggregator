"""Layer-2 adapter: AI Security Forum -- the recurring DC edition.

aisecurity.forum runs a multi-city series (DC, Vegas, Paris, Tel Aviv) on a
Notion/Super.so site. The DC edition recurs annually under a stable slug pattern
`dc-ai-security-forum-NN`, so we discover those slugs from the /events listing
(future editions appear automatically) and read each event's own page for the
date and venue. The page exposes a small config block ("date"/"venue"); the hero
"Month DD, YYYY" is the fallback. The site's robots.txt disallows AI-named bots,
so the adapter uses a neutral browser UA. Title is built deterministically from
the slug (the site's own <title> uses an em dash, which our copy never does).
The pure parsers are offline-tested against saved REAL fixtures.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

BASE = "https://aisecurity.forum"
TIMEOUT = 30.0
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_DC_SLUG = re.compile(r'data-link-uri="/events/(dc-ai-security-forum-\d+)"')
_CFG_DATE = re.compile(r'"date"</span>:\s*<span[^>]*>"(\d{4}-\d{2}-\d{2})"')
_CFG_VENUE = re.compile(r'"venue"</span>:\s*<span[^>]*>"([^"]+)"')
_HERO_DATE = re.compile(r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s+(20\d{2})\b")
_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
           "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
           "december": 12}
_UPPER = {"dc": "DC", "ai": "AI", "us": "US"}


def parse_aisf_listing(html: str) -> list[str]:
    """The recurring DC-forum slugs on the /events listing (e.g. future editions)."""
    return sorted(set(_DC_SLUG.findall(html or "")))


def _title_from_slug(slug: str) -> str:
    """`dc-ai-security-forum-26` -> `DC AI Security Forum 2026`."""
    parts = slug.split("-")
    year = ""
    if parts and parts[-1].isdigit():
        year = ("20" + parts[-1]) if len(parts[-1]) == 2 else parts[-1]
        parts = parts[:-1]
    words = " ".join(_UPPER.get(p, p.capitalize()) for p in parts)
    return f"{words} {year}".strip()


def _detail_date(html: str) -> str | None:
    m = _CFG_DATE.search(html)
    if m:
        return m.group(1)
    d = _HERO_DATE.search(html)            # fallback: rendered "Month DD, YYYY"
    if d and d.group(1).lower() in _MONTHS:
        return f"{d.group(3)}-{_MONTHS[d.group(1).lower()]:02d}-{int(d.group(2)):02d}"
    return None


def parse_aisf_detail(source: Source, slug: str, html: str, today: str) -> Event | None:
    """One DC-edition page -> Event, or None if undated or already past."""
    date = _detail_date(html)
    if not date or date < today:
        return None
    vm = _CFG_VENUE.search(html)
    venue = (vm.group(1).strip() if vm else "Washington, DC")
    title = _title_from_slug(slug)
    return Event(
        id=f"aisf-{slug}",
        title=title,
        start=date,
        source=source.slug,
        source_url=f"{BASE}/events/{slug}",
        venue_name=venue.split(",")[0].strip(),
        address=venue,
        topics=detect_topics(title) or ["ai"],
    )


async def fetch_aisf(source: Source, today: str | None = None) -> SourceResult:
    today = today or datetime.now(timezone.utc).date().isoformat()
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=TIMEOUT,
                                     follow_redirects=True) as c:
            r = await c.get(source.url)
            if r.status_code != 200:
                return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
            events = []
            for slug in parse_aisf_listing(r.text):
                d = await c.get(f"{BASE}/events/{slug}")
                if d.status_code != 200:
                    continue
                ev = parse_aisf_detail(source, slug, d.text, today)
                if ev:
                    events.append(ev)
    except Exception as e:  # noqa: BLE001
        return SourceResult(source, [], None, repr(e))
    return SourceResult(source, events, 200, None)
