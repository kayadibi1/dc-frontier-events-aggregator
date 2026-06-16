"""Relevance scoring (GOAL: rank by relevance + proximity + big name).

Pure functions over normalized Events so they are trivially testable. Weights
are interpretable: a big-name event dominates; on-topic + upcoming + close-to-DC
add up underneath it.
"""

from __future__ import annotations

import math
import re

from .models import Event

DC_CENTER = (38.9007, -77.0339)  # downtown DC
W_TOPIC = 8.0       # per distinct real topic
W_BIG = 50.0        # is_big_name (GOAL's first-class signal) -- dominates
W_UPCOMING = 20.0   # event is today or later
W_PROX_MAX = 5.0    # at DC center; linearly to 0 by ~40 km out

# Event-type weighting, tuned for an UPSKILLING radar with a policy/strategy angle:
# prioritize hands-on learning + frontier/policy substance; downrank (but keep)
# pure networking. is_big_name still dominates so a marquee-org event of any type
# floats to the top.
W_HANDSON = 14.0    # workshops, hackathons, "laptop required" -- build skills
W_POLICY_EVENT = 12.0  # firesides, panels, testimony, think-tank substance
W_NETWORKING = -18.0   # parties/mixers/happy hours -- downranked, not removed
W_POLICY_TOPIC = 6.0   # bonus for the user's focus: policy / semiconductor topics

# Checked against title + description (lowercased). Order = precedence:
# hands-on beats policy beats networking (a "policy workshop" is hands-on; a
# "fireside happy hour" is policy). Keep "meetup"/"demo night" OUT of networking
# -- those are community-talk learning, not pure socializing.
_HANDSON = re.compile(
    r"\bworkshop\b|hackathon|hack night|\bbootcamp\b|boot camp|laptop required|"
    r"code-?along|build session|hands-?on|\btutorial\b|\btraining\b|"
    r"build with|build your|deploy your|code lab|cloud lab", re.I)
_POLICY_EVENT = re.compile(
    r"fireside|\bpanel\b|\btestimony\b|\bhearing\b|briefing|keynote|symposium|"
    r"\bforum\b|\bsummit\b|roundtable|in conversation|distinguished lecture|"
    r"\bpolicy\b|governance|export control", re.I)
_NETWORKING = re.compile(
    r"happy hour|\bmixer\b|launch party|\bsoir|\breception\b|\bbrunch\b|cocktail|"
    r"wine tasting|\bgala\b|networking|pitch party|\bparty\b|\bsocial\b|"
    r"co-?working|\bdrinks\b|founders friday|founders dinner|founders breakfast|"
    r"game night|meet ?(?:&|and) ?greet|\bnerdworking\b", re.I)
_POLICY_TOPICS = {"policy", "semiconductor"}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _real_topics(ev: Event) -> int:
    return sum(1 for t in ev.topics if not t.startswith("big:"))


def event_kind(ev: Event) -> str:
    """Classify an event for ranking: 'handson' | 'policy' | 'networking' |
    'talk'. Precedence: hands-on > policy > networking > (neutral) talk."""
    blob = f"{ev.title} {ev.description}"
    if _HANDSON.search(blob):
        return "handson"
    if _POLICY_EVENT.search(blob):
        return "policy"
    if _NETWORKING.search(blob):
        return "networking"
    return "talk"


def score_event(ev: Event, today_iso: str) -> float:
    s = W_TOPIC * _real_topics(ev)
    if ev.is_big_name:
        s += W_BIG
    if (ev.start or "")[:10] >= today_iso:
        s += W_UPCOMING
    if ev.lat is not None and ev.lng is not None:
        d = _haversine_km(ev.lat, ev.lng, *DC_CENTER)
        s += max(0.0, W_PROX_MAX * (1 - d / 40.0))
    # Event-type weighting (upskilling + policy angle).
    s += {"handson": W_HANDSON, "policy": W_POLICY_EVENT,
          "networking": W_NETWORKING}.get(event_kind(ev), 0.0)
    # Bonus for the user's focus areas.
    if any(t in _POLICY_TOPICS for t in ev.topics):
        s += W_POLICY_TOPIC
    return round(s, 2)


def top_upcoming(events: list[Event], today_iso: str, n: int = 25) -> list[Event]:
    upcoming = [e for e in events if (e.start or "")[:10] >= today_iso]
    upcoming.sort(key=lambda e: (-score_event(e, today_iso), e.start or ""))
    return upcoming[:n]
