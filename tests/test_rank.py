from aggregator.models import Event
from aggregator.rank import event_kind, score_event, top_upcoming

TODAY = "2026-05-29"


def mk(**kw):
    base = dict(id="x", title="t", start="2026-06-10", source="DC2")
    base.update(kw)
    return Event(**base)


def test_big_name_outranks_plain():
    big = mk(topics=["ai"], is_big_name=True)
    plain = mk(topics=["ai"])
    assert score_event(big, TODAY) > score_event(plain, TODAY)


def test_upcoming_outranks_past():
    fut = mk(start="2026-06-10", topics=["ai"])
    past = mk(start="2024-01-01", topics=["ai"])
    assert score_event(fut, TODAY) > score_event(past, TODAY)


def test_more_topics_scores_higher():
    two = mk(topics=["ai", "semiconductor"])
    one = mk(topics=["ai"])
    assert score_event(two, TODAY) > score_event(one, TODAY)


def test_closer_to_dc_scores_higher():
    near = mk(topics=["ai"], lat=38.90, lng=-77.03)   # downtown DC
    far = mk(topics=["ai"], lat=39.29, lng=-76.61)    # Baltimore-ish, ~40mi
    assert score_event(near, TODAY) > score_event(far, TODAY)


def test_big_tags_dont_count_as_topics():
    # only a big: tag, no real topic -> topic component is 0; title 't' is a
    # neutral 'talk' (no type weight) and big: tags aren't policy topics.
    ev = mk(topics=["big:Anthropic"], is_big_name=True)
    assert score_event(ev, TODAY) == 50.0 + 20.0


# --- event-type weighting for an upskilling / policy-angled radar ---

def test_event_kind_classification():
    assert event_kind(mk(title="Hands-on Workshop: Build an AI Agent")) == "handson"
    assert event_kind(mk(title="AI Governance Fireside Chat")) == "policy"
    assert event_kind(mk(title="AI Collective DC | Launch Party")) == "networking"
    assert event_kind(mk(title="DC Tech Meetup #91: Integrating AI")) == "talk"
    # community-talk formats are NOT penalized as networking
    assert event_kind(mk(title="GenAI Collective NYC Demo Night")) == "talk"


def test_founders_friday_and_brand_networking_detected():
    # real brands seen in the live data that must classify as networking
    assert event_kind(mk(title="Humans in AI Week: Founders Friday x Unstuck Labs")) == "networking"
    assert event_kind(mk(title="GenAI Collective Founders Dinner")) == "networking"
    assert event_kind(mk(title="AI Game Night")) == "networking"
    # but community-talk formats stay neutral, not networking
    assert event_kind(mk(title="GenAI Collective NYC Demo Night")) == "talk"
    assert event_kind(mk(title="Founders Roundtable on AI Strategy")) == "policy"  # roundtable=policy


def test_handson_beats_policy_beats_networking_precedence():
    # a workshop that also says "happy hour" is still hands-on
    assert event_kind(mk(title="AI Workshop + Happy Hour")) == "handson"
    # a fireside that also says "reception" is still policy
    assert event_kind(mk(title="Fireside Chat & Reception")) == "policy"


def test_handson_outranks_networking():
    work = mk(title="Workshop: Build with AI (laptop required)", topics=["ai"])
    party = mk(title="AI Founders Happy Hour", topics=["ai"])
    assert score_event(work, TODAY) > score_event(party, TODAY)


def test_policy_event_outranks_plain_talk():
    panel = mk(title="Export Controls Panel", topics=["ai", "policy"])
    talk = mk(title="Intro to AI", topics=["ai"])
    assert score_event(panel, TODAY) > score_event(talk, TODAY)


def test_networking_is_downranked_but_scoreable():
    party = mk(title="AI Launch Party", topics=["ai"])
    # networking penalty applies but the function still returns a number
    assert isinstance(score_event(party, TODAY), float)


def test_big_name_networking_still_outranks_plain_talk():
    # a marquee-org networking event should still float above a plain talk
    big_party = mk(title="Anthropic Launch Party", topics=["ai"], is_big_name=True)
    plain = mk(title="Intro to AI", topics=["ai"])
    assert score_event(big_party, TODAY) > score_event(plain, TODAY)


def test_policy_topic_bonus():
    pol = mk(title="Talk", topics=["ai", "semiconductor"])
    non = mk(title="Talk", topics=["ai", "ml"])
    assert score_event(pol, TODAY) > score_event(non, TODAY)


def test_top_upcoming_excludes_past_and_sorts_desc():
    evs = [
        mk(id="past", start="2024-01-01", topics=["ai"]),
        mk(id="low", start="2026-06-01", topics=["ai"]),
        mk(id="high", start="2026-06-01", topics=["ai", "compute"], is_big_name=True),
    ]
    top = top_upcoming(evs, TODAY, n=10)
    ids = [e.id for e in top]
    assert "past" not in ids
    assert ids[0] == "high"          # highest score first
