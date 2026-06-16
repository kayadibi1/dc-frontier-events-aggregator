"""Layer-2 adapters for additional DC policy / NGO event sources.

These sources do not share one CMS, but they do share one operational need:
listing pages are only a discovery surface, while detail pages are the
authoritative place for date, time, venue, attendance mode, and speakers.  The
helpers below keep parsing conservative:

* never fabricate an event without a parseable event date;
* prefer schema.org Event JSON-LD when present;
* treat publish dates as non-events;
* keep broad org feeds behind the normal DC/topic/big-name filter.
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from ..config import SOURCE_HQ, Source
from ..remote import detect_remote
from ..models import Event
from ..normalize import detect_topics
from ..provenance import prov_set
from ..structured import extract_structured
from .base import SourceResult
from .waf import curl_get

TIMEOUT = 30.0
MAX_DETAIL_LINKS = 24
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_WS = re.compile(r"\s+")
_DATE_LONG = re.compile(r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s+(20\d{2})\b")
_DATE_SHORT = re.compile(r"\b([A-Z][a-z]{2})\s+(\d{1,2}),\s+(20\d{2})\b")
_DATE_DAY_MONTH = re.compile(r"\b(\d{1,2})\s+([A-Z][a-z]+)\s+(20\d{2})\b")
_DATE_DOT = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b")
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|AM|PM|am|pm)\b", re.I)
_DETAIL_BOILERPLATE = (
    "script, style, nav, footer, aside, [class*='menu'], [class*='nav'], "
    "[class*='footer'], [class*='related'], [class*='recommend'], "
    "[class*='sidebar'], [id*='footer'], [id*='menu'], [id*='nav']"
)
_STOP_TITLES = {
    "", "events", "event", "learn more", "read more", "view details",
    "register", "register here", "upcoming events", "past events",
}
_ONLINE_RE = re.compile(r"\b(online|virtual|webinar|livestream|live online|zoom)\b", re.I)
_IN_PERSON_RE = re.compile(r"\b(in[- ]person|doors open|where\s+(?!online)|at\s+the)\b", re.I)
_CANCEL_RE = re.compile(r"\b(cancel(?:ed|led)|postponed|private)\b", re.I)

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


@dataclass(frozen=True)
class DetailSeed:
    url: str
    title: str = ""
    start: str = ""
    description: str = ""


def _clean(text: str) -> str:
    return _html.unescape(_WS.sub(" ", text or "").strip())


def _main_text(html: str) -> str:
    tree = HTMLParser(html or "")
    for node in tree.css(_DETAIL_BOILERPLATE):
        node.decompose()
    return _clean(tree.body.text(separator=" ") if tree.body else tree.text(separator=" "))


def _detail_scope_text(html: str, title: str = "") -> str:
    """Text most likely to be the event detail block, not site chrome.

    Many institutional pages render search drawers or related articles before the
    actual event.  Date parsing from the whole body can then accidentally grab a
    publication date.  Prefer a node around the H1/title that also contains an
    event date; fall back to a bounded window around the title.
    """
    tree = HTMLParser(html or "")
    for node in tree.css(_DETAIL_BOILERPLATE):
        node.decompose()
    h1 = tree.css_first("h1")
    candidates = []
    if h1 is not None:
        cur = h1
        for _ in range(5):
            if cur is None:
                break
            candidates.append(cur)
            cur = cur.parent
    candidates.extend(tree.css(
        "main, article, [class*='event-detail'], [class*='event-node'], "
        "[class*='single-event'], [class*='hero-event']"))
    for node in candidates:
        text = _clean(node.text(separator=" "))
        if text and _first_event_date(text) and (not title or title[:40] in text):
            return text
    body = _clean(tree.body.text(separator=" ") if tree.body else tree.text(separator=" "))
    if title:
        idx = body.find(title)
        if idx >= 0:
            return body[max(0, idx - 500):idx + 2800]
    return body


def _title_from_detail(html: str) -> str:
    tree = HTMLParser(html or "")
    for sel in ("h1", "meta[property='og:title']", "title"):
        node = tree.css_first(sel)
        if node is None:
            continue
        text = node.attributes.get("content", "") if sel.startswith("meta") else node.text()
        text = _clean(text)
        if text and text.lower() not in _STOP_TITLES:
            # Strip site suffixes from <title> fallbacks.
            return re.split(r"\s+(?:[|-]|\u2022)\s+", text, maxsplit=1)[0].strip()
    return ""


def _description_from_detail(html: str) -> str:
    tree = HTMLParser(html or "")
    for sel in (
        "meta[property='og:description']",
        "meta[name='description']",
        "meta[name='twitter:description']",
    ):
        node = tree.css_first(sel)
        if node is None:
            continue
        text = _clean(node.attributes.get("content", ""))
        if len(text) >= 40:
            return text
    # Conservative prose fallback: first substantial paragraph.
    for p in tree.css("main p, article p, .content p, p"):
        text = _clean(p.text())
        if len(text) >= 80 and not text.lower().startswith(("subscribe", "sign up")):
            return text
    return ""


def _us_eastern(d: date) -> tuple[str, str]:
    mar1 = date(d.year, 3, 1).weekday()
    dst_start = date(d.year, 3, 1 + ((6 - mar1) % 7) + 7)
    nov1 = date(d.year, 11, 1).weekday()
    dst_end = date(d.year, 11, 1 + ((6 - nov1) % 7))
    return ("EDT", "-04:00") if dst_start <= d < dst_end else ("EST", "-05:00")


def _date_from_match(month: str, day: str, year: str) -> date | None:
    m = _MONTHS.get(month.lower().rstrip("."))
    if not m:
        return None
    try:
        return date(int(year), m, int(day))
    except ValueError:
        return None


def _first_event_date(text: str) -> date | None:
    """First date shape common in event detail areas."""
    for rx in (_DATE_LONG, _DATE_SHORT):
        m = rx.search(text)
        if m:
            return _date_from_match(m.group(1), m.group(2), m.group(3))
    m = _DATE_DAY_MONTH.search(text)
    if m:
        return _date_from_match(m.group(2), m.group(1), m.group(3))
    m = _DATE_DOT.search(text)
    if m:
        mm, dd, yy = map(int, m.groups())
        try:
            return date(2000 + yy, mm, dd)
        except ValueError:
            return None
    return None


def _to_24h(m: re.Match) -> tuple[int, int]:
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ap = m.group(3).lower().replace(".", "")
    if ap == "pm" and hour != 12:
        hour += 12
    if ap == "am" and hour == 12:
        hour = 0
    return hour, minute


def _parse_when(text: str, fallback_date: str = "") -> tuple[str | None, str | None, str | None]:
    """Return start/end/tz from common policy-event date lines."""
    clean = _clean(text)
    d = _first_event_date(clean)
    if d is None and fallback_date:
        try:
            d = date.fromisoformat(fallback_date[:10])
        except ValueError:
            d = None
    if d is None:
        return None, None, None

    # Bias time parsing to a small window after the event date, avoiding agenda
    # times and related-card dates later in the page.
    date_pos = len(clean)
    for rx in (_DATE_LONG, _DATE_SHORT, _DATE_DAY_MONTH, _DATE_DOT):
        m = rx.search(clean)
        if m:
            date_pos = m.start()
            break
    window = clean[date_pos:date_pos + 700]
    times = list(_TIME.finditer(window))
    if not times:
        return d.isoformat(), None, None
    sh, sm = _to_24h(times[0])
    label, off = _us_eastern(d)
    start = f"{d.isoformat()}T{sh:02d}:{sm:02d}:00{off}"
    end = None
    if len(times) >= 2:
        eh, em = _to_24h(times[1])
        end = f"{d.isoformat()}T{eh:02d}:{em:02d}:00{off}"
    return start, end, label


def _parse_google_calendar_when(html: str) -> tuple[str | None, str | None, str | None]:
    tree = HTMLParser(html or "")
    for a in tree.css("a[href*='calendar.google.com/calendar/render']"):
        href = (a.attributes.get("href") or "").replace("&amp;", "&")
        qs = parse_qs(urlparse(href).query)
        dates = (qs.get("dates") or [""])[0]
        if "/" not in dates:
            continue
        raw_start, raw_end = dates.split("/", 1)
        if not (len(raw_start) >= 15 and len(raw_end) >= 15):
            continue
        try:
            d = date(int(raw_start[:4]), int(raw_start[4:6]), int(raw_start[6:8]))
            sh, sm, ss = int(raw_start[9:11]), int(raw_start[11:13]), int(raw_start[13:15])
            eh, em, es = int(raw_end[9:11]), int(raw_end[11:13]), int(raw_end[13:15])
        except ValueError:
            continue
        label, off = _us_eastern(d)
        return (
            f"{d.isoformat()}T{sh:02d}:{sm:02d}:{ss:02d}{off}",
            f"{d.isoformat()}T{eh:02d}:{em:02d}:{es:02d}{off}",
            label,
        )
    return None, None, None


def _strip_tags(fragment: str) -> str:
    return _clean(HTMLParser(fragment or "").text(separator=" "))


def _node_link(node, base: str) -> str:
    href = (node.attributes.get("href") or "").split("#")[0].split("?")[0]
    return urljoin(base, href)


def _slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return re.sub(r"[^a-z0-9-]+", "-", path.rsplit("/", 1)[-1].lower()).strip("-")


def _is_online(text: str, loc: str = "") -> bool:
    blob = f"{loc} {text}"
    if re.search(r"\b(?:In[- ]Person Event|Online or In[- ]Person)\b", blob, re.I):
        return False
    if re.search(r"\b(?:Where|Location)\s+Online\b|\bLive Online\b|\bOnline Only\b|\bVirtual\b", blob, re.I):
        return True
    return bool(_ONLINE_RE.search(blob)) and not bool(_IN_PERSON_RE.search(blob))


def _clean_where_value(loc: str) -> str:
    loc = _clean(loc)
    if re.match(r"Online\b|Virtual\b", loc, re.I):
        return ""
    loc = re.split(
        r"\s+\(?This event\b|\s+On\s+[A-Z][a-z]+\s+\d{1,2}\b|"
        r"\s+Watch\b|\s+Opening Remarks\b|\s+Panel Discussion\b|"
        r"\s+The\s+[A-Z][a-z]+",
        loc,
        maxsplit=1,
    )[0]
    return loc.strip(" ,;")


def _location_from_text(text: str, source_slug: str = "") -> str:
    # Explicit "Where ..." blocks first.
    m = re.search(
        r"\bWhere\s+(.+?)(?:\s+(?:Register|RSVP|Share|Featuring|Agenda|This event|"
        r"Event Description|The |Join |Hosted by|Use and)\b|$)",
        text)
    if m:
        loc = _clean_where_value(m.group(1))
        if loc and not _ONLINE_RE.fullmatch(loc):
            if source_slug == "aei" and loc.lower().startswith("aei"):
                return SOURCE_HQ.get("aei", loc)
            return loc
    # Common direct venue phrases.
    patterns = [
        r"(Rayburn HOB[^.]{0,80}Washington,?\s*D\.?C\.?)",
        r"(The Heritage Foundation\s+\d+[^.]{0,120}Washington,?\s*DC\s*\d{5})",
        r"((?:National Press Club|Union Station|Walter E\. Washington Convention Center)[^|;]{0,120})",
        r"([A-Z][A-Za-z .&'-]+,\s*Washington,?\s*D\.?C\.?(?:\s*\d{5})?)",
        r"(Washington,?\s*D\.?C\.?(?:\s*\d{5})?)",
        r"(Arlington,?\s*VA(?:\s*\d{5})?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            loc = _clean(m.group(1).replace("Copied", ""))
            if len(loc) <= 180:
                return loc
    if source_slug == "carnegie" and "Carnegie Endowment for International Peace" in text:
        return SOURCE_HQ.get("carnegie", "")
    # If a detail page says an in-person event is at the host org, pin to HQ.
    if source_slug and re.search(r"\bIn[- ]Person Event\b", text, re.I):
        return SOURCE_HQ.get(source_slug, "")
    return ""


def _event_from_detail(source: Source, seed: DetailSeed, html: str,
                       organizer: str) -> Event | None:
    if _CANCEL_RE.search(_main_text(html)[:400]):
        return None
    structured = extract_structured(html)
    title = structured.get("name") or _title_from_detail(html) or seed.title
    title = _clean(title)
    if not title or title.lower() in _STOP_TITLES:
        return None
    body = _detail_scope_text(html, title)
    full_body = _main_text(html)

    start = structured.get("start")
    end = structured.get("end")
    tz = None
    if start:
        try:
            dt = datetime.fromisoformat(start)
            if dt.tzinfo is not None:
                tz = _us_eastern(dt.date())[0] if dt.utcoffset() else None
        except ValueError:
            pass
    if not start:
        start, end, tz = _parse_google_calendar_when(html)
    if not start:
        start, end, tz = _parse_when(body, seed.start)
    if not start:
        return None

    loc = structured.get("address") or _location_from_text(body, source.slug)
    if not loc and body != full_body:
        loc = _location_from_text(full_body, source.slug)
    if source.slug == "aei" and re.fullmatch(r"Washington,?\s*D\.?C\.?\s*20036", loc or "", re.I):
        loc = SOURCE_HQ.get("aei", loc)
    venue = structured.get("venue_name", "")
    virtual = bool(structured.get("virtual")) or _is_online(body, loc)
    if not virtual and body != full_body:
        # Some page templates put "Where Online" outside the nearest title/date
        # block. Only use explicit online-only phrases from the full page, not
        # generic "online" mentions that may live in related cards.
        virtual = bool(re.search(r"\bWhere\s+Online\b|\bLive Online\b|\bOnline Only\b|\bVirtual Event\b",
                                 full_body, re.I))
    if re.search(r"\b(?:In[- ]Person Event|Online or In[- ]Person)\b", body, re.I):
        virtual = False
    if virtual and _ONLINE_RE.fullmatch((loc or "").strip()):
        loc = ""
    if not loc and not virtual and source.dc_curated:
        loc = SOURCE_HQ.get(source.slug, "")
        if loc:
            prov = "hq"
        else:
            prov = ""
    elif structured.get("address"):
        prov = "structured"
    elif loc:
        prov = "scraped"
    else:
        prov = ""

    desc = seed.description or structured.get("description") or _description_from_detail(html)
    topics = detect_topics(f"{title} {desc}")
    ev = Event(
        id=f"{source.slug}-{_slug(seed.url)}",
        title=title,
        start=start,
        end=end,
        tz=tz,
        source=source.slug,
        source_url=seed.url,
        description=desc,
        venue_name=venue,
        address=loc,
        organizer=organizer,
        topics=topics,
        raw={"virtual": virtual} if virtual else {},
    )
    if prov:
        prov_set(ev, "location", prov)
    if "T" in start:
        prov_set(ev, "time", "structured" if structured.get("start") else "extracted")
    found, w = detect_remote(html, seed.url)
    if found:
        ev.raw["remote"] = True
        if w and not ev.raw.get("watch_url"):
            ev.raw["watch_url"] = w
    return ev


def _link_seeds(html: str, base: str, contains: str, title_selector: str = "") -> list[DetailSeed]:
    tree = HTMLParser(html or "")
    out: list[DetailSeed] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        url = _node_link(a, base)
        if contains not in url or url.rstrip("/") == base.rstrip("/") or url in seen:
            continue
        seen.add(url)
        title = _clean(a.text())
        if title.lower() in _STOP_TITLES and title_selector:
            cur = a
            for _ in range(5):
                cur = cur.parent if cur is not None else None
                if cur is None:
                    break
                h = cur.css_first(title_selector)
                if h is not None:
                    title = _clean(h.text())
                    break
        out.append(DetailSeed(url=url, title=title if title.lower() not in _STOP_TITLES else ""))
    return out


async def _fetch_html(url: str, waf: bool, client: httpx.AsyncClient | None = None
                      ) -> tuple[int, str]:
    if waf:
        return await asyncio.to_thread(curl_get, url)
    if client is None:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
            timeout=TIMEOUT, follow_redirects=True
        ) as c:
            r = await c.get(url)
            return r.status_code, r.text
    r = await client.get(url)
    return r.status_code, r.text


async def _fetch_json(url: str, waf: bool, client: httpx.AsyncClient | None = None):
    code, text = await _fetch_html(url, waf, client)
    if code != 200:
        return code, None
    try:
        return code, json.loads(text)
    except json.JSONDecodeError:
        return code, None


async def _detail_events(source: Source, seeds: list[DetailSeed], organizer: str,
                         waf: bool = False) -> list[Event]:
    seeds = seeds[:MAX_DETAIL_LINKS]
    events: list[Event] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
        timeout=TIMEOUT, follow_redirects=True
    ) as client:
        async def one(seed: DetailSeed):
            code, html = await _fetch_html(seed.url, waf, client)
            if code != 200:
                return None
            return _event_from_detail(source, seed, html, organizer)

        for ev in await asyncio.gather(*[one(s) for s in seeds]):
            if ev is not None:
                events.append(ev)
    return events


async def _fetch_from_listing(source: Source, base: str, contains: str, organizer: str,
                              waf: bool = False, title_selector: str = "h1,h2,h3,h4"
                              ) -> SourceResult:
    code, html = await _fetch_html(source.url, waf)
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    seeds = _link_seeds(html, base, contains, title_selector)
    events = await _detail_events(source, seeds, organizer, waf)
    return SourceResult(source, events, code, None)


def parse_newamerica_item(source: Source, item: dict) -> Event | None:
    title = _strip_tags((item.get("title") or {}).get("rendered", ""))
    details = (item.get("acf") or {}).get("details") or {}
    dt = details.get("date_time") or {}
    d0 = dt.get("start_date") or ""
    if not (isinstance(d0, str) and len(d0) == 8 and d0.isdigit()):
        return None
    d = date(int(d0[:4]), int(d0[4:6]), int(d0[6:8]))
    label, off = _us_eastern(d)
    t0 = dt.get("start_time") or ""
    t1 = dt.get("end_time") or ""
    if t0:
        start = f"{d.isoformat()}T{t0[:8]}{off}"
        tz = label
    else:
        start, tz = d.isoformat(), None
    end = None
    if t1:
        end_date = d
        ed = dt.get("end_date") or ""
        if isinstance(ed, str) and len(ed) == 8 and ed.isdigit():
            end_date = date(int(ed[:4]), int(ed[4:6]), int(ed[6:8]))
        end = f"{end_date.isoformat()}T{t1[:8]}{off}"
    loc_parts = [details.get("location"), details.get("location_line_2"),
                 details.get("location_line_3")]
    address = _clean(", ".join(p for p in loc_parts if isinstance(p, str) and p.strip()))
    event_type = ((details.get("helper_taxonomies") or {}).get("event_type") or "")
    virtual = (event_type == 3864) or _is_online("", address)
    desc = _clean(details.get("abstract") or "")
    ev = Event(
        id=f"{source.slug}-{item.get('slug')}",
        title=title,
        start=start,
        end=end,
        tz=tz,
        source=source.slug,
        source_url=item.get("link") or "",
        description=desc,
        address="" if virtual and _ONLINE_RE.fullmatch(address or "") else address,
        organizer="New America",
        topics=detect_topics(f"{title} {desc}"),
        raw={"virtual": True} if virtual else {},
    )
    if address and not virtual:
        prov_set(ev, "location", "scraped")
    if "T" in start:
        prov_set(ev, "time", "structured")
    return ev


async def fetch_newamerica(source: Source) -> SourceResult:
    url = "https://www.newamerica.org/wp-json/wp/v2/event?per_page=30"
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT,
                                 follow_redirects=True) as client:
        code, data = await _fetch_json(url, False, client)
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    events = [e for item in (data or []) if (e := parse_newamerica_item(source, item))]
    return SourceResult(source, events, code, None)


def parse_fas_item(source: Source, item: dict) -> Event | None:
    title = _strip_tags((item.get("title") or {}).get("rendered", ""))
    text = _strip_tags((item.get("content") or {}).get("rendered", ""))
    start, end, tz = _parse_when(text)
    if not start:
        return None
    loc = _location_from_text(text, source.slug)
    desc = _strip_tags((item.get("excerpt") or {}).get("rendered", "")) or text[:400]
    ev = Event(
        id=f"{source.slug}-{item.get('slug')}",
        title=title,
        start=start,
        end=end,
        tz=tz,
        source=source.slug,
        source_url=item.get("link") or "",
        description=desc,
        address=loc,
        organizer="FAS",
        topics=detect_topics(f"{title} {desc}"),
    )
    if loc:
        prov_set(ev, "location", "scraped")
    if "T" in start:
        prov_set(ev, "time", "extracted")
    return ev


async def fetch_fas(source: Source) -> SourceResult:
    return await _fetch_wp_detail_source(
        source,
        "https://fas.org/wp-json/wp/v2/events?per_page=30",
        "FAS",
        waf=False,
    )


async def _fetch_wp_detail_source(source: Source, endpoint: str, organizer: str,
                                  waf: bool, status_param: str = "") -> SourceResult:
    url = endpoint + ("&" + status_param if status_param else "")
    code, data = await _fetch_json(url, waf)
    if code != 200:
        return SourceResult(source, [], code, f"HTTP {code}")
    seeds = []
    for item in data or []:
        link = item.get("link")
        if not link:
            continue
        seeds.append(DetailSeed(
            url=link,
            title=_strip_tags((item.get("title") or {}).get("rendered", "")),
            description=_strip_tags((item.get("excerpt") or {}).get("rendered", "")),
        ))
    events = await _detail_events(source, seeds, organizer, waf)
    return SourceResult(source, events, code, None)


async def fetch_bpc(source: Source) -> SourceResult:
    return await _fetch_wp_detail_source(
        source,
        "https://bipartisanpolicy.org/wp-json/wp/v2/event?per_page=30",
        "Bipartisan Policy Center",
        waf=True,
    )


async def fetch_stimson(source: Source) -> SourceResult:
    return await _fetch_wp_detail_source(
        source,
        "https://www.stimson.org/wp-json/wp/v2/event?per_page=30",
        "Stimson Center",
        waf=True,
        status_param="event-status=689",
    )


async def fetch_hudson(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://www.hudson.org/events", "hudson.org/events/",
        "Hudson Institute", waf=True, title_selector="h1,h2,h3,h4")


async def fetch_aei(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://www.aei.org/events/", "aei.org/events/",
        "AEI", waf=True, title_selector="h1,h2,h3,h4")


async def fetch_heritage(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://www.heritage.org/events", "/event/",
        "Heritage Foundation", waf=True, title_selector="h1,h2,h3,h4")


async def fetch_carnegie(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://carnegieendowment.org/events", "carnegieendowment.org/events/",
        "Carnegie Endowment", waf=False, title_selector="h1,h2,h3,h4")


async def fetch_rand(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://www.rand.org/events.html", "rand.org/events/",
        "RAND", waf=False, title_selector="h1,h2,h3,h4")


async def fetch_wilson(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://www.wilsoncenter.org/events", "wilsoncenter.org/event/",
        "Wilson Center", waf=False, title_selector="h1,h2,h3,h4")


async def fetch_scsp(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://www.scsp.ai/events/", "scsp.ai/event/",
        "SCSP", waf=True, title_selector="h1,h2,h3,h4")


async def fetch_mercatus(source: Source) -> SourceResult:
    return await _fetch_from_listing(
        source, "https://www.mercatus.org/events", "mercatus.org/events/",
        "Mercatus Center", waf=True, title_selector="h1,h2,h3,h4")
