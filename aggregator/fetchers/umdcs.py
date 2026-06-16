"""Layer-3 adapter: University of Maryland — Computer Science (College Park, DC metro).

UMD CS / UMIACS run a strong AI/ML/robotics/NLP program; the department's Drupal
events listing carries an authoritative tz-aware start in a
`span[property='dc:date'].date-display-start` `content` attribute, with the event
title in a sibling `/event/YYYY/MM/<slug>` link. College Park (lat 38.99) is inside
the DC bbox, so this is dc_curated; held to STRICT_TITLE topic matching like the
other campus feeds (a desc-only keyword on a whole-department page is boilerplate).
httpx-accessible. `parse_umdcs_listing` is pure (offline-tested against a saved REAL
fixture). Academic calendars are seasonal -- expect a quiet summer, a full fall.
"""
from __future__ import annotations

import re

import httpx
from selectolax.parser import HTMLParser

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

BASE = "https://www.cs.umd.edu"
TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_WS = re.compile(r"\s+")
_SLUG = re.compile(r"/event/20\d\d/\d\d/([^/?#]+)")


def _clean(t: str) -> str:
    return _WS.sub(" ", t or "").strip()


def parse_umdcs_listing(source: Source, html: str) -> list[Event]:
    tree = HTMLParser(html)
    events: list[Event] = []
    seen: set[str] = set()
    for a in tree.css("a[href*='/event/']"):
        href = (a.attributes.get("href") or "").split("?")[0]
        m = _SLUG.search(href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        title = _clean(a.text())
        if not title or len(title) < 6:
            continue
        # The row's authoritative tz-aware start lives in the dc:date content attr.
        start = None
        node = a
        for _ in range(6):
            node = node.parent
            if node is None:
                break
            ds = (node.css_first("span.date-display-start[content]")
                  or node.css_first("[class*='date-display-start'][content]"))
            if ds and ds.attributes.get("content"):
                start = ds.attributes["content"].strip()
                break
        if not start or not start[:4].isdigit():
            continue
        seen.add(slug)
        url = href if href.startswith("http") else BASE + href
        events.append(Event(
            id=f"umdcs-{slug}",
            title=title,
            start=start,
            source=source.slug,
            source_url=url,
            organizer="University of Maryland",
            topics=detect_topics(title),
        ))
    return events


async def fetch_umdcs(source: Source) -> SourceResult:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT,
                                 follow_redirects=True) as client:
        r = await client.get(source.url)
        if r.status_code != 200:
            return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
        return SourceResult(source, parse_umdcs_listing(source, r.text), r.status_code, None)
