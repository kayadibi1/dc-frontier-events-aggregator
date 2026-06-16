"""The one normalized event schema shared across the pipeline (GOAL.md)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Event:
    id: str                         # stable id (Luma UID, source-agnostic)
    title: str
    start: str                      # ISO 8601
    source: str                     # source slug
    source_url: str = ""
    description: str = ""
    end: str | None = None
    tz: str | None = None
    venue_name: str = ""
    address: str = ""
    lat: float | None = None
    lng: float | None = None
    organizer: str = ""
    speakers: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    is_big_name: bool = False
    raw: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        d = asdict(self)
        d["speakers"] = json.dumps(self.speakers)
        d["topics"] = json.dumps(self.topics)
        d["raw"] = json.dumps(self.raw, default=str)
        d["is_big_name"] = 1 if self.is_big_name else 0
        return d

    @classmethod
    def from_row(cls, row) -> "Event":
        d = dict(row)
        for col in ("updated_at", "dedupe_key", "first_seen", "last_seen", "status"):
            d.pop(col, None)
        d["speakers"] = json.loads(d.get("speakers") or "[]")
        d["topics"] = json.loads(d.get("topics") or "[]")
        d["raw"] = json.loads(d.get("raw") or "{}")
        d["is_big_name"] = bool(d.get("is_big_name"))
        return cls(**d)
