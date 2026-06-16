"""Layered event extraction from rendered HTML (the jsrender engine).

Given a page's final HTML (from render.py), pull events the most-stable way first:
  1. schema.org Event JSON-LD  (structured.extract_all_events) -- authoritative.
  2. Next.js __NEXT_DATA__ / embedded JSON arrays of event-shaped dicts (like ITIF).
  3. heuristic cards -- a repeating block with a title + a <time datetime>/date + a
     detail link, optionally guided by per-source CSS hints in config.JSRENDER_HINTS.
The first layer that yields events wins. Pure + offline-testable. Location is carried
through (JSON-LD location) so the DC filter can drop a global page's non-DC events.
"""
from __future__ import annotations

import json
import re

from selectolax.parser import HTMLParser

from .config import JSRENDER_HINTS
from .models import Event
from .normalize import detect_topics
from .structured import extract_all_events

_NEXT = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_WS = re.compile(r"\s+")
_ORIGIN = re.compile(r"(https?://[^/]+)")
_TITLE_KEYS = ("title", "name", "heading")
_DATE_KEYS = ("date", "startDate", "start", "eventDate", "start_date", "datetime", "when")


def _clean(t: str) -> str:
    return _WS.sub(" ", t or "").strip()


def _slug(url: str) -> str:
    m = re.search(r"/([^/?#]+)/?(?:[?#]|$)", url or "")
    return m.group(1) if m else ""


def _mk(source, title, start, url, address="", venue="", desc="") -> Event | None:
    title = _clean(title)
    start = (start or "").strip()
    if not title or len(title) < 5 or not start[:4].isdigit():
        return None
    sid = _slug(url) or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    return Event(id=f"{source.slug}-{sid}", title=title, start=start, source=source.slug,
                 source_url=url or "", address=address, venue_name=venue,
                 topics=detect_topics(f"{title} {desc}"))


def _from_jsonld(source, html: str) -> list[Event]:
    out = []
    for e in extract_all_events(html):
        ev = _mk(source, e.get("name"), e.get("start"), e.get("url", ""),
                 address=e.get("address", ""), venue=e.get("venue_name", ""))
        if ev:
            out.append(ev)
    return out


def _from_nextdata(source, html: str) -> list[Event]:
    m = _NEXT.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    found: list[Event] = []

    def walk(o):
        if isinstance(o, list):
            if o and isinstance(o[0], dict):
                keys = set(o[0])
                if (keys & set(_TITLE_KEYS)) and (keys & set(_DATE_KEYS)):
                    for it in o:
                        if not isinstance(it, dict):
                            continue
                        title = next((it[k] for k in _TITLE_KEYS if isinstance(it.get(k), str)), "")
                        start = next((it[k] for k in _DATE_KEYS if isinstance(it.get(k), str)), "")
                        slug = it.get("slug")
                        if isinstance(slug, dict):
                            slug = slug.get("current")
                        url = it.get("url") or it.get("externalURL") or (slug if isinstance(slug, str) else "")
                        ev = _mk(source, title, start, url if isinstance(url, str) else "")
                        if ev:
                            found.append(ev)
            for it in o[:5]:
                walk(it)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)

    walk(data)
    dedup = {}
    for e in found:
        dedup.setdefault(e.id, e)
    return list(dedup.values())


def _from_cards(source, html: str) -> list[Event]:
    hints = JSRENDER_HINTS.get(source.slug, {})
    tree = HTMLParser(html or "")
    card_sel = hints.get("card") or "article, li[class*=event], div[class*=event], div[class*=card]"
    origin = _ORIGIN.match(source.url or "")
    origin = origin.group(1) if origin else ""
    out: list[Event] = []
    seen: set[str] = set()
    for card in tree.css(card_sel):
        a = card.css_first(hints.get("link") or "a[href]")
        t = card.css_first(hints.get("title") or "h1,h2,h3,h4")
        tm = card.css_first(hints.get("date") or "time[datetime]")
        if a is None or t is None or tm is None:
            continue
        url = (a.attributes.get("href") or "").split("?")[0]
        if url and not url.startswith("http"):
            url = origin + url
        if not url or url in seen:
            continue
        start = (tm.attributes.get("datetime") or "").strip()
        loc = card.css_first(hints["location"]) if hints.get("location") else None
        ev = _mk(source, _clean(t.text()), start, url,
                 address=_clean(loc.text()) if loc else "")
        if ev:
            seen.add(url)
            out.append(ev)
    return out


def extract_events(source, html: str, today_iso: str | None = None) -> list[Event]:
    """Events from rendered HTML, trying the most-stable layer first."""
    for layer in (_from_jsonld, _from_nextdata, _from_cards):
        evs = layer(source, html)
        if evs:
            return evs
    return []
