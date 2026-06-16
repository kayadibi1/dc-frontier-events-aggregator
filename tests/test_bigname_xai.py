from aggregator.filter import apply_filters
from aggregator.models import Event


def _ev(title):
    # cnas is dc_curated + a real topic, so it survives to the big-name check
    return Event(id="x", title=title, start="2026-07-01", source="cnas", topics=["ai"])


def test_explainable_ai_xai_not_flagged_as_elon_xai():
    # academic "xAI" = eXplainable AI (common in ML) must NOT trip the xAI (Elon)
    # company big-name -- a real collision UMD CS surfaced.
    kept, _ = apply_filters([_ev("Beyond Descriptive xAI: Cross-Domain Methods")])
    assert kept and not kept[0].is_big_name


def test_grok_still_flags_the_xai_company():
    kept, _ = apply_filters([_ev("A fireside chat about Grok")])
    assert kept and kept[0].is_big_name
    assert "big:xAI" in kept[0].topics
