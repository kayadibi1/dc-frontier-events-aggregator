from aggregator.enrich import recompute_topics
from aggregator.models import Event


def _ev(**kw):
    base = dict(id="x", title="t", start="2026-07-01", source="itif")
    base.update(kw)
    return Event(**base)


def test_adds_topic_from_enriched_description_for_curated_source():
    ev = _ev(title="A Conversation With the Director",
             description="A discussion of AI, chip export controls and compute policy.")
    recompute_topics([ev], {"itif"})
    assert {"ai", "semiconductor", "compute", "policy"} & set(ev.topics)


def test_ignores_sources_not_in_set():
    ev = _ev(source="gwu", title="Generic", description="all about artificial intelligence")
    recompute_topics([ev], {"itif"})
    assert ev.topics == []


def test_preserves_existing_and_big_tags_without_dupes():
    ev = _ev(source="csis", title="AI policy", description="more on AI",
             topics=["ai", "big:Nvidia"])
    recompute_topics([ev], {"csis"})
    assert "big:Nvidia" in ev.topics
    assert ev.topics.count("ai") == 1


def test_no_description_is_a_noop():
    ev = _ev(title="Bland title", description="")
    recompute_topics([ev], {"itif"})
    assert ev.topics == []
