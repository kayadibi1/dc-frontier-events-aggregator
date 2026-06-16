from aggregator.config import Source
from aggregator.fetchers.brookings import parse_brookings_listing

SRC = Source("brookings", "Brookings", "brookings", 2, True,
             url="https://www.brookings.edu/events/")

# Mirrors the VERIFIED real Brookings listing DOM (confirmed against a live fetch
# 2026-05-30): article cards, title in a heading, date as free text inside the
# card ("June 10 2026", no comma; or "July 15, 2026" with comma), an
# a[href*='/events/'] link. A sub-brand card uses /event/ (singular) and must be
# excluded; an undated card must be skipped.
LISTING = """
<div class="grid">
  <article>
    <a href="https://www.brookings.edu/events/ai-and-economic-mobility/"></a>
    <h3>AI and economic mobility: Opportunities and challenges</h3>
    <a href="https://www.brookings.edu/topics/artificial-intelligence/">AI</a>
    <span>June 10 2026</span>
  </article>
  <article>
    <a href="https://www.brookings.edu/events/the-powell-years-at-the-fed/"></a>
    <h3>The Powell years at the Fed: A retrospective</h3>
    <span>June 02 2026</span>
  </article>
  <article>
    <a href="https://www.brookings.edu/events/chip-export-controls-panel/"></a>
    <h2>Semiconductor export controls and the CHIPS Act</h2>
    <span>July 15, 2026</span>
  </article>
  <article>
    <a href="https://www.hamiltonproject.org/event/social-media-costs/"></a>
    <h3>Understanding the costs of social media</h3>
    <span>June 02 2026</span>
  </article>
  <article>
    <a href="https://www.brookings.edu/events/no-date-event/"></a>
    <h3>Undated event</h3>
  </article>
</div>
"""


def test_excludes_subbrand_and_undated_and_dedupes():
    events = parse_brookings_listing(SRC, LISTING)
    ids = {e.id for e in events}
    # Hamilton Project (/event/ singular) excluded; undated skipped
    assert ids == {
        "brookings-ai-and-economic-mobility",
        "brookings-the-powell-years-at-the-fed",
        "brookings-chip-export-controls-panel",
    }


def test_date_formats_with_and_without_comma():
    by_id = {e.id: e for e in parse_brookings_listing(SRC, LISTING)}
    assert by_id["brookings-ai-and-economic-mobility"].start == "2026-06-10"     # no comma
    assert by_id["brookings-chip-export-controls-panel"].start == "2026-07-15"   # comma


def test_fields_and_topics():
    by_id = {e.id: e for e in parse_brookings_listing(SRC, LISTING)}
    ai = by_id["brookings-ai-and-economic-mobility"]
    assert ai.title == "AI and economic mobility: Opportunities and challenges"
    assert ai.source == "brookings" and ai.organizer == "Brookings"
    assert ai.source_url == "https://www.brookings.edu/events/ai-and-economic-mobility/"
    assert "ai" in ai.topics
    assert "semiconductor" in by_id["brookings-chip-export-controls-panel"].topics
    # off-topic event still parsed (topic filtering happens later in the pipeline)
    assert by_id["brookings-the-powell-years-at-the-fed"].topics == []
