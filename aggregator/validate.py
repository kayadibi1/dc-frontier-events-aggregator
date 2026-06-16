"""Two-phase validation gate. Prefer omitting/downgrading a field to emitting a
wrong value. `validate_pre_filter` cleans fields the relevance filter consumes (so
it runs BEFORE apply_filters, which is not idempotent). `validate_post_geocode`
does coordinate cross-checks AFTER geocode. Each returns (clean, dropped),
dropped = list of (event_id, field, reason). `today_iso` is injected (never
wall-clock) for deterministic tests / --today runs.
"""
from __future__ import annotations

import time
from datetime import date, datetime

from .config import DC_BBOX, SOURCE_HQ
from .enrich import _looks_like_name
from .filter import is_dc_relevant
from .geocode import _address_variants, _norm, load_cache, save_cache
from .models import Event
from .provenance import prov_clear
from .rank import _haversine_km

DATE_WINDOW_YEARS = 3
MAX_SPEAKERS = 12
STREET_KM = 2.0
VENUE_KM = 10.0
_MIN_INTERVAL_S = 1.1


def _date_of(start: str | None):
    if not start:
        return None
    try:
        return date.fromisoformat(start[:10])
    except ValueError:
        return None


def _is_timed(start: str | None) -> bool:
    return bool(start) and "T" in start


def _tzinfo_of(start: str | None):
    try:
        return datetime.fromisoformat(start).tzinfo if start else None
    except ValueError:
        return None


def validate_pre_filter(events: list[Event], today_iso: str) -> tuple[list[Event], list]:
    today = date.fromisoformat(today_iso)
    lo = date(today.year - DATE_WINDOW_YEARS, 1, 1)
    hi = date(today.year + DATE_WINDOW_YEARS, 12, 31)
    clean: list[Event] = []
    dropped: list = []
    for ev in events:
        d = _date_of(ev.start)
        if d is None or not (lo <= d <= hi):
            dropped.append((ev.id, "date", f"implausible:{ev.start}"))
            continue
        if _is_timed(ev.start) and _tzinfo_of(ev.start) is None:
            dropped.append((ev.id, "time", "timed-no-tz"))
            ev.start = ev.start[:10]
            if ev.end:
                ev.end = ev.end[:10]
            ev.tz = None
            prov_clear(ev, "time")
        if ev.speakers:
            cleaned = [s for s in ev.speakers if _looks_like_name(s)]
            if len(cleaned) > MAX_SPEAKERS:
                dropped.append((ev.id, "speakers", "over-limit"))
                cleaned = []
            elif len(cleaned) != len(ev.speakers):
                dropped.append((ev.id, "speakers", "junk-removed"))
            ev.speakers = cleaned
            if not ev.speakers:
                prov_clear(ev, "speakers")
        # A pure-virtual event must not carry a physical-venue (HQ) fallback.
        # No generic junk-address nulling here -- that would erase valid ZIP-less
        # venues (e.g. "Marvin Center, Washington, DC"); handled, geocode-informed,
        # in validate_post_geocode.
        if ev.raw.get("virtual") and ev.address:
            dropped.append((ev.id, "address", "virtual-cleared"))
            ev.address = ""
            prov_clear(ev, "location")
        clean.append(ev)
    return clean, dropped


def _in_bbox(lat: float, lng: float) -> bool:
    b = DC_BBOX
    return b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]


def _has_street_number(addr: str) -> bool:
    return any(part[:1].isdigit() for part in addr.split())


def _has_zip(addr: str) -> bool:
    tail = addr.split(",")[-1]
    return any(ch.isdigit() for ch in tail)


def validate_post_geocode(events: list[Event], today_iso: str, query=None,
                          cache_path: str | None = None, sleep=time.sleep) -> tuple[list[Event], list]:
    cache = load_cache(cache_path) if (query is not None and cache_path) else {}
    state = {"queried": False, "dirty": False}

    def truth(address: str):
        """(ok, coords): ok=False on a transient exception (NOT evidence);
        ok=True with coords or None on a definitive hit/miss. Cached + throttled."""
        key = _norm(address)
        if key in cache:
            return True, cache[key]
        result = None
        try:
            for variant in _address_variants(address):
                if state["queried"]:
                    sleep(_MIN_INTERVAL_S)
                state["queried"] = True
                result = query(variant)
                if result:
                    break
        except Exception:
            return False, None
        cache[key] = list(result) if result else None
        state["dirty"] = True
        return True, cache[key]

    clean: list[Event] = []
    dropped: list = []
    for ev in events:
        if ev.lat is not None and ev.lng is not None and not _in_bbox(ev.lat, ev.lng):
            dropped.append((ev.id, "geo", "out-of-bbox"))
            ev.lat = ev.lng = None
        if ev.lat is not None and ev.lng is not None and ev.address and query is not None:
            ok, coords = truth(ev.address)
            if ok and coords:
                km = _haversine_km(ev.lat, ev.lng, coords[0], coords[1])
                if km > (STREET_KM if _has_street_number(ev.address) else VENUE_KM):
                    dropped.append((ev.id, "geo", f"far-from-address:{km:.1f}km"))
                    ev.lat = ev.lng = None
        if ev.address and not _address_ok(ev, query, truth):
            dropped.append((ev.id, "address", "unverified"))
            ev.raw.pop("location", None)        # mask stale text for the DC recheck
            ev.address = ""
            prov_clear(ev, "location")
        if not is_dc_relevant(ev):
            dropped.append((ev.id, "dc", "not-dc-after-validation"))
            continue
        clean.append(ev)
    if state["dirty"] and cache_path:
        try:
            save_cache(cache_path, cache)
        except OSError:
            pass
    return clean, dropped


def _address_ok(ev: Event, query, truth) -> bool:
    addr = ev.address
    if _has_zip(addr):
        return True
    if addr in SOURCE_HQ.values():
        return True
    if ev.lat is not None and ev.lng is not None:
        return True
    if query is None:
        return True                              # can't verify offline -> keep
    ok, coords = truth(addr)
    if not ok:
        return True                              # transient failure is not evidence
    return coords is not None                    # definitive miss -> unverified
