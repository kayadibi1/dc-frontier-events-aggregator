"""Layer-2 adapter: ITIF (Information Technology and Innovation Foundation).

ITIF is a DC tech-policy think tank (AI, semiconductors, compute, data, platform
policy) -- exactly the policy tier GOAL.md targets. Its events page is a Next.js
app whose full event list is embedded as JSON in the __NEXT_DATA__ script
(props.pageProps.data.upcomingEvents), each with title/date/slug -- authoritative
and robust (no card-scraping). The detail URL is /events/YYYY/MM/DD/<slug>/. ITIF
is behind a WAF, so fetch via curl_cffi (Chrome impersonation); detail pages carry
og:description (enriched via enrich.py). ITIF HQ is in DC (700 K St NW) -> dc_curated.
`parse_itif_listing` is pure (offline-tested against a saved REAL fixture).
"""
from __future__ import annotations

import asyncio
import json
import re

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

BASE = "https://itif.org"
TIMEOUT = 30.0
_NEXT = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _slug_of(it: dict) -> str:
    s = it.get("slug")
    if isinstance(s, dict):
        return (s.get("current") or "").strip()
    return (s or "").strip() if isinstance(s, str) else ""


def _event_url(date: str, slug: str, external) -> str:
    if isinstance(external, str) and external.startswith("http"):
        return external
    y, m, d = date.split("-")
    return f"{BASE}/events/{y}/{m}/{d}/{slug}/"


def parse_itif_listing(source: Source, html: str) -> list[Event]:
    m = _NEXT.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        items = data["props"]["pageProps"]["data"]["upcomingEvents"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    events: list[Event] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        date = (it.get("date") or "")[:10]
        slug = _slug_of(it)
        if not title or not _ISO_DATE.match(date) or not slug or slug in seen:
            continue
        seen.add(slug)
        # summary/excerpt are Sanity Portable-Text block arrays, not plain text;
        # leave description empty and let enrich.py pull the detail page's
        # og:description (and recompute topics from it for this curated source).
        events.append(Event(
            id=f"itif-{slug}",
            title=title,
            start=date,
            source=source.slug,
            source_url=_event_url(date, slug, it.get("externalURL")),
            organizer="ITIF",
            topics=detect_topics(title),
        ))
    return events


def _curl_get(url: str) -> tuple[int, str]:
    from curl_cffi import requests as creq
    r = creq.Session(impersonate="chrome").get(url, timeout=TIMEOUT)
    return r.status_code, (r.text or "")


async def fetch_itif(source: Source) -> SourceResult:
    try:
        code, html = await asyncio.to_thread(_curl_get, source.url)
    except Exception as e:  # noqa: BLE001
        return SourceResult(source, [], None, repr(e))
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    return SourceResult(source, parse_itif_listing(source, html), code, None)
