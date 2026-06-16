import json

from aggregator.config import Source
from aggregator.extract import extract_events

SRC = Source("x", "X", "jsrender", 2, False, url="https://x.example")


def test_jsonld_layer():
    html = ('<script type="application/ld+json">{"@type":"Event",'
            '"name":"AI Policy Summit","startDate":"2026-07-01T13:00:00Z",'
            '"url":"https://x.example/e/summit","location":{"@type":"Place",'
            '"name":"Convention Center","address":"801 Mt Vernon Pl NW, Washington, DC"}}</script>')
    evs = extract_events(SRC, html, "2026-06-02")
    assert len(evs) == 1
    e = evs[0]
    assert e.title == "AI Policy Summit"
    assert e.start.startswith("2026-07-01")
    assert e.source == "x" and e.id == "x-summit"
    assert "Washington" in e.address
    assert {"ai", "policy"} & set(e.topics)


def test_nextdata_layer():
    payload = {"props": {"pageProps": {"data": {"events": [
        {"title": "Semiconductor Supply Workshop", "date": "2026-08-10",
         "slug": "https://x.example/e/semi"},
        {"title": "Robotics Day", "date": "2026-08-12", "slug": "https://x.example/e/robo"}]}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    evs = extract_events(SRC, html, "2026-06-02")
    titles = {e.title for e in evs}
    assert "Semiconductor Supply Workshop" in titles and "Robotics Day" in titles
    assert any("semiconductor" in e.topics for e in evs)


def test_cards_layer_absolutizes_relative_links():
    html = ('<div>'
            '<article><a href="/e/chip-policy"><h3>Chip Export Controls Briefing</h3></a>'
            '<time datetime="2026-09-05T10:00:00-04:00">Sep 5</time></article>'
            '<article><a href="https://x.example/e/ai-safety"><h3>AI Safety Forum</h3></a>'
            '<time datetime="2026-09-06T10:00:00-04:00">Sep 6</time></article></div>')
    evs = extract_events(SRC, html, "2026-06-02")
    titles = {e.title for e in evs}
    assert "Chip Export Controls Briefing" in titles and "AI Safety Forum" in titles
    chip = next(e for e in evs if "Chip" in e.title)
    assert chip.source_url == "https://x.example/e/chip-policy"
    assert chip.start == "2026-09-05T10:00:00-04:00"
