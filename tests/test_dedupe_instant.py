from aggregator.dedupe import dedupe
from aggregator.models import Event


def _ev(**kw):
    base = dict(id="x", title="t", start="2026-07-01", source="s")
    base.update(kw)
    return Event(**base)


def test_same_instant_cross_offset_abbrev_titles_merge():
    # Data Visualization DC cross-posts to Meetup and Luma: identical instant
    # (17:00-04:00 == 21:00Z), abbreviated/prefixed titles. Should collapse.
    a = _ev(id="meetup-1", title="Workshop: Data Viz with AI", source="meetup-dataviz",
            start="2026-06-15T17:00:00-04:00")
    b = _ev(id="dc2-1", title="DVDC: WORKSHOP: Data Visualization with AI", source="DC2",
            start="2026-06-15T21:00:00+00:00")
    out, removed = dedupe([a, b])
    assert removed == 1
    assert "also_sources" in out[0].raw


def test_same_instant_generic_tokens_only_not_merged():
    # Two DIFFERENT events at the exact same minute whose only shared tokens are
    # generic (ai/policy/forum/summit) must NOT collapse, even though the raw token
    # ratio clears 0.45 (a distinctive shared token is required to collapse).
    a = _ev(id="csis-1", title="AI Policy Forum", source="csis",
            start="2026-06-10T14:00:00-04:00")
    b = _ev(id="brk-1", title="AI Policy Summit", source="brookings",
            start="2026-06-10T14:00:00-04:00")
    out, removed = dedupe([a, b])
    assert removed == 0


def test_same_instant_but_unrelated_titles_not_merged():
    # Same start minute but clearly different events -> low token overlap -> keep both.
    a = _ev(id="a", title="Maritime Security in the Indo-Pacific", source="csis",
            start="2026-06-10T14:00:00-04:00")
    b = _ev(id="b", title="Quantum Computing Export Controls", source="cnas",
            start="2026-06-10T14:00:00-04:00")
    out, removed = dedupe([a, b])
    assert removed == 0
