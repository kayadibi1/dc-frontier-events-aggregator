"""Layer-2 enrichment from each event's detail page: descriptions + speakers.

Layer-2 listing pages (CSET, CSIS, Brookings, CNAS, Atlantic Council) carry only a
title + date -- no blurb and no speaker names -- so without enrichment the calendar
shows a bare "Source: <url>" body and the big-name watchlist can't see who is
speaking. enrich_layer2 fetches each Layer-2 event's detail page and pulls:
  - a description from the page's og:/meta description (extract_description), used
    only when the event has no description yet (a listing-sourced blurb wins), and
  - speaker names (extract_speakers) from structured markup (CSIS:
    [class*=speaker]/[class*=participant]) and prose ("featuring X and Y, moderated
    by Z" -- CSET), set on Event.speakers for the big-name matcher.
Best-effort: a failed fetch leaves both empty.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from .config import SOURCE_HQ
from .fetchers.waf import curl_get
from .models import Event
from .normalize import detect_topics
from .provenance import prov_clear, prov_set
from .remote import detect_remote
from .structured import extract_structured

# A person name: 2-4 capitalized words (allowing internal hyphen/period/').
_NAME = re.compile(r"\b([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){1,3})\b")
# Words that look capitalized but are not names (cut false positives).
_STOP = {"Register Now", "Read More", "Learn More", "Add To", "Google Calendar",
         "Watch Now", "Event Page", "Privacy Policy", "United States",
         "New York", "Washington Dc", "Add To Calendar"}
# If a candidate contains any of these tokens it is an organization / field /
# affiliation, not a person name -- reject it (CSET/CSIS bios are full of these).
_ORG_WORDS = {
    "university", "college", "institute", "foundation", "center", "centre",
    "committee", "partnership", "program", "programme", "initiative", "department",
    "consulting", "studies", "policy", "science", "sciences", "community",
    "security", "analytics", "government", "cybersecurity", "homeland",
    "intelligence", "relations", "council", "association", "corporation",
    "company", "agency", "office", "bureau", "division", "group", "network",
    "coalition", "alliance", "laboratory", "school", "academy", "society",
    "bank", "fund", "capital", "ventures", "partners", "technologies", "systems",
    "solutions", "services", "foreign", "national", "federal", "neuroscience",
}
_INTRO = re.compile(r"(?:featuring|fireside chat with|joined by|with|moderated by|"
                    r"keynote by|in conversation with|speakers?:)\s+(.+?)(?:\.|\n|$)", re.I)

# Meta tags carrying the event blurb, richest first. og:description is the best on
# CSIS / Atlantic Council; plain meta / twitter descriptions are fallbacks.
_DESC_SELECTORS = ('meta[property="og:description"]',
                   'meta[name="description"]',
                   'meta[name="twitter:description"]')
# Require a real blurb so junk metas ("Events", a bare org name) are skipped.
_MIN_DESC_CHARS = 40
# Layer-2 sources behind a WAF that 403s plain httpx -- fetch via curl_cffi
# (Chrome TLS impersonation), like their listing fetchers.
_WAF_SOURCES = {
    "cset", "atlanticcouncil", "nist", "itif", "nasem", "cdt",
    "hudson", "bpc", "heritage", "scsp", "stimson", "mercatus", "aei",
}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# Site chrome (nav/menu/footer/related-events/sidebar) carries capitalized words
# the prose speaker-fallback mistakes for names ("About CSIS", "Media Requests")
# and "related events" blocks that leak another event's speaker. Strip it before
# reading speaker / virtual-vs-in-person signals from the page.
_BOILERPLATE = ("script, style, nav, footer, aside, "
                "[class*='menu'], [class*='navbar'], [class*='breadcrumb'], "
                "[class*='footer'], [class*='related'], [class*='recommend'], "
                "[class*='sidebar'], [id*='footer'], [id*='menu'], [id*='nav']")


def _main_tree(html: str) -> HTMLParser:
    """Parse HTML and remove site chrome, leaving the main content."""
    tree = HTMLParser(html or "")
    for node in tree.css(_BOILERPLATE):
        node.decompose()
    return tree


def _looks_like_name(s: str) -> bool:
    s = s.strip()
    if s in _STOP or any(ch.isdigit() for ch in s):
        return False
    parts = s.split()
    if not (2 <= len(parts) <= 4 and all(p[:1].isupper() for p in parts)):
        return False
    # Reject all-caps acronym tokens (timezones / org initials: EDT, CSIS, AI) --
    # real name words are Titlecase, so "EDT Brought" / "About CSIS" are dropped.
    if any(p.isalpha() and p.isupper() and len(p) >= 2 for p in parts):
        return False
    # Reject organization / field / affiliation strings (e.g. "Carnegie Mellon
    # University", "Open Government Partnership", "Political Science").
    return not any(p.lower().strip(".,") in _ORG_WORDS for p in parts)


def extract_speakers(html: str) -> list[str]:
    tree = _main_tree(html)
    found: list[str] = []

    # 1) structured nodes
    for node in tree.css("[class*='speaker'], [class*='participant'], [class*='panelist']"):
        name_node = node.css_first("[class*='name']") or node
        cand = _clean(name_node.text())
        if _looks_like_name(cand):
            found.append(cand)

    # 2) prose fallback ("featuring A and B, moderated by C"). Collapse
    # whitespace first so a name wrapped across a newline is not truncated.
    if not found:
        body = _clean(tree.body.text(separator=" ") if tree.body else (tree.text() or ""))
        for m in _INTRO.finditer(body):
            chunk = m.group(1)
            for piece in re.split(r",|\band\b|&", chunk):
                for nm in _NAME.findall(piece):
                    if _looks_like_name(nm):
                        found.append(nm)

    # dedupe preserving order
    seen, out = set(), []
    for n in found:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# A real postal address node contains a 5-digit ZIP; this keeps us from grabbing
# nav/footer junk out of the loosely-classed address elements.
_ZIP = re.compile(r"\b\d{5}\b")
_ADDR_SELECTORS = "[class*='location'], [class*='venue'], [class*='address'], address"


def extract_location(html: str) -> str:
    """Scrape a real per-event venue address from the detail page, if present.
    Only accepts a node that looks like a postal address (has a ZIP) so we don't
    pull navigation/footer text. Returns '' when none found (caller falls back to
    the host org's HQ)."""
    tree = HTMLParser(html)
    for node in tree.css(_ADDR_SELECTORS):
        text = _clean(node.text())
        if _ZIP.search(text) and 8 < len(text) < 160:
            return text
    return ""


# Deciding whether to pin a Layer-2 event at the org HQ. A ZIP (a real postal
# address in the main content, after boilerplate stripping) or an explicit
# in-person phrase vetoes the virtual classification, so genuine HQ events keep
# their pin while pure webcasts stay pin-less.
_VIRTUAL_RE = re.compile(
    r"\b(webcasts?|virtual (?:event|conversation|discussion|program|panel|forum)|"
    r"livestream(?:ed|ing)?|watch (?:it )?(?:live|online)|online[- ]only|"
    r"register to (?:watch|view))\b", re.I)
_INPERSON_RE = re.compile(r"\b(in[- ]person|doors open|join us at|headquarters)\b", re.I)


def _is_virtual_only(html: str) -> bool:
    """True when the page signals a virtual/webcast-only event with no in-person
    venue -- so the caller should NOT fall back to pinning it at the org HQ."""
    tree = _main_tree(html)
    body = _clean(tree.body.text(separator=" ") if tree.body else (tree.text() or ""))
    if not _VIRTUAL_RE.search(body):
        return False
    return not (_ZIP.search(body) or _INPERSON_RE.search(body))


def extract_description(html: str) -> str:
    """Pull a human blurb from a detail page's og:/meta description tags. Returns
    '' when none is long enough to be a real description (skips junk like 'Events')."""
    tree = HTMLParser(html)
    for sel in _DESC_SELECTORS:
        node = tree.css_first(sel)
        if node is None:
            continue
        content = _clean(node.attributes.get("content") or "")
        if len(content) >= _MIN_DESC_CHARS:
            return content
    return ""


async def default_fetch(url: str, source_kind: str) -> str:
    """Fetch a detail page: curl_cffi (browser TLS, profile fallback) for
    WAF-fronted sources (CSET, Atlantic Council, CDT), httpx for the rest.
    A non-200 (e.g. a Cloudflare challenge page) yields "" so the enricher
    skips the event instead of parsing challenge HTML."""
    if source_kind in _WAF_SOURCES:
        code, text = await asyncio.to_thread(curl_get, url)
        return text if code == 200 else ""
    async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=30,
                                 follow_redirects=True) as c:
        r = await c.get(url)
        return r.text if r.status_code == 200 else ""


