"""Field-level provenance: record which rung of the confidence ladder a value came
from (`ev.raw["provenance"][field] = tag`) and render a marker / notes for the
DERIVED rungs, so a guess is never shown as a scraped fact. Renderers are defensive
-- they only fire when the field is still present, so a value that validation later
cleared/downgraded produces no stale label.
"""
from __future__ import annotations

from .models import Event

# Derived tags that earn a user-facing label (high-confidence tags render nothing).
_MARKER = {("location", "hq"): "📍approx"}
_NOTE = {
    ("location", "hq"): "location approximate (host venue)",
    ("time", "assumed_et"): "time assumed ET",
    ("speakers", "extracted"): "speakers auto-extracted",
}


def prov_set(ev: Event, field: str, tag: str) -> None:
    ev.raw.setdefault("provenance", {})[field] = tag


def prov_clear(ev: Event, field: str) -> None:
    ev.raw.get("provenance", {}).pop(field, None)


def prov_get(ev: Event, field: str):
    return ev.raw.get("provenance", {}).get(field)


def _field_present(ev: Event, field: str) -> bool:
    if field == "location":
        return bool(ev.address)
    if field == "time":
        return "T" in (ev.start or "")
    if field == "speakers":
        return bool(ev.speakers)
    return True


def marker(ev: Event) -> str:
    """Compact one-line surface marker (location only today)."""
    for (field, tag), text in _MARKER.items():
        if prov_get(ev, field) == tag and _field_present(ev, field):
            return text
    return ""


def notes(ev: Event) -> list[str]:
    """All derived labels, for the .ics DESCRIPTION + json consumers."""
    out = []
    for (field, tag), text in _NOTE.items():
        if prov_get(ev, field) == tag and _field_present(ev, field):
            out.append(text)
    return out
