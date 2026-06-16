"""Shared adapter result type."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Source
from ..models import Event


@dataclass
class SourceResult:
    source: Source
    events: list  # list[Event]
    status: int | None
    error: str | None = None

    @property
    def healthy(self) -> bool:
        """Fetched without an adapter/network error, even if no events exist."""
        return self.error is None

    @property
    def ok(self) -> bool:
        """Produced at least one event. Empty-but-successful fetches are healthy."""
        return self.healthy and len(self.events) > 0

    @property
    def reason(self) -> str:
        if self.error:
            return self.error
        if not self.events:
            return f"empty (HTTP {self.status}, 0 events)"
        return "ok"
