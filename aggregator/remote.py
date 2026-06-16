"""Remote / livestream attendance signal: read-time helpers + detection.

`is_remote`/`is_hybrid`/`safe_watch_url` are the single source of truth used by
every emit path. `detect_remote` scans already-fetched event detail HTML for a
livestream option, precision-first (a false negative is fine; a false positive is
not). Uses selectolax (`HTMLParser`), matching the rest of the fetchers.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from .models import Event

_HTTP = re.compile(r"^https?://", re.I)

# Hosts where the link itself implies a live session.
_STRONG_HOSTS = ("zoom.us", "teams.microsoft.com", "on24.com", "crowdcast.io",
                 "brighttalk.com", "streamyard.com", "livestream.com", "gotowebinar.com")
_LIVE_PHRASE = re.compile(
    r"watch\s+live|watch\s+online|live\s?stream|webcast|register\s+to\s+watch|"
    r"join\s+online|attend\s+(?:virtually|online)|virtual\s+attendance|"
    r"livestream\s+link|tune\s+in|stream(?:ed)?\s+live", re.I)
_NEGATIVE = re.compile(
    r"\bpast\b|\bprevious\b|recording|replay|on[- ]demand|watch\s+again|archive|"
    r"recap|in[- ]person\s+only|no\s+(?:livestream|webcast|virtual)|"
    r"(?:will\s+)?not\s+be\s+(?:livestreamed|webcast|streamed)|"
    r"virtual\s+attendance\s+is\s+not\s+available", re.I)
_CHANNEL_RE = re.compile(r"/(?:@|channel/|user/|c/)", re.I)
_BLOCK_TAGS = {"li", "p", "td", "figure", "blockquote", "h1", "h2", "h3", "h4"}


def is_remote(ev: Event) -> bool:
    """Can be attended/watched remotely: an explicit remote signal OR fully-virtual."""
    return bool(ev.raw.get("remote")) or bool(ev.raw.get("virtual"))


def is_hybrid(ev: Event) -> bool:
    """Remote AND in-person (has an address) AND not fully-virtual."""
    return is_remote(ev) and bool(ev.address) and not bool(ev.raw.get("virtual"))


def safe_watch_url(ev: Event) -> str:
    """The watch link, sanitized to http(s) only (a scraped javascript: becomes '')."""
    u = (ev.raw.get("watch_url") or "").strip()
    return u if _HTTP.match(u) else ""


def _strong_host(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in _STRONG_HOSTS)


def _live_path(u) -> bool:
    host = (u.hostname or "").lower()
    if host.endswith("youtube.com") and u.path.startswith("/live/"):
        return True
    if host.endswith("vimeo.com") and u.path.startswith("/event/"):
        return True
    return False


def _block_text(node) -> str:
    """Text of the anchor's nearest small block ancestor (so a phrase next to the
    link counts, but a huge container's unrelated text does not)."""
    cur = node
    for _ in range(4):
        if cur is None:
            break
        if cur.tag in _BLOCK_TAGS:
            return cur.text() or ""
        cur = cur.parent
    return node.text() or ""


def detect_remote(html: str, base_url: str = "") -> tuple[bool, str]:
    """Scan event detail HTML for a livestream/remote-attendance link.
    Returns (found, watch_url). Scoped to <main>/<article> (falls back to <body>)
    so nav/footer/related links don't false-positive."""
    if not html:
        return (False, "")
    tree = HTMLParser(html)
    root = None
    for sel in ("main", "article"):
        root = tree.css_first(sel)
        if root is not None:
            break
    if root is None:
        root = tree.body or tree

    candidates = []   # (abs_url, parsed, block_text), negatives already excluded
    for a in root.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        absu = urljoin(base_url, href) if base_url else href
        if not _HTTP.match(absu):
            continue
        ctx = _block_text(a)
        if _NEGATIVE.search(ctx):
            continue
        candidates.append((absu, urlparse(absu), ctx))

    # Pass A: a link whose host/path implies a live session.
    for absu, u, _ctx in candidates:
        if _CHANNEL_RE.search(u.path) and not _live_path(u):
            continue
        if _strong_host((u.hostname or "").lower()) or _live_path(u):
            return (True, absu)

    # Pass B/C: a live phrase in the link's block (weak-host or phrase-anchored link).
    for absu, u, ctx in candidates:
        if _CHANNEL_RE.search(u.path):
            continue
        if _LIVE_PHRASE.search(ctx):
            return (True, absu)

    return (False, "")
