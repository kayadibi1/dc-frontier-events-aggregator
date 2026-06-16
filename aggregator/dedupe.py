"""Collapse duplicate events.

Four passes:
  1. exact: same cleaned UID -- the same Luma event cross-listed on several
     calendars (e.g. it shows on both DC2 and aic-washington).
  2. fuzzy: same start-day + near-identical normalized title (SequenceMatcher)
     -- catches cross-platform dupes (Luma vs Meetup vs Eventbrite) that carry
     different UIDs.
  3. series: a single multi-day event listed once per day (same source +
     source_url + title, on consecutive days) -- collapsed into one event
     spanning the range. Weekly recurring meetups (>2-day gaps) are NOT merged.
  4. paraphrase: same start-day + order-insensitive token-set match (and, when
     the optional sentence-transformers dep is present, a semantic match),
     guarded by location (<= NEAR_KM apart, or missing geo) so two distinct
     same-day events at different venues are never merged.
The earliest-seen event wins; merged sources are recorded for transparency.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher

from .models import Event

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
FUZZY_THRESHOLD = 0.88
SERIES_MAX_GAP_DAYS = 2
TOKEN_THRESHOLD = 0.7
SEMANTIC_THRESHOLD = 0.80
# A shared EXACT start instant is itself a strong "same event" signal (the same
# event cross-posted on Meetup + Luma with different titles/offsets), so the token
# bar to merge is lower than the same-day paraphrase pass -- but still guarded by
# token overlap + location so two unrelated talks at the same minute don't merge.
INSTANT_TOKEN_THRESHOLD = 0.45
NEAR_KM = 3.0
# Domain-generic title words. Two DIFFERENT events can start at the same minute and
# share only these (e.g. "AI Policy Forum" vs "AI Policy Summit"), so the same-instant
# pass additionally requires a DISTINCTIVE shared token beyond this set before merging.
_GENERIC_TOKENS = {
    "ai", "ml", "policy", "forum", "webinar", "workshop", "summit", "discussion",
    "conversation", "event", "panel", "talk", "series", "annual", "virtual",
    "online", "dc", "washington", "tech", "meeting", "session", "keynote",
}

_STOP = {"the", "a", "an", "of", "on", "in", "for", "to", "and", "with", "at", "by"}


def _norm_title(t: str) -> str:
    return _NON_ALNUM.sub(" ", t.lower()).strip()


def _day(iso: str) -> str:
    return (iso or "")[:10]


def _merge_source(canonical: Event, other: Event) -> None:
    if other.source != canonical.source:
        also = canonical.raw.setdefault("also_sources", [])
        if other.source not in also:
            also.append(other.source)


def _absorb_fields(canonical: Event, other: Event) -> None:
    """Fill gaps in the surviving duplicate from `other` so it is the most
    complete copy: a precise same-day time over a date-only start, plus any
    venue / coords / speakers / richer description the canonical lacks. Never
    overwrites non-empty canonical data. Topics are unioned (a real topic the
    other listing's title carried helps the event clear the topic gate)."""
    c, o = canonical, other
    if (o.start and len(o.start) > 10 and len(c.start or "") == 10
            and _day(c.start) == _day(o.start)):
        c.start = o.start                       # date-only -> precise timed start
        if o.tz and not c.tz:
            c.tz = o.tz
    if not c.end and o.end:
        c.end = o.end
    if not c.venue_name and o.venue_name:
        c.venue_name = o.venue_name
    if not c.address and o.address:
        c.address = o.address
    if c.lat is None and o.lat is not None:
        c.lat, c.lng = o.lat, o.lng
    if not c.speakers and o.speakers:
        c.speakers = list(o.speakers)
    if len(o.description or "") > len(c.description or ""):
        c.description = o.description
    for t in o.topics:
        if t not in c.topics:
            c.topics.append(t)
    if o.raw.get("remote"):
        c.raw["remote"] = True
    if not c.raw.get("watch_url") and o.raw.get("watch_url"):
        c.raw["watch_url"] = o.raw["watch_url"]


def _merge(canonical: Event, other: Event) -> None:
    """Cross-listing duplicate: record the other source AND absorb its richer
    fields so the survivor is the most complete copy."""
    _merge_source(canonical, other)
    _absorb_fields(canonical, other)


def _day_gap(iso_a: str, iso_b: str) -> int:
    try:
        a = date.fromisoformat((iso_a or "")[:10])
        b = date.fromisoformat((iso_b or "")[:10])
        return abs((b - a).days)
    except ValueError:
        return 999


def _series_collapse(events: list[Event]) -> list[Event]:
    """Pass 3: merge a single event listed once per consecutive day into one
    spanning the date range. Keyed on (source, source_url, normalized title);
    only events with a non-empty source_url are eligible (else left untouched)."""
    groups: dict[tuple, list[Event]] = {}
    out: list[Event] = []
    for ev in events:
        if ev.source_url:
            groups.setdefault((ev.source, ev.source_url, _norm_title(ev.title)), []).append(ev)
        else:
            out.append(ev)  # no stable url -> not a collapsible series

    for evs in groups.values():
        if len(evs) == 1:
            out.append(evs[0])
            continue
        evs.sort(key=lambda e: e.start or "")
        run = [evs[0]]
        for e in evs[1:]:
            if _day_gap(run[-1].start, e.start) <= SERIES_MAX_GAP_DAYS:
                run.append(e)               # consecutive day -> same multi-day event
            else:
                out.append(_fold_run(run))   # gap too large (e.g. weekly) -> new event
                run = [e]
        out.append(_fold_run(run))
    return out


def _fold_run(run: list[Event]) -> Event:
    base = run[0]
    if len(run) > 1:
        last = run[-1]
        base.end = last.end or last.start
        base.raw["days"] = [(e.start or "")[:10] for e in run]
        for e in run[1:]:
            _merge_source(base, e)
            if e.raw.get("remote"):
                base.raw["remote"] = True
            if not base.raw.get("watch_url") and e.raw.get("watch_url"):
                base.raw["watch_url"] = e.raw["watch_url"]
    return base


def _tokens(title: str) -> set:
    return {w for w in _NON_ALNUM.sub(" ", (title or "").lower()).split()
            if w and w not in _STOP}


def _token_set_ratio(a: str, b: str) -> float:
    """Order-insensitive Jaccard over content tokens (0..1)."""
    sa, sb = _tokens(a), _tokens(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _km(a: Event, b: Event) -> float | None:
    if None in (a.lat, a.lng, b.lat, b.lng):
        return None
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = math.radians(b.lat - a.lat), math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _near(a: Event, b: Event) -> bool:
    """True if close enough to be the same physical event: within NEAR_KM, or at
    least one event lacks geo (cannot contradict)."""
    d = _km(a, b)
    return d is None or d <= NEAR_KM


_MODEL = None
_MODEL_TRIED = False


def semantic_ratio(a: str, b: str) -> float | None:
    """Cosine similarity of sentence embeddings, or None if the optional
    sentence-transformers dependency is not installed (caller falls back to
    token-set). Lazy-loads the model once."""
    global _MODEL, _MODEL_TRIED
    if not _MODEL_TRIED:
        _MODEL_TRIED = True
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        except Exception:
            _MODEL = None
    if _MODEL is None:
        return None
    import numpy as np
    va, vb = _MODEL.encode([a, b])
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def _paraphrase_collapse(events: list[Event]) -> list[Event]:
    """Pass 4: same-day order-insensitive / semantic title match, location-guarded."""
    kept: list[Event] = []
    by_day: dict[str, list[Event]] = {}
    for ev in events:
        day = _day(ev.start)
        match = None
        for other in by_day.get(day, []):
            tok = _token_set_ratio(ev.title, other.title)
            sem = semantic_ratio(ev.title, other.title)  # None if lib absent
            similar = tok >= TOKEN_THRESHOLD or (sem is not None and sem >= SEMANTIC_THRESHOLD)
            if similar and _near(ev, other):
                match = other
                break
        if match is None:
            by_day.setdefault(day, []).append(ev)
            kept.append(ev)
        else:
            _merge(match, ev)
    return kept


def _utc_instant(iso: str | None) -> str | None:
    """The event's start as a UTC instant string, or None if it is date-only or
    offset-naive (we won't compare a naive time across sources)."""
    try:
        dt = datetime.fromisoformat(iso or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _same_instant_collapse(events: list[Event]) -> list[Event]:
    """Pass 5: merge events that share the EXACT same start instant (compared in
    UTC, so different offsets for the same moment match) when their titles share
    enough tokens and their locations don't contradict. Catches the same event
    cross-posted to two platforms with reworded titles ('Data Viz' vs 'Data
    Visualization')."""
    kept: list[Event] = []
    by_instant: dict[str, list[Event]] = {}
    for ev in events:
        inst = _utc_instant(ev.start)
        if inst is None:
            kept.append(ev)
            continue
        match = None
        for other in by_instant.get(inst, []):
            # A distinctive (non-generic) shared token guards against merging two
            # different same-minute events that only share words like "AI"/"policy".
            distinctive = (_tokens(ev.title) & _tokens(other.title)) - _GENERIC_TOKENS
            if (distinctive
                    and _token_set_ratio(ev.title, other.title) >= INSTANT_TOKEN_THRESHOLD
                    and _near(ev, other)):
                match = other
                break
        if match is None:
            by_instant.setdefault(inst, []).append(ev)
            kept.append(ev)
        else:
            _merge(match, ev)
    return kept


def dedupe(events: list[Event]) -> tuple[list[Event], int]:
    # Pass 1: exact id.
    by_id: dict[str, Event] = {}
    for ev in events:
        if ev.id not in by_id:
            by_id[ev.id] = ev
        else:
            _merge(by_id[ev.id], ev)
    stage1 = list(by_id.values())

    # Pass 2: fuzzy title within the same day.
    kept: list[Event] = []
    buckets: dict[str, list[Event]] = {}
    for ev in stage1:
        day = _day(ev.start)
        nt = _norm_title(ev.title)
        match = None
        for other in buckets.get(day, []):
            if SequenceMatcher(None, nt, _norm_title(other.title)).ratio() >= FUZZY_THRESHOLD:
                match = other
                break
        if match is None:
            buckets.setdefault(day, []).append(ev)
            kept.append(ev)
        else:
            _merge(match, ev)

    # Pass 3: collapse multi-day series.
    final = _series_collapse(kept)

    # Pass 4: collapse same-day paraphrase / reorder dupes (location-guarded).
    final = _paraphrase_collapse(final)

    # Pass 5: collapse exact same-instant cross-posts with reworded titles.
    final = _same_instant_collapse(final)

    removed = len(events) - len(final)
    return final, removed
