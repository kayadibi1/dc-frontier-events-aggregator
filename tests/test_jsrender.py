import asyncio

import aggregator.fetchers.jsrender as J
from aggregator.config import Source

SRC = Source("x", "X", "jsrender", 2, False, url="https://x.example/events")


def test_jsrender_extracts_from_rendered_html(monkeypatch):
    async def fake_render(url, wait_for=None, timeout_ms=15000):
        return ('<script type="application/ld+json">{"@type":"Event",'
                '"name":"Rendered AI Summit","startDate":"2026-07-01",'
                '"url":"https://x.example/e/s"}</script>')
    monkeypatch.setattr(J, "render", fake_render)
    res = asyncio.run(J.fetch_jsrender(SRC))
    assert res.ok
    assert res.events[0].title == "Rendered AI Summit"


def test_jsrender_empty_render_quarantines(monkeypatch):
    async def empty(url, wait_for=None, timeout_ms=15000):
        return ""
    monkeypatch.setattr(J, "render", empty)
    res = asyncio.run(J.fetch_jsrender(SRC))
    assert not res.ok and res.events == []