def _reconcile_time(ev: Event, st: dict) -> None:
    """Apply a structured start/end over the listing's, honoring offset-awareness.
    Offset-aware structured time wins. A naive structured time is trusted only for
    CSIS (its JSON-LD emits naive UTC): cross-check the start against the
    offset-aware listing; on agreement also adopt the structured end (converted to
    the listing's offset); on conflict downgrade start+end+tz to date-only."""
    s = st.get("start")
    if not s:
        return
    try:
        sdt = datetime.fromisoformat(s)
    except ValueError:
        return
    ev.raw["start_structured"] = s
    if sdt.tzinfo is not None:                        # authoritative
        prov_set(ev, "time", "structured")
        ev.start = s
        if st.get("end"):
            ev.end = st["end"]
        return
    if ev.source != "csis" or not ev.start:
        return
    try:
        listing = datetime.fromisoformat(ev.start)
    except ValueError:
        return
    if listing.tzinfo is None:
        return
    struct_utc = sdt.replace(tzinfo=timezone.utc)     # CSIS naive == UTC
    if struct_utc != listing.astimezone(timezone.utc):
        ev.raw["start_conflict"] = True
        prov_clear(ev, "time")
        ev.start = ev.start[:10]
        ev.end = ev.end[:10] if ev.end else ev.end
        ev.tz = None
        return
    # agreement: adopt the structured end, expressed in the listing's offset
    end_s = st.get("end")
    if end_s:
        try:
            edt = datetime.fromisoformat(end_s).replace(tzinfo=timezone.utc)
            ev.end = edt.astimezone(listing.tzinfo).isoformat()
        except ValueError:
            pass


