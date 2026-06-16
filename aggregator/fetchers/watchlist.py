"""Curated marquee-event source for orgs that publish NO event feed (OpenAI, Anthropic).

Headless rendering can't capture what an org never posts, so a few hand-confirmed
entries (config.WATCHLIST_EVENTS) fill the highest-prestige gap. The adapter self-
prunes: a past-dated or dead-link entry is dropped each run, so it never shows stale
or fabricated events. All entries are DC by construction.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from .. import config
from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


async def _http_ok(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                     headers={"User-Agent": _UA}) as c:
            r = await c.get(url)
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:50]


async def fetch_watchlist(source: Source, link_ok=None, today: str | None = None) -> SourceResult:
    link_ok = link_ok or _http_ok
    today = today or datetime.now(timezone.utc).date().isoformat()
    out: list[Event] = []
    for ent in config.WATCHLIST_EVENTS:
        name = (ent.get("name") or "").strip()
        date = (ent.get("date") or "").strip()
        url = (ent.get("url") or "").strip()
        if not name or date[:10] < today:                # self-prune past entries
            continue
        if url and not await link_ok(url):               # drop dead links
            continue
        # The entry's venue is the FULL DC-metro address (events may sit in VA/MD
        # suburbs, not literally "Washington, DC") -- used verbatim, no suffix.
        venue = (ent.get("venue") or "").strip()
        topics = list(dict.fromkeys(detect_topics(name) + list(ent.get("topics", []))))
        out.append(Event(id=f"watchlist-{_slug(name)}", title=name, start=date,
                         source=source.slug, source_url=url, address=venue,
                         venue_name=venue.split(",")[0].strip(), topics=topics))
    return SourceResult(source, out, 200, None)
