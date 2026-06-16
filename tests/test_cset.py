from aggregator.config import Source
from aggregator.fetchers.cset import parse_cset_listing

SRC = Source("cset", "CSET (Georgetown)", "cset", 2, True,
             url="https://cset.georgetown.edu/events/")

# Mirrors the real CSET listing DOM (div.teaser__top + .teaser__dates/.location),
# with each card wrapped in a single-event container holding an excerpt.
LISTING = """
<div class="events-grid">
  <article class="teaser">
    <div class="teaser__top">
      <h4><a href="https://cset.georgetown.edu/event/rewiring-the-chip-landscape/">Rewiring the Chip Landscape</a></h4>
      <span>
        <div class="teaser__dates">February 27, 2026</div>
        <div class="teaser__location">125 E Street NW, Washington, DC, 20001</div>
      </span>
    </div>
    <div class="teaser__excerpt">A discussion on semiconductor export controls and GPU supply chains.</div>
  </article>
  <article class="teaser">
    <div class="teaser__top">
      <h4><a href="https://cset.georgetown.edu/event/the-talent-map/">The Talent Map</a></h4>
      <span>
        <div class="teaser__dates">December 2, 2025</div>
        <div class="teaser__location">Online</div>
      </span>
    </div>
    <div class="teaser__excerpt">A webinar on AI workforce.</div>
  </article>
  <article class="teaser">
    <div class="teaser__top">
      <h4><a href="https://cset.georgetown.edu/event/no-date/">Undated</a></h4>
      <div class="teaser__location">Online</div>
    </div>
  </article>
</div>
"""


def test_parses_cards_and_dates():
    events = parse_cset_listing(SRC, LISTING)
    # the undated card is skipped
    assert len(events) == 2
    by_id = {e.id: e for e in events}
    assert "cset-rewiring-the-chip-landscape" in by_id
    chip = by_id["cset-rewiring-the-chip-landscape"]
    assert chip.title == "Rewiring the Chip Landscape"
    assert chip.start == "2026-02-27"
    assert chip.source == "cset"
    assert chip.source_url.endswith("/rewiring-the-chip-landscape/")


def test_location_and_virtual():
    events = parse_cset_listing(SRC, LISTING)
    by_id = {e.id: e for e in events}
    chip = by_id["cset-rewiring-the-chip-landscape"]
    talent = by_id["cset-the-talent-map"]
    assert "125 E Street" in chip.address
    assert chip.raw["virtual"] is False
    assert talent.address == ""           # Online -> no physical address
    assert talent.raw["virtual"] is True


def test_topics_detected_from_cset():
    by_id = {e.id: e for e in parse_cset_listing(SRC, LISTING)}
    assert "semiconductor" in by_id["cset-rewiring-the-chip-landscape"].topics
    assert "ai" in by_id["cset-the-talent-map"].topics


def test_excerpt_extracted_when_single_card():
    by_id = {e.id: e for e in parse_cset_listing(SRC, LISTING)}
    assert "export controls" in by_id["cset-rewiring-the-chip-landscape"].description


def test_grid_guard_blocks_contaminated_description():
    # Two teaser__top directly under one parent -> parent has 2 dates -> no excerpt.
    grid = """
    <div class="grid">
      <div class="teaser__top"><h4><a href="https://cset.georgetown.edu/event/a/">A</a></h4>
        <div class="teaser__dates">January 5, 2026</div><div class="teaser__location">Online</div></div>
      <div class="teaser__top"><h4><a href="https://cset.georgetown.edu/event/b/">B</a></h4>
        <div class="teaser__dates">January 6, 2026</div><div class="teaser__location">Online</div></div>
    </div>
    """
    events = parse_cset_listing(SRC, grid)
    assert len(events) == 2
    assert all(e.description == "" for e in events)
