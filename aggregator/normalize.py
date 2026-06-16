"""Parse raw .ics text into normalized Event objects."""

from __future__ import annotations

import re
from datetime import date, datetime

from icalendar import Calendar

from .config import TOPIC_PATTERNS, Source
from .models import Event

_URL_IN_DESC = re.compile(r"information at:\s*(https?://\S+)", re.I)
_ADDR_IN_DESC = re.compile(r"Address:\s*(.+?)(?:\n\n|\Z)", re.I | re.S)
_TOPIC_RES = {t: re.compile(p, re.I) for t, p in TOPIC_PATTERNS.items()}


def _iso(dt) -> tuple[str, str | None]:
    """Return (iso_string, tzname or None) for a date or datetime."""
    if isinstance(dt, datetime):
        tzname = None
        if dt.tzinfo is not None:
            tzname = getattr(dt.tzinfo, "key", None) or dt.tzname() or str(dt.tzinfo)
        return dt.isoformat(), tzname
    if isinstance(dt, date):
        return dt.isoformat(), None
    return str(dt), None


def _geo(comp) -> tuple[float | None, float | None]:
    g = comp.get("geo")
    if g is None:
        return None, None
    lat = getattr(g, "latitude", None)
    lng = getattr(g, "longitude", None)
    if lat is not None and lng is not None:
        try:
            return float(lat), float(lng)
        except (TypeError, ValueError):
            pass
    try:
        parts = re.split(r"[;,]", str(g))
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None, None


def detect_topics(text: str) -> list[str]:
    """Canonical topic tags matched in free text. Shared by all adapters."""
    low = text.lower()
    return [t for t, rx in _TOPIC_RES.items() if rx.search(low)]


def _clean_uid(uid: str, fallback: str) -> str:
    uid = (uid or "").strip()
    if not uid:
        return fallback
    # Strip the host part of feed UIDs ('event_123@meetup.com' -> 'event_123')
    # so ids stay stable if a platform changes its UID domain. (Originally for
    # Luma's 'evt-X@events.lu.ma'; Luma now arrives via JSON with bare ids.)
    return uid.split("@", 1)[0]


def parse_ics(source: Source, ics_text: str) -> list[Event]:
    cal = Calendar.from_ical(ics_text)
    events: list[Event] = []
    for i, comp in enumerate(cal.walk("VEVENT")):
        title = str(comp.get("summary", "")).strip()
        dtstart = comp.get("dtstart")
        if dtstart is None or not title:
            continue  # an event with no start or title is unusable

        desc = str(comp.get("description", "")).replace("\\n", "\n").strip()
        loc = str(comp.get("location", "")).strip()

        start_iso, tz = _iso(dtstart.dt)
        end_iso = None
        dtend = comp.get("dtend")
        if dtend is not None:
            end_iso, _ = _iso(dtend.dt)

        lat, lng = _geo(comp)

        m = _URL_IN_DESC.search(desc)
        url_prop = str(comp.get("url", "")).strip()
        if m:
            source_url = m.group(1).rstrip(".")              # Luma "information at: <url>"
        elif url_prop.startswith("http"):
            source_url = url_prop                            # iCal URL property (Localist, etc.)
        elif loc.startswith("http"):
            source_url = loc
        else:
            source_url = ""

        # LOCATION is sometimes a URL, sometimes a real address.
        address = "" if loc.startswith("http") else loc
        if not address:
            am = _ADDR_IN_DESC.search(desc)
            if am:
                cand = am.group(1).replace("\n", ", ").strip(", ").strip()
                if cand and "check event page" not in cand.lower():
                    address = cand

        organizer = comp.get("organizer")
        org = str(organizer.params.get("CN", "")) if organizer is not None else ""

        uid = _clean_uid(str(comp.get("uid", "")), f"{source.slug}-{i}")

        events.append(
            Event(
                id=uid,
                title=title,
                start=start_iso,
                end=end_iso,
                tz=tz,
                source=source.slug,
                source_url=source_url,
                description=desc,
                venue_name=address.split(",")[0].strip() if address else "",
                address=address,
                lat=lat,
                lng=lng,
                organizer=org,
                topics=detect_topics(f"{title} {desc}"),
                raw={"location": loc, "calendar": source.name},
            )
        )
    return events
