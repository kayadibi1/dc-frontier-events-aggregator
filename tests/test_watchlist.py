import asyncio

import aggregator.config as config
from aggregator.config import Source
from aggregator.fetchers.watchlist import fetch_watchlist

SRC = Source("watchlist", "Curated (marquee)", "watchlist", 2, True)


def test_watchlist_keeps_only_future_live_entries(monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_EVENTS", [
        {"name": "OpenAI Workshop: Building with GPT", "date": "2026-07-01",
         "venue": "901 F St NW, Washington, DC", "url": "https://live/1", "topics": ["ai"]},
        {"name": "Old AI Event", "date": "2020-01-01", "venue": "X", "url": "https://live/2"},
        {"name": "Dead Link AI Event", "date": "2026-07-02", "venue": "Y", "url": "https://dead/3"},
    ])

    async def link_ok(url):
        return "dead" not in url

    res = asyncio.run(fetch_watchlist(SRC, link_ok=link_ok, today="2026-06-02"))
    titles = {e.title for e in res.events}
    assert titles == {"OpenAI Workshop: Building with GPT"}    # past + dead dropped
    e = res.events[0]
    assert e.id.startswith("watchlist-")
    assert "Washington, DC" in e.address
    assert "ai" in e.topics
