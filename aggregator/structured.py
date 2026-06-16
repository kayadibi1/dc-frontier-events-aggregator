"""Authoritative event data from a detail page's schema.org markup.

Some Layer-2 detail pages embed a schema.org `Event` as JSON-LD. When present it
is authoritative for venue, virtual-vs-physical, and times. `extract_structured`
returns ONLY fields it confidently finds. JSON-LD `Event` is the ONLY source
allowed to set start/end/address; generic page metadata (og:*,
article:published_time, datePublished) is ignored.
"""
from __future__ import annotations

import json

from selectolax.parser import HTMLParser


def _iter_jsonld(tree: HTMLParser):
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text() or "")
        except (ValueError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                yield item


def _types(node: dict) -> str:
    t = node.get("@type")
    return " ".join(t) if isinstance(t, list) else str(t or "")


def _format_address(postal) -> str:
    if isinstance(postal, str):
        return postal.strip()
    if not isinstance(postal, dict):
        return ""
    parts = [postal.get(k) for k in
             ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
    return ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


def _parse_location(loc) -> dict:
    items = loc if isinstance(loc, list) else [loc]
    has_place = has_virtual = False
    venue_name = address = ""
    for it in items:
        if not isinstance(it, dict):
            continue
        ts = _types(it)
        if "VirtualLocation" in ts:
            has_virtual = True
        elif "Place" in ts or it.get("address"):
            has_place = True
            venue_name = venue_name or (it.get("name") or "").strip()
            address = address or _format_address(it.get("address") or it)
    out: dict = {}
    if venue_name:
        out["venue_name"] = venue_name
    if address:
        out["address"] = address
    if has_virtual and has_place:
        out["attendance_mode"] = "mixed"
    elif has_virtual:
        out["virtual"] = True
        out["attendance_mode"] = "online"
    out["_has_place"] = has_place      # internal hint for attendance-mode refinement
    return out


def _event_fields(node: dict) -> dict:
    out: dict = {}
    for key, prop in (("start", "startDate"), ("end", "endDate")):
        v = node.get(prop)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    name = node.get("name")
    if isinstance(name, str) and name.strip():
        out["name"] = name.strip()
    loc = node.get("location")
    has_place = False
    if loc is not None:
        parsed = _parse_location(loc)
        has_place = parsed.pop("_has_place", False)
        out.update(parsed)
    # eventAttendanceMode refines virtual even without a VirtualLocation node.
    mode = node.get("eventAttendanceMode")
    if isinstance(mode, str):
        if "Online" in mode and not has_place and "virtual" not in out:
            out["virtual"] = True
            out["attendance_mode"] = "online"
        elif "Mixed" in mode and has_place:
            out["attendance_mode"] = "mixed"
    perf = node.get("performer")
    if perf is not None:
        names = []
        for p in (perf if isinstance(perf, list) else [perf]):
            nm = p.get("name") if isinstance(p, dict) else (p if isinstance(p, str) else None)
            if isinstance(nm, str) and nm.strip():
                names.append(nm.strip())
        if names:
            out["speakers"] = names
    return out


def extract_structured(html: str) -> dict:
    """The FIRST schema.org Event's authoritative fields, or {} if none."""
    tree = HTMLParser(html or "")
    node = next((n for n in _iter_jsonld(tree) if "Event" in _types(n)), None)
    return _event_fields(node) if node is not None else {}


def extract_all_events(html: str) -> list[dict]:
    """Every schema.org Event on the page (for listing pages that embed many),
    each with its `url` when present. Used by the jsrender extractor."""
    tree = HTMLParser(html or "")
    events = []
    for n in _iter_jsonld(tree):
        if "Event" in _types(n):
            fields = _event_fields(n)
            u = n.get("url")
            if isinstance(u, str) and u.strip():
                fields["url"] = u.strip()
            events.append(fields)
    return events
