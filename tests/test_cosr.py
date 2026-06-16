import os

from aggregator.config import Source
from aggregator.fetchers.cosr import parse_cosr_detail, parse_cosr_rss

SRC = Source("cosr", "Council on Strategic Risks", "cosr", 2, False,
             url="https://councilonstrategicrisks.org/category/events/feed/")

LINK = ("https://councilonstrategicrisks.org/2026/05/22/"
        "webinar-ai-in-professional-military-education-friend-foe-or-frenemy/")


def _read(n):
    with open(os.path.join(os.path.dirname(__file__), "fixtures", n), encoding="utf-8") as f:
        return f.read()


def test_rss_lists_event_items():
    items = parse_cosr_rss(_read("cosr_feed.xml"))
    assert len(items) >= 5
    assert any("AI in Professional Military Education" in t for t, _ in items)


def test_detail_uses_bold_event_date_not_publish_date():
    ev = parse_cosr_detail(SRC, "Webinar: AI in Professional Military Education",
                           LINK, _read("cosr_webinar_detail.html"), today="2026-06-01")
    assert ev is not None
    assert ev.start == "2026-06-04"          # bolded event date, NOT the May 22 publish date
    assert "ai" in ev.topics
    assert ev.source_url == LINK
    assert ev.id == ("cosr-webinar-ai-in-professional-military-education-"
                     "friend-foe-or-frenemy")


def test_detail_past_skipped():
    assert parse_cosr_detail(SRC, "x", LINK, _read("cosr_webinar_detail.html"),
                             today="2026-07-01") is None


def test_blog_post_without_event_date_skipped():
    assert parse_cosr_detail(SRC, "Some analysis post",
                             "https://councilonstrategicrisks.org/2026/01/01/post/",
                             "<html><body><p>No event date here.</p></body></html>",
                             today="2026-01-01") is None
