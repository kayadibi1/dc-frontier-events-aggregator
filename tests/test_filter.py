from aggregator.filter import _big_names, apply_filters, is_admin_event, is_dc_relevant
from aggregator.models import Event
from aggregator.normalize import detect_topics


def mk(**kw):
    base = dict(id="x", title="t", start="2026-06-10T23:00:00+00:00", source="DC2")
    base.update(kw)
    return Event(**base)


def test_dc_ontopic_event_kept():
    ev = mk(title="Machine Learning Workshop", topics=["ml"], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert len(kept) == 1
    assert not kept[0].is_big_name


def test_non_dc_event_dropped_on_location():
    # San Francisco coords, non-curated global calendar -> excluded.
    ev = mk(title="AI Meetup", topics=["ai"], lat=37.77, lng=-122.41, source="ai")
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_location"] == 1


def test_big_name_flagged_and_kept_even_without_topic():
    ev = mk(title="Fireside chat with Anthropic", topics=[], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert len(kept) == 1
    assert kept[0].is_big_name
    assert stats["big_name"] == 1
    assert any(t == "big:Anthropic" for t in kept[0].topics)


def test_dc_offtopic_event_dropped_on_topic():
    ev = mk(title="Morning Yoga in the Park", topics=[], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_topic"] == 1


def test_big_name_precision_no_false_positives():
    # Common DC/event phrases that must NOT trip the big-name flag.
    for text in ["Metadata management for AI teams",
                 "Arms control and AI policy panel",
                 "Intelligence community AI briefing",
                 "Intel community data-sharing forum",
                 "Register via Google Form for the AI workshop"]:
        ev = mk(title=text, lat=38.9, lng=-77.03, topics=["ai"])
        kept, _ = apply_filters([ev])
        assert kept and not kept[0].is_big_name, f"false positive on: {text!r}"


def test_big_name_new_watchlist_hits():
    for text in ["Qualcomm on the chip supply chain",
                 "A fireside with Satya Nadella",
                 "Scale AI and defense data",
                 "Intel's new foundry strategy"]:
        ev = mk(title=text, lat=38.9, lng=-77.03, topics=["ai"])
        kept, _ = apply_filters([ev])
        assert kept[0].is_big_name, f"missed big name in: {text!r}"


def test_big_name_expanded_watchlist_hits():
    # Newly added frontier labs, chip cos, AI leaders, and DC policy orgs.
    for text in ["xAI releases Grok update",
                 "Groq inference chips deep dive",
                 "Cerebras wafer-scale compute",
                 "Inflection AI strategy session",
                 "A talk by Yann LeCun on world models",
                 "Fireside with Mira Murati",
                 "RAND Corporation on AI and deterrence",
                 "The AI Safety Institute (CAISI) framework"]:
        ev = mk(title=text, lat=38.9, lng=-77.03, topics=["ai"])
        kept, _ = apply_filters([ev])
        assert kept and kept[0].is_big_name, f"missed big name in: {text!r}"


def test_big_name_expanded_watchlist_no_false_positives():
    # Landmines the specific patterns must dodge.
    for text in ["The inflection point for AI adoption",   # not Inflection AI
                 "Numerical stability in deep learning",    # not Stability AI
                 "Reducing perplexity in language models",  # not Perplexity (metric)
                 "Senator Rand Paul on tech policy",        # not RAND Corporation
                 "A 7-micron sensor for edge AI",           # not Micron (company)
                 "Grokking: sudden generalization in nets"]:  # not Grok (xAI)
        ev = mk(title=text, lat=38.9, lng=-77.03, topics=["ai"])
        kept, _ = apply_filters([ev])
        assert kept and not kept[0].is_big_name, f"false positive on: {text!r}"


def test_host_org_self_mention_not_big_name():
    # A CSIS-sourced event naming its own host "CSIS" is NOT a prestige signal.
    ev = mk(title="CSIS Debrief: AI policy", source="csis", topics=["ai"],
            lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert kept and not kept[0].is_big_name


def test_policy_source_events_not_self_flagged_bigname():
    # Every curated policy SOURCE must suppress its own org self-mention, else its
    # whole slate (organizer == the org) would be spuriously big-name. Regression
    # for the cnas/atlanticcouncil leak: they were added as sources + watchlist
    # orgs but missed from SOURCE_ORG, inflating big-name by their full feed.
    for slug, org in [("cnas", "CNAS"), ("atlanticcouncil", "Atlantic Council"),
                      ("csis", "CSIS"), ("cset", "CSET"), ("brookings", "Brookings")]:
        ev = mk(title="AI and the Future of War", source=slug, topics=["ai"],
                lat=38.9, lng=-77.03, organizer=org)
        kept, _ = apply_filters([ev])
        assert kept and not kept[0].is_big_name, f"{slug} self-flagged big-name"


def test_cross_source_org_mention_is_big_name():
    # The same org named in ANOTHER source's event IS a prestige signal.
    ev = mk(title="GW panel featuring RAND Corporation", source="gwu",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert kept and kept[0].is_big_name


def test_host_event_still_flags_other_marquee_org():
    # A CSIS event featuring a real marquee lab (Anthropic) still flags big-name;
    # only the circular self-mention is suppressed.
    ev = mk(title="CSIS hosts Anthropic on frontier policy", source="csis",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert kept and kept[0].is_big_name
    assert any(t == "big:Anthropic" for t in kept[0].topics)
    assert not any(t == "big:CSIS" for t in kept[0].topics)


# --- policy-org names: title/Layer-2 only (kill firehose-description noise) ---

def test_policy_org_in_firehose_speaker_bio_not_flagged():
    # Real live false positives: policy-org names appearing in a firehose source's
    # speaker bio set big-name, bypassing the topic filter and injecting off-topic
    # events. A policy-org name in a non-Layer-2 DESCRIPTION must not flag. Tested
    # on _big_names directly (the flag logic), isolated from the topic filter.
    nist = mk(title="The Many Faces of Trust", source="gwu",
              description="Deputy Director of the NIST-NSF Institute for Trustworthy AI")
    assert _big_names(nist) == []
    ac = mk(title="Careers in European Business and Policy", source="gwu",
            description="speakers include Kristen Taylor (Atlantic Council)")
    assert _big_names(ac) == []


def test_policy_org_in_firehose_title_is_flagged():
    # A policy org named in the TITLE is a genuine signal even in a firehose source.
    ev = mk(title="Fireside with RAND Corporation", source="gwu")
    assert "RAND" in _big_names(ev)


def test_policy_org_in_title_still_big_name_even_in_firehose():
    ev = mk(title="GW panel featuring RAND Corporation on AI", source="gwu",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert kept and kept[0].is_big_name


def test_policy_org_in_layer2_body_is_big_name():
    # A legit cross-mention in a curated Layer-2 source body still counts.
    ev = mk(title="Frontier chips briefing", source="cset", topics=["ai"],
            description="In partnership with RAND Corporation analysts.",
            lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert kept and kept[0].is_big_name
    assert any(t == "big:RAND" for t in kept[0].topics)


def test_dc_curated_virtual_event_is_relevant():
    ev = mk(title="Virtual AI Talk", description="Online webinar", topics=["ai"])
    assert is_dc_relevant(ev) is True


def test_big_name_fires_on_speaker():
    ev = mk(title="Fireside chat", topics=["ai"], lat=38.9, lng=-77.03,
            speakers=["Jensen Huang"])
    kept, _ = apply_filters([ev])
    assert kept and kept[0].is_big_name


def test_big_name_does_not_fire_on_speaker_org_affiliation():
    # A speaker's org affiliation ("Microsoft AR") must NOT flag the event as a
    # big-name -- only watchlisted PEOPLE among speakers count.
    ev = mk(title="AI Red-Teaming Panel", topics=["ai"], lat=38.9, lng=-77.03,
            speakers=["Microsoft AR", "People Analytics"])
    kept, _ = apply_filters([ev])
    assert kept and not kept[0].is_big_name


def test_inperson_nondc_geo_dropped_despite_dc_text():
    # Hampton Roads, VA: real coords ~200mi from DC, address says "VA 23462".
    # GEO is authoritative for in-person events -> dropped.
    ev = mk(title="AI Build Challenge", topics=["ai"], lat=36.80, lng=-76.20,
            address="Regent University, Virginia Beach, VA 23462", source="aic-washington")
    assert is_dc_relevant(ev) is False


def test_virtual_curated_event_with_bogus_geo_kept():
    # Online DC2 event with a junk placeholder geo (mid-Pacific) -> still kept.
    ev = mk(title="Online: Intro to AI Evals", description="Online webinar",
            topics=["ai"], lat=-8.5, lng=179.1, source="DC2")
    assert is_dc_relevant(ev) is True


# --- relevance precision: kill admissions/boilerplate noise, keep real events ---

def test_accelerated_degree_not_compute():
    # "accelerated" in university boilerplate must NOT count as a compute topic.
    assert "compute" not in detect_topics("Accelerated MBA program info")
    assert "compute" not in detect_topics("GW Nursing Tour join our accelerated track")


def test_real_compute_terms_still_match():
    assert "compute" in detect_topics("Hands-on with GPU accelerators")
    assert "compute" in detect_topics("Accelerated computing on NVIDIA hardware")
    assert "compute" in detect_topics("Data center buildout for AI")


def test_admin_info_session_excluded_even_with_topic():
    ev = mk(title="GWSB MS in Artificial Intelligence Information Session",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_admin"] == 1


def test_admin_open_house_and_master_of_and_whygw_excluded():
    for title in ["GW School of Business Graduate Programs Online Open House",
                  "GWSB Master of Accountancy",
                  "LLM Virtual Webinars: Why GW Law?"]:
        ev = mk(title=title, topics=["ai", "data-science", "llm"], lat=38.9, lng=-77.03)
        kept, stats = apply_filters([ev])
        assert kept == [], f"should drop admin: {title!r}"
        assert stats["dropped_admin"] == 1


def test_real_talks_not_flagged_as_admin():
    # Genuine talks/panels/workshops must survive the admin filter.
    for title in ["AI in Action: Smarter Sourcing & Contracts",
                  "Generative AI: Hands-On with the Tools Shaping Tomorrow",
                  "Data Centers, AI, and the Future of U.S. Strategic Competitiveness",
                  "Rewiring the Chip Landscape",
                  "AI and economic mobility: Opportunities and challenges"]:
        assert not is_admin_event(mk(title=title)), f"false admin hit: {title!r}"


def test_real_ai_event_still_kept():
    ev = mk(title="AI in Action: Smarter Sourcing & Contracts",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert len(kept) == 1


# --- per-source topic strictness: firehose sources require a TITLE topic ---

def test_strict_source_drops_desc_only_topic():
    # gwu firehose: AI only in description (topics from normalize) but NOT in
    # title -> dropped (boilerplate). Title is non-admin so it reaches the gate.
    ev = mk(title="GW Faculty Research Showcase", source="gwu",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_topic"] == 1


def test_strict_source_keeps_title_topic():
    ev = mk(title="The Many Faces of Trust: Innovating in AI", source="gwu",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert len(kept) == 1


def test_strict_aic_drops_desc_only_topic():
    ev = mk(title="Networking Happy Hour", source="aic-washington",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_topic"] == 1


def test_curated_source_keeps_desc_only_topic():
    # CSET gem: no topic word in title, AI only in description -> STILL kept,
    # because curated Layer-2 sources are not held to the title-only rule.
    ev = mk(title="How the U.S. Wins the Global Tech Competition", source="cset",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert len(kept) == 1


# --- per-source topic strictness: firehose sources require a TITLE topic ---

def test_strict_source_drops_desc_only_topic():
    # gwu firehose: AI only in description (topics from normalize), not title ->
    # dropped as boilerplate. Title is non-admin so it reaches the topic gate.
    ev = mk(title="GW Faculty Research Showcase", source="gwu",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_topic"] == 1


def test_strict_source_keeps_title_topic():
    ev = mk(title="The Many Faces of Trust: Innovating in AI", source="gwu",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert len(kept) == 1


def test_strict_aic_drops_desc_only_topic():
    ev = mk(title="Networking Happy Hour", source="aic-washington",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_topic"] == 1


def test_curated_source_keeps_desc_only_topic():
    # CSET gem: no topic word in title, AI only in description -> STILL kept,
    # because curated Layer-2 sources are not held to the title-only rule.
    ev = mk(title="How the U.S. Wins the Global Tech Competition", source="cset",
            topics=["ai"], lat=38.9, lng=-77.03)
    kept, _ = apply_filters([ev])
    assert len(kept) == 1


def test_structured_virtual_flag_respected():
    # Luma JSON signals online via raw["virtual"] with no text marker; an online
    # event with out-of-town coords must take the virtual path, not geo-authority.
    ev = mk(title="AI fireside (streamed)", topics=["ai"], lat=37.77, lng=-122.42,
            raw={"virtual": True})
    assert is_dc_relevant(ev)                     # DC2 is dc_curated -> trusted
    ev2 = mk(source="aic-washington", title="AI fireside (streamed)",
             topics=["ai"], lat=37.77, lng=-122.42, raw={"virtual": True})
    assert not is_dc_relevant(ev2)                # non-curated, no DC text -> still out
