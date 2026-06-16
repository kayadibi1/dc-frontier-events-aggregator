import os

from aggregator.config import Source
from aggregator.fetchers.aisf import (
    _title_from_slug,
    parse_aisf_detail,
    parse_aisf_listing,
)

SRC = Source("aisf", "AI Security Forum", "aisf", 2, True,
             url="https://aisecurity.forum/events")


def _read(n):
    with open(os.path.join(os.path.dirname(__file__), "fixtures", n), encoding="utf-8") as f:
        return f.read()


def test_listing_finds_dc_forum_slugs():
    slugs = parse_aisf_listing(_read("aisf_events.html"))
    assert "dc-ai-security-forum-26" in slugs
    assert "dc-ai-security-forum-25" in slugs        # past edition discovered too


def test_title_from_slug():
    assert _title_from_slug("dc-ai-security-forum-26") == "DC AI Security Forum 2026"


def test_parse_detail_dc_26():
    ev = parse_aisf_detail(SRC, "dc-ai-security-forum-26",
                           _read("aisf_dc_detail.html"), today="2026-06-15")
    assert ev is not None
    assert ev.start == "2026-06-18"                  # from the config block
    assert ev.title == "DC AI Security Forum 2026"   # deterministic, no em dash
    assert "ai" in ev.topics
    assert "Washington, DC" in ev.address            # Conrad Washington, DC
    assert ev.source_url == "https://aisecurity.forum/events/dc-ai-security-forum-26"
    assert ev.id == "aisf-dc-ai-security-forum-26"


def test_parse_detail_past_skipped():
    assert parse_aisf_detail(SRC, "dc-ai-security-forum-26",
                             _read("aisf_dc_detail.html"), today="2027-01-01") is None
