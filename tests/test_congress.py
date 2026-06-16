import json
import os

from aggregator.config import Source
from aggregator.fetchers.congress import parse_congress_meeting

SRC = Source("congress", "U.S. Congress", "congress", 2, True)


def _load(n):
    p = os.path.join(os.path.dirname(__file__), "fixtures", f"congress_meeting_{n}.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_parses_ai_hearing():
    ev = parse_congress_meeting(SRC, _load(0), "2026-06-02")
    assert ev is not None
    assert ev.id == "congress-119338"
    assert "AI-Ready America" in ev.title
    assert not ev.title.startswith('"')                 # surrounding quotes stripped
    assert ev.start == "2026-06-03T14:15:00Z"
    assert "ai" in ev.topics
    assert "Washington, DC" in ev.address and "Rayburn" in ev.address
    assert ev.source == "congress"
    assert ev.source_url.startswith("https://www.congress.gov/")
    assert ev.speakers                                  # witnesses captured as speakers


def test_skips_past_meeting():
    assert parse_congress_meeting(SRC, _load(0), "2026-12-01") is None   # hearing already happened


def test_cancelled_meeting_skipped():
    m = dict(_load(0))
    m["meetingStatus"] = "Cancelled"
    assert parse_congress_meeting(SRC, m, "2026-06-02") is None


def test_offtopic_title_dropped():
    m = dict(_load(0))
    m["title"] = '"Agriculture, Rural Development Appropriations Markup"'
    assert parse_congress_meeting(SRC, m, "2026-06-02") is None


def test_business_meeting_without_ai_dropped():
    # fixture 2 is a real "Open Business Meeting" (agenda-as-title). Give it an
    # agenda that trips a *non-core* keyword the way the real S.4726 foreign-
    # relations markup did ("Arms Export Control Act" -> 'policy'). That stray
    # match used to KEEP it; a procedural markup with no genuine AI/chip bill
    # must now be dropped.
    m = dict(_load(2))
    m["title"] = ("Business meeting to consider S.10, to amend the Arms Export "
                  "Control Act, and S.11, to protect the Brazilian Amazon.")
    assert parse_congress_meeting(SRC, m, "2026-06-02") is None


def test_business_meeting_with_ai_kept_and_titled_cleanly():
    m = dict(_load(2))
    # an agenda that genuinely includes an AI bill, plus stray keywords that used
    # to cause false matches (Arms Export Control Act -> 'policy', Brazilian
    # Amazon -> 'big:Amazon').
    m["title"] = ('Business meeting to consider S.1, the Artificial Intelligence '
                  'Research Act, S.2, to amend the Arms Export Control Act, and '
                  'S.3, to protect the Brazilian Amazon.')
    ev = parse_congress_meeting(SRC, m, "2026-06-02")
    assert ev is not None
    assert "ai" in ev.topics                              # genuine AI bill kept it
    # title is the clean committee label, NOT the agenda blob
    assert ev.title == "Senate Commerce, Science, and Transportation: business meeting"
    assert "S.1" not in ev.title and "Amazon" not in ev.title
    assert len(ev.title) < 80


def test_hearing_is_remote_with_meeting_page():
    from aggregator.remote import is_remote, safe_watch_url
    ev = parse_congress_meeting(SRC, _load(0), "2026-06-02")
    assert is_remote(ev) is True                          # hearings are webcast
    assert safe_watch_url(ev) == ev.source_url            # the congress.gov page
    assert ev.source_url.startswith("https://www.congress.gov/")


def test_markup_not_remote():
    m = dict(_load(2))
    m["title"] = ("Business meeting to consider S.1, the Artificial Intelligence "
                  "Research Act.")
    ev = parse_congress_meeting(SRC, m, "2026-06-02")
    assert ev is not None                                 # kept (genuine AI bill)
    assert not ev.raw.get("remote")                       # but markups are not flagged
