import json

from selectolax.parser import HTMLParser

from aggregator.emit import _li, write_json, write_map
from aggregator.models import Event


def sample():
    return [
        Event(id="dc2-1", title="AI Workshop", start="2026-06-10T23:00:00+00:00",
              source="DC2", source_url="https://luma.com/a", address="Arlington VA",
              lat=38.88, lng=-77.10, topics=["ai"]),
        Event(id="csis-1", title="Data Centers & AI", start="2026-06-04T14:30:00+00:00",
              source="csis", source_url="https://www.csis.org/events/x",
              is_big_name=True, lat=38.905, lng=-77.045, topics=["ai", "compute"]),
        Event(id="virt", title="Virtual Talk", start="2026-06-12", source="DC2"),  # no geo
    ]


def test_write_json_roundtrips(tmp_path):
    p = tmp_path / "events.json"
    n = write_json(sample(), str(p))
    assert n == 3
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert {d["id"] for d in data} == {"dc2-1", "csis-1", "virt"}
    csis = next(d for d in data if d["id"] == "csis-1")
    assert csis["layer"] == 2 and csis["is_big_name"] is True
    assert next(d for d in data if d["id"] == "dc2-1")["layer"] == 1


def test_write_map_interactive(tmp_path):
    p = tmp_path / "map.html"
    n = write_map(sample(), str(p), "2026-05-01")
    assert n == 2                       # geo events get map pins
    html = p.read_text(encoding="utf-8")
    tree = HTMLParser(html)
    assert "leaflet" in html.lower()
    assert tree.css_first("#map") is not None
    assert tree.css_first("#search") is not None
    assert len(tree.css(".flt-layer")) == 3           # layer filter checkboxes
    lis = tree.css("#list li.ev")
    assert len(lis) == 3                                # ALL events listed (incl. virtual)
    geo_lis = [li for li in lis if li.attributes.get("data-lat")]
    assert len(geo_lis) == 2                            # only geo ones carry coords
    assert "Data Centers" in html and "AI Workshop" in html and "Virtual Talk" in html


def test_map_blocks_dangerous_source_url(tmp_path):
    from aggregator.emit import _safe_url
    assert _safe_url("https://x.com/a") == "https://x.com/a"
    assert _safe_url("HTTP://x.com") == "HTTP://x.com"
    assert _safe_url("javascript:alert(1)") == ""
    assert _safe_url("data:text/html,x") == ""
    assert _safe_url(None) == ""
    # a script-scheme source_url must not surface as an href or data-url in the map
    p = tmp_path / "m.html"
    evs = [Event(id="x", title="t", start="2026-06-10", source="DC2",
                 source_url="javascript:alert(1)", lat=38.9, lng=-77.0, topics=["ai"])]
    write_map(evs, str(p), "2026-05-01")
    assert "javascript:alert" not in p.read_text(encoding="utf-8")


def test_map_handles_empty(tmp_path):
    p = tmp_path / "m.html"
    assert write_map([], str(p), "2026-05-01") == 0
    tree = HTMLParser(p.read_text(encoding="utf-8"))
    assert tree.css_first("#map") is not None
    assert len(tree.css("#list li.ev")) == 0
