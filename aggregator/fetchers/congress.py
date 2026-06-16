"""Layer-2 adapter: U.S. Congress committee hearings/meetings (congress.gov API).

The highest-signal DC policy source -- AI / semiconductor / export-control hearings
at House & Senate committees, on Capitol Hill. The api.congress.gov committee-meeting
LIST carries only ids (no title/date), so we pull the most-recently-updated meetings
and fetch their DETAILS concurrently, keeping only the SCHEDULED, future-dated,
ON-TOPIC ones (Congress runs hundreds of meetings -- pre-filtering by title topic
keeps the volume sane and avoids enriching hundreds of off-topic pages). Every
hearing is in DC, so the address is built from the hearing room; witnesses become
speakers. Needs CONGRESS_API_KEY in the env -- without it the source is skipped
(quarantined, never fabricated). `parse_congress_meeting` is pure (offline-tested
against a saved REAL detail fixture).
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

import httpx

from ..config import Source
from ..models import Event
from ..normalize import detect_topics
from .base import SourceResult

API = "https://api.congress.gov/v3"
TIMEOUT = 30.0
LIST_LIMIT = 250          # one page of the most-recently-updated meetings
CONCURRENCY = 12
UA = "dc-frontier-events/1.0 (+https://events.emersus.ai)"
_HONORIFIC = re.compile(r"^(?:Mr\.|Mrs\.|Ms\.|Dr\.|Hon\.|The Honorable|Rep\.|Sen\.)\s+", re.I)


def parse_congress_meeting(source: Source, m: dict, today_iso: str) -> Event | None:
    """A committee-meeting detail -> Event, or None if it's not a scheduled, future,
    on-topic hearing. The title topic-prefilter is deliberate: Congress runs hundreds
    of meetings and only the explicitly AI/chip-titled ones belong on this radar."""
    if not isinstance(m, dict) or m.get("meetingStatus") != "Scheduled":
        return None
    title = (m.get("title") or "").strip().strip('"').strip()
    date = (m.get("date") or "").strip()
    eid = str(m.get("eventId") or "")
    if not title or len(title) < 6 or not date or not eid:
        return None
    if date[:10] < today_iso:                  # upcoming only
        return None
    topics = detect_topics(title)
    if not topics:                             # off-topic hearing -> skip
        return None
    loc = m.get("location") or {}
    building = (loc.get("building") or "") if isinstance(loc, dict) else ""
    room = (loc.get("room") or "") if isinstance(loc, dict) else ""
    where = " ".join(p for p in (building, room) if p).strip()
    address = ", ".join(p for p in (where, "Washington, DC") if p)
    committees = m.get("committees") or []
    organizer = (committees[0].get("name") if committees and isinstance(committees[0], dict)
                 else f"U.S. {m.get('chamber') or 'Congress'}")
    # A "business meeting" / markup carries its ENTIRE bill agenda as the title.
    # Detecting topics on that blob false-matches stray keywords (an Arms Export
    # Control Act bill -> 'policy', "Brazilian Amazon" -> a big-name star). Keep a
    # markup only when the agenda names a genuinely AI/chip bill (a CORE topic,
    # not the collision-prone 'policy'/'data-science'), and replace the agenda
    # blob with a clean committee label (full agenda stays at source_url).
    m_type = m.get("type") or ""
    if re.search(r"business meeting|markup", m_type, re.I):
        if not (set(topics) & {"ai", "ml", "llm", "deep-learning", "semiconductor", "compute"}):
            return None
        title = f"{organizer}: business meeting"
    speakers = []
    for w in (m.get("witnesses") or []):
        nm = _HONORIFIC.sub("", (w.get("name") or "").strip()) if isinstance(w, dict) else ""
        if nm:
            speakers.append(nm)
    chamber = (m.get("chamber") or "house").lower()
    # congress.gov's canonical event page. NOT /committee-meeting/<c>/<chamber>/<id>
    # (that 404s); the real shape is /event/<c>th-Congress/<chamber>-event/<id>.
    # Prefer the API's own congress.gov video URL when present, else build it.
    url = f"https://www.congress.gov/event/{m.get('congress')}th-Congress/{chamber}-event/{eid}"
    for v in (m.get("videos") or []):
        vu = (v.get("url") or "") if isinstance(v, dict) else ""
        if "congress.gov/event/" in vu:
            url = vu
            break
    ev = Event(
        id=f"congress-{eid}",
        title=title,
        start=date,
        source=source.slug,
        source_url=url,
        organizer=organizer or "U.S. Congress",
        venue_name=building,
        address=address,
        speakers=speakers,
        topics=topics,
    )
    # Congressional hearings are publicly webcast; the congress.gov meeting page
    # hosts the official video. Institutional fact, not a per-event scrape. Exclude
    # business-meetings/markups (relabeled above; not uniformly webcast).
    if not re.search(r"business meeting|markup", m_type, re.I):
        ev.raw["remote"] = True
        ev.raw["watch_url"] = url
    return ev


async def fetch_congress(source: Source) -> SourceResult:
    key = os.environ.get("CONGRESS_API_KEY")
    if not key:
        return SourceResult(source, [], None, "no CONGRESS_API_KEY (set in env to enable)")
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=TIMEOUT,
                                     follow_redirects=True) as c:
            r = await c.get(f"{API}/committee-meeting",
                            params={"limit": LIST_LIMIT, "api_key": key, "format": "json"})
            if r.status_code != 200:
                return SourceResult(source, [], r.status_code, f"HTTP {r.status_code}")
            meetings = r.json().get("committeeMeetings", [])
            sem = asyncio.Semaphore(CONCURRENCY)

            async def detail(item: dict) -> dict | None:
                async with sem:
                    try:
                        rr = await c.get(f"{item['url']}&api_key={key}")
                        return rr.json().get("committeeMeeting", {}) if rr.status_code == 200 else None
                    except Exception:  # noqa: BLE001
                        return None

            details = await asyncio.gather(*[detail(m) for m in meetings])
    except Exception as e:  # noqa: BLE001
        return SourceResult(source, [], None, repr(e))
    events = []
    for d in details:
        ev = parse_congress_meeting(source, d, today) if d else None
        if ev:
            events.append(ev)
    return SourceResult(source, events, 200, None)