def recompute_topics(events: list[Event], slugs: set[str]) -> None:
    """Re-derive topic tags from each enriched event's title+description for the
    curated Layer-2 sources in `slugs`. Adapters tag topics from the bare listing
    title, so a vague-titled but on-topic policy event ("A Conversation With...")
    whose blurb is about AI/chips is otherwise dropped by the topic gate. These
    sources are high-signal and DC-curated, so trusting a description match is
    safe (the firehose sources stay title-strict). Adds only -- never removes
    existing topics or big: tags. Mutates in place."""
    for ev in events:
        if ev.source not in slugs or not ev.description:
            continue
        for t in detect_topics(f"{ev.title} {ev.description}"):
            if t not in ev.topics:
                ev.topics.append(t)


async def enrich_layer2(events: list[Event], layer_by_source: dict[str, int],
                        fetch) -> int:
    """For each Layer-2 event with a source_url, fetch its detail page via
    `fetch(url, source_kind)` and set ev.speakers + (when missing) ev.description
    and ev.address (scraped venue, else the source's HQ). Best-effort: a failed
    fetch leaves them empty. `fetch` is async and returns HTML (or '' on failure).
    Returns the number of events enriched (speakers, description, or location)."""
    # Watchlist events arrive complete (hand-curated venue/date/topics); their URLs
    # are marketing pages, so detail-scraping only invents junk speakers. Skip them.
    _NO_ENRICH = {"watchlist"}
    targets = [e for e in events
               if layer_by_source.get(e.source, 0) == 2 and e.source_url
               and e.source not in _NO_ENRICH]

    async def one(ev: Event) -> int:
        try:
            html = await fetch(ev.source_url, ev.source)
        except Exception:
            return 0
        st = extract_structured(html or "")

        # Speakers: structured performers (name-filtered) win; else heuristic.
        structured_spk = [s for s in st.get("speakers", []) if _looks_like_name(s)]
        if structured_spk:
            ev.speakers = structured_spk
            prov_set(ev, "speakers", "structured")
        else:
            scraped = extract_speakers(html or "")
            if scraped:                       # keep adapter-set speakers (e.g. congress
                ev.speakers = scraped         # witnesses) when the page scrape finds none
                prov_set(ev, "speakers", "extracted")

        added_desc = False
        if not ev.description:
            ev.description = extract_description(html or "")
            added_desc = bool(ev.description)

        # Virtual: structured VirtualLocation / attendance mode is authoritative;
        # else the regex fallback (only when structured gave no attendance signal).
        if st.get("virtual"):
            virtual = True
        elif "attendance_mode" in st:        # "mixed" -> not pure virtual
            virtual = False
        else:
            virtual = _is_virtual_only(html or "")
        if virtual:
            ev.raw["virtual"] = True
        if st.get("attendance_mode"):
            ev.raw["attendance_mode"] = st["attendance_mode"]

        # Location: structured venue/address > scraped venue > HQ (unless virtual).
        added_loc = False
        if st.get("venue_name") and not ev.venue_name:
            ev.venue_name = st["venue_name"]
        if not ev.address:
            if structured_addr := st.get("address"):
                ev.address = structured_addr
                prov_set(ev, "location", "structured")
            elif scraped_addr := extract_location(html or ""):
                ev.address = scraped_addr
                prov_set(ev, "location", "scraped")
            elif not virtual:
                ev.address = SOURCE_HQ.get(ev.source, "")
                if ev.address:
                    prov_set(ev, "location", "hq")
            added_loc = bool(ev.address)

        _reconcile_time(ev, st)

        added_remote = False
        found, w = detect_remote(html or "", ev.source_url)
        if found:
            if not ev.raw.get("remote"):
                ev.raw["remote"] = True
                added_remote = True
            if w and not ev.raw.get("watch_url"):
                ev.raw["watch_url"] = w
        return 1 if (ev.speakers or added_desc or added_loc or added_remote) else 0

    results = await asyncio.gather(*[one(e) for e in targets])
    return sum(results)
