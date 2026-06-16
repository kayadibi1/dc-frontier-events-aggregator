"""Geocode event venue addresses -> (lat, lng) so scraped / think-tank events get
map pins, not just the feed events that ship an iCal GEO.

The pipeline already fills `ev.address` for every locatable event (a scraped venue,
else the host org's HQ from SOURCE_HQ); this turns that text address into
coordinates. Results are cached on disk (data/geocode_cache.json) keyed by the
normalized address, so each unique address hits the provider at most ONCE -- every
later build is cache-only, and a brand-new event geocodes itself automatically on
first sight. Provider is OSM Nominatim (free, no key); we honor its usage policy
with an identifying User-Agent and <=1 request/second. Best-effort: a failed lookup
leaves the event pin-less and never blocks the build. Both hits ([lat,lng]) and
misses (null) are cached so neither is re-queried.

Geocoding runs AFTER the DC/topic filter, purely to add coordinates -- it never
changes which events are kept (the filter's own GEO handling is untouched).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request

from .config import DC_BBOX
from .models import Event

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_CACHE = "data/geocode_cache.json"
# Nominatim asks for an identifying UA and no more than 1 request/second.
_UA = "dc-frontier-events/1.0 (https://events.emersus.ai; radar@emersus.ai)"
_MIN_INTERVAL_S = 1.1

# A street number followed by a street name -> the start of a postal address.
_STREET = re.compile(r"\b\d{1,6}\s+[A-Za-z]")
# Trailing room/floor/suite noise Nominatim chokes on ("... - 9th floor",
# ", Room 401-E"). Cuts from the unit word (with an optional ordinal) to the end.
_UNIT_TAIL = re.compile(
    r"[\s,;-]*(?:\d+\s*(?:st|nd|rd|th)?\s*)?\b(?:suite|ste|room|rm|floor|fl|unit)\b.*$",
    re.I)


def _norm(address: str) -> str:
    """Cache key: whitespace-collapsed, lowercased address (so trivially different
    spellings of the same string share a cache entry)."""
    return " ".join((address or "").split()).lower()


def _address_variants(address: str) -> list[str]:
    """Progressively simpler forms to try when the full string misses, in order:
      1. the full address;
      2. the full address with a trailing room/floor/suite cut off
         ("MLK Library, Room 401-E" -> "MLK Library");
      3. from the first street number onward, trailing unit noise cut
         ("Brookings ... Saul Auditorium 1775 Mass Ave NW ..." -> "1775 Mass Ave NW ...");
      4. the first comma-segment dropped, i.e. a leading org/building prefix
         ("CSET, Georgetown University, DC" -> "Georgetown University, DC").
    Deduped, order-preserving."""
    a = " ".join((address or "").split())
    out: list[str] = []

    def add(s: str) -> None:
        s = s.strip(" ,;-")
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)

    add(a)
    add(_UNIT_TAIL.sub("", a))
    m = _STREET.search(a)
    if m:
        add(_UNIT_TAIL.sub("", a[m.start():]))
    if "," in a:
        add(_UNIT_TAIL.sub("", a.split(",", 1)[1]))
    return out


def nominatim_query(address: str) -> tuple[float, float] | None:
    """Live OSM Nominatim lookup for one address, CONSTRAINED to the DC metro
    (countrycodes=us + a bounded viewbox over DC_BBOX). The constraint matters
    because the trimmed retry variants can be ambiguous -- e.g. an over-trimmed
    "Washington, DC" or a foreign venue must not resolve to the wrong city/country
    and get pinned. Returns (lat, lng), or None when there's no in-region match.
    Network / HTTP errors PROPAGATE so the caller can retry on a later build
    instead of caching a transient blip as a permanent miss."""
    qs = urllib.parse.urlencode({
        "q": address, "format": "json", "limit": 1,
        "countrycodes": "us",
        "viewbox": (f"{DC_BBOX['lng_min']},{DC_BBOX['lat_min']},"
                    f"{DC_BBOX['lng_max']},{DC_BBOX['lat_max']}"),
        "bounded": 1,   # only return results inside the viewbox
    })
    req = urllib.request.Request(f"{NOMINATIM_URL}?{qs}", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as r:   # network/HTTP error -> propagates
        data = json.load(r)
    if not data:
        return None                                       # genuine: no in-region match
    try:
        return float(data[0]["lat"]), float(data[0]["lon"])
    except (KeyError, ValueError, IndexError):
        return None


def load_cache(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"   # per-process temp: overlapping builds don't
    with open(tmp, "w", encoding="utf-8") as f:   # clobber each other's tmp / replace
        json.dump(cache, f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)   # atomic: never leave a half-written cache


def geocode_events(events: list[Event], cache_path: str = DEFAULT_CACHE,
                   query=nominatim_query, sleep=time.sleep) -> int:
    """Set ev.lat/ev.lng for every event that has an address but no coordinates,
    consulting the disk cache first and `query` (the live geocoder) only on a miss.
    `query`/`sleep` are injectable so tests run offline. Returns the count of
    events newly given coordinates. Existing coordinates (feed GEO) are never
    overwritten."""
    cache = load_cache(cache_path)
    dirty = False
    pinned = 0
    state = {"queried": False}

    def live(addr: str):
        if state["queried"]:
            sleep(_MIN_INTERVAL_S)       # throttle only BETWEEN live calls
        state["queried"] = True
        return query(addr)

    for ev in events:
        if (ev.lat is not None and ev.lng is not None) or not (ev.address or "").strip():
            continue
        key = _norm(ev.address)
        if key not in cache:
            # Variant generation is pure (no network) -> outside the try, so a bug
            # here fails loudly instead of masquerading as a transient miss.
            variants = _address_variants(ev.address)
            result = None
            try:
                # Try the full address, then progressively trimmed forms; stop at
                # the first that resolves.
                for variant in variants:
                    result = live(variant)
                    if result:
                        break
            except Exception:
                continue   # transient network failure: don't cache; retry next build
            cache[key] = list(result) if result else None
            dirty = True
        coords = cache.get(key)
        if coords:
            ev.lat, ev.lng = float(coords[0]), float(coords[1])
            pinned += 1
    if dirty:
        try:
            save_cache(cache_path, cache)
        except OSError:
            pass   # cache is best-effort; a write failure just re-geocodes next build
    return pinned


def scrub_far_geo(events: list[Event], bbox: dict = DC_BBOX) -> int:
    """Null out coordinates that fall outside the DC-metro bbox. A feed can ship a
    junk GEO (e.g. a virtual event carrying a mid-Pacific coordinate); the geocoder
    only bbox-constrains addresses IT resolves, so bad feed GEO would otherwise
    reach events.json / .ics / the map. Runs on the post-filter set, where an
    out-of-bbox pin is necessarily a virtual event's bogus coordinate (in-person
    out-of-DC events are already excluded by the filter's GEO rule). Returns the
    number of events whose pin was scrubbed."""
    n = 0
    for ev in events:
        if ev.lat is None or ev.lng is None:
            continue
        if not (bbox["lat_min"] <= ev.lat <= bbox["lat_max"]
                and bbox["lng_min"] <= ev.lng <= bbox["lng_max"]):
            ev.lat = ev.lng = None
            n += 1
    return n
