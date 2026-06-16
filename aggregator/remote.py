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

# Dedicated streaming/webinar platforms: a (non-marketing) link is an event/stream.
_DEDICATED_HOSTS = ("on24.com", "crowdcast.io", "brighttalk.com", "streamyard.com",
                    "livestream.com", "gotowebinar.com", "gotomeeting.com")
# Big hosts that ALSO serve marketing pages -> require an event-like path so a
# footer "powered by Zoom" / privacy link is not mistaken for a live session.
_HOST_EVENT_PATH = {
    "zoom.us": re.compile(r"/(?:j|w|s|webinar|meeting|register)/", re.I),
    "teams.microsoft.com": re.compile(r"/l/meetup-join|/meet/", re.I),
    "webex.com": re.compile(r"/(?:meet|join|event|webappng|e)/", re.I),
    "meet.google.com": re.compile(r"^/[a-z0-9-]{6,}", re.I),
}
_NON_EVENT_PATH = re.compile(
    r"^/(?:privacy|terms|about|pricing|contact|blog|career|help|support|legal|"
    r"cookie|policy|trust|security|press|sponsor|download|sign-?in|login)\b", re.I)
_WEAK_HOST = re.compile(r"(?:^|\.)(?:youtube\.com|youtu\.be|vimeo\.com|facebook\.com)$", re.I)
_ACTION_ANCHOR = re.compile(
    r"watch|join|register|stream|rsvp|\blive\b|webcast|tune\s*in|view|attend", re.I)
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
# Related-events / share / cookie blocks that live INSIDE the event body. Page
# chrome (footer/nav) is already excluded by the <main>/<article> scoping, so we
# deliberately do NOT match generic layout words like "sidebar"/"aside"/"nav" --
# event pages often place the registration CTA in a layout sidebar (e.g. CSET's
# "l-sidebar__main post-content"), and excluding those drops real watch links.
_EXCLUDE_ANCESTOR = re.compile(
    r"\brelated\b|recommend|more-events|other-events|upcoming-events|"
    r"social-share|share-button|sharedaddy|addtoany|cookie|newsletter|promo|sponsor",
    re.I)
_BLOCK_TAGS = {"li", "p", "td", "figure", "blockquote", "h1", "h2", "h3", "h4"}
_CTX_CAP = 500


def is_remote(ev: Event) -> bool:
    """Can be attended/watched remotely: an explicit remote signal OR fully-virtual."""
    return bool(ev.raw.get("remote")) or bool(ev.raw.get("virtual"))


def is_hybrid(ev: Event) -> bool:
    """Remote AND in-person (has an address) AND not fully-virtual."""
    return is_remote(ev) and bool(ev.address) and not bool(ev.raw.get("virtual"))


def safe_watch_url(ev: Event) -> str:
    """The watch link, sanitized to http(s) only (a scraped javascript:/non-string
    becomes ''). THE accessor every emitter uses."""
    u = ev.raw.get("watch_url")
    if not isinstance(u, str):
        return ""
    u = u.strip()
    return u if _HTTP.match(u) else ""


def _live_path(u) -> bool:
    host = (u.hostname or "").lower()
    if host.endswith("youtube.com") and u.path.startswith("/live/"):
        return True
    if host.endswith("vimeo.com") and u.path.startswith("/event/"):
        return True
    return False


def _strong_live_link(u) -> bool:
    """A link whose host (+ path, for hosts that also serve marketing pages)
    implies a live session, independent of surrounding text."""
    host = (u.hostname or "").lower()
    path = u.path or ""
    if _NON_EVENT_PATH.search(path):
        return False
    for h, pat in _HOST_EVENT_PATH.items():
        if host == h or host.endswith("." + h):
            return bool(pat.search(path))
    return any(host == d or host.endswith("." + d) for d in _DEDICATED_HOSTS)


def _block_text(node) -> str:
    """Text of the anchor's nearest small block ancestor, capped, so a phrase next
    to the link counts but a huge container's unrelated text does not."""
    cur = node
    for _ in range(4):
        if cur is None:
            break
        if cur.tag in _BLOCK_TAGS:
            return (cur.text() or "")[:_CTX_CAP]
        cur = cur.parent
    return (node.text() or "")[:_CTX_CAP]


def _excluded(node) -> bool:
    """True if the link sits inside page chrome (related/share/footer/nav/...)."""
    cur = node
    for _ in range(8):
        if cur is None:
            break
        attrs = cur.attributes or {}
        cls = f"{attrs.get('class') or ''} {attrs.get('id') or ''}"
        if cls.strip() and _EXCLUDE_ANCESTOR.search(cls):
            return True
        cur = cur.parent
    return False


def detect_remote(html: str, base_url: str = "") -> tuple[bool, str]:
    """Scan event detail HTML for a livestream/remote-attendance link.
    Returns (found, watch_url). Scoped to <main>/<article> (falls back to <body>),
    excludes page chrome, and guards against recordings / negations."""
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

    cands = []   # (abs_url, parsed, block_text, anchor_text); negatives/chrome dropped
    for a in root.css("a[href]"):
        if _excluded(a):
            continue
        href = (a.attributes.get("href") or "").strip()
        absu = urljoin(base_url, href) if base_url else href
        if not _HTTP.match(absu):
            continue
        ctx = _block_text(a)
        if _NEGATIVE.search(ctx):
            continue
        cands.append((absu, urlparse(absu), ctx, a.text() or ""))

    # Pass A: a link whose host/path implies a live session, regardless of text.
    for absu, u, _ctx, _t in cands:
        if _CHANNEL_RE.search(u.path) and not _live_path(u):
            continue
        if _strong_live_link(u) or _live_path(u):
            return (True, absu)

    # Pass B/C: a live phrase in the link's block. Among such links prefer a weak
    # video host or an action-word anchor over an arbitrary first link in the block.
    phrase = [(absu, u, t) for absu, u, ctx, t in cands
              if not _CHANNEL_RE.search(u.path) and _LIVE_PHRASE.search(ctx)]
    for absu, u, t in phrase:
        if _WEAK_HOST.search(u.hostname or "") or _ACTION_ANCHOR.search(t):
            return (True, absu)
    if phrase:
        return (True, phrase[0][0])
    return (False, "")
