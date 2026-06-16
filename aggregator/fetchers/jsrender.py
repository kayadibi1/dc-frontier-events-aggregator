"""Generic adapter for JS-rendered event pages.

Renders the page (render.py) then extracts events (extract.py). New JS sites are a
`Source(kind="jsrender")` row plus an optional `config.JSRENDER_HINTS` entry -- no new
code. An empty render (JS failure / bot block) quarantines the source; never fabricates.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import JSRENDER_HINTS, Source
from ..extract import extract_events
from ..render import render
from .base import SourceResult


async def fetch_jsrender(source: Source) -> SourceResult:
    hints = JSRENDER_HINTS.get(source.slug, {})
    html = await render(source.url, wait_for=hints.get("wait_for"))
    if not html:
        # 204 (not None/5xx) so the retry layer does NOT re-render a hard-blocked page.
        return SourceResult(source, [], 204, "render returned empty (JS/blocked)")
    today = datetime.now(timezone.utc).date().isoformat()
    return SourceResult(source, extract_events(source, html, today), 200, None)
