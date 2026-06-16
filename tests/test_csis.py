from aggregator.config import Source
from aggregator.fetchers.csis import parse_csis_listing, _parse_when

SRC = Source("csis", "CSIS", "csis", 2, True, url="https://www.csis.org/events")

# Mirrors the real CSIS DOM: an empty image anchor + a title anchor to the same
# /events/<slug>, an <h3> title, a date+time line, and a /programs/ host link.
LISTING = """
<div class="grid">
  <article class="ts-card-event-sm mb-xl relative">
    <a href="/events/data-centers-ai-future"></a>
    <h3 class="headline-sm">Data Centers, AI, and the Future of U.S. Strategy</h3>
    <a href="/events/data-centers-ai-future">Data Centers, AI, and the Future of U.S. Strategy</a>
    <span>June 3, 2026 - 3:30 - 4:45 pm EDT</span>
    <a href="/programs/strategic-technologies-program">Strategic Technologies Program</a>
  </article>
  <article class="ts-card-event-sm mb-xl relative">
    <a href="/events/data-centers-ai-future"></a>
    <h3 class="headline-sm">Data Centers, AI, and the Future of U.S. Strategy</h3>
    <span>June 3, 2026 - 3:30 - 4:45 pm EDT</span>
  </article>
  <article class="ts-card-event-lg">
    <h3 class="headline-sm">Energy Shots: Running on Empty</h3>
    <a href="/events/energy-shots-running-empty">Energy Shots: Running on Empty</a>
    <span>May 29, 2026 - 9:30 am</span>
    <a href="/programs/energy-security">Energy Security Program</a>
  </article>
  <article class="ts-card-event-sm">
    <h3 class="headline-sm">Undated Placeholder</h3>
    <a href="/events/undated">Undated Placeholder</a>
  </article>
</div>
"""


def test_when_parsing():
    # pm + explicit EDT -> 24h with offset
    assert _parse_when("June 3, 2026 - 3:30 - 4:45 pm EDT") == ("2026-06-03T15:30:00-04:00", "EDT")
    # am with no explicit zone -> default to US Eastern (CSIS is always ET); summer -> EDT
    assert _parse_when("May 29, 2026 - 9:30 am") == ("2026-05-29T09:30:00-04:00", "EDT")
    # bare "ET" (the AI Policy Podcast format the regex used to drop) -> Eastern, kept
    assert _parse_when("June 4, 2026 - 11:00 am ET") == ("2026-06-04T11:00:00-04:00", "EDT")
    # winter date -> EST
    assert _parse_when("January 14, 2026 - 9:00 am") == ("2026-01-14T09:00:00-05:00", "EST")
    # no date -> nothing
    assert _parse_when("no date here") == (None, None)


def test_parses_dedupes_and_skips_undated():
    events = parse_csis_listing(SRC, LISTING)
    ids = {e.id for e in events}
    # duplicate slug collapsed; undated skipped
    assert ids == {"csis-data-centers-ai-future", "csis-energy-shots-running-empty"}


def test_ai_event_fields():
    by_id = {e.id: e for e in parse_csis_listing(SRC, LISTING)}
    ev = by_id["csis-data-centers-ai-future"]
    assert ev.title == "Data Centers, AI, and the Future of U.S. Strategy"
    assert ev.start == "2026-06-03T15:30:00-04:00"
    assert ev.tz == "EDT"
    assert ev.organizer == "Strategic Technologies Program"
    assert ev.source_url == "https://www.csis.org/events/data-centers-ai-future"
    assert "ai" in ev.topics and "compute" in ev.topics


def test_provenance_time_assumed_vs_explicit():
    from aggregator.provenance import prov_get
    html = """<div class="grid">
      <article class="ts-card-event-sm"><a href="/events/explicit-t"></a>
        <h3>Explicit AI</h3><span>June 3, 2026 - 3:30 - 4:45 pm EDT</span>
        <a href="/programs/x">X</a></article>
      <article class="ts-card-event-sm"><a href="/events/assumed-t"></a>
        <h3>Assumed AI</h3><span>June 4, 2026 - 11:00 am ET</span>
        <a href="/programs/y">Y</a></article>
    </div>"""
    by_id = {e.id: e for e in parse_csis_listing(SRC, html)}
    assert prov_get(by_id["csis-explicit-t"], "time") == "explicit"
    assert prov_get(by_id["csis-assumed-t"], "time") == "assumed_et"


def test_offtopic_event_still_parsed_topicless():
    by_id = {e.id: e for e in parse_csis_listing(SRC, LISTING)}
    energy = by_id["csis-energy-shots-running-empty"]
    assert energy.topics == []          # topic filtering happens later in the pipeline
    assert energy.start == "2026-05-29T09:30:00-04:00"   # default Eastern (EDT in May)
