from aggregator.dedupe import dedupe
from aggregator.models import Event


def E(id, title, start, source):
    return Event(id=id, title=title, start=start, source=source)


def test_exact_uid_collapses_across_calendars():
    evs = [
        E("evt-1", "AI Night", "2026-06-10T23:00:00+00:00", "DC2"),
        E("evt-1", "AI Night", "2026-06-10T23:00:00+00:00", "aic-washington"),
    ]
    kept, removed = dedupe(evs)
    assert len(kept) == 1
    assert removed == 1
    assert "aic-washington" in kept[0].raw.get("also_sources", [])


def test_fuzzy_title_same_day_collapses():
    evs = [
        E("evt-1", "AI/ML Project Night!", "2026-06-10T23:00:00+00:00", "DC2"),
        E("evt-2", "AI ML Project Night", "2026-06-10T18:00:00+00:00", "dctech"),
    ]
    kept, removed = dedupe(evs)
    assert len(kept) == 1
    assert removed == 1


def test_distinct_events_kept():
    evs = [
        E("evt-1", "AI Workshop", "2026-06-10T23:00:00+00:00", "DC2"),
        E("evt-2", "Semiconductor Policy Panel", "2026-06-12T23:00:00+00:00", "DC2"),
    ]
    kept, removed = dedupe(evs)
    assert len(kept) == 2
    assert removed == 0


def test_same_title_different_day_not_merged():
    evs = [
        E("evt-1", "AI Office Hours", "2026-06-10T23:00:00+00:00", "DC2"),
        E("evt-2", "AI Office Hours", "2026-06-17T23:00:00+00:00", "DC2"),
    ]
    kept, removed = dedupe(evs)
    assert len(kept) == 2
    assert removed == 0


def Eu(id, title, start, url, source="gwu"):
    return Event(id=id, title=title, start=start, source=source, source_url=url)


def test_multiday_series_collapses_to_range():
    url = "https://calendar.gwu.edu/event/aiexpo-2026"
    evs = [Eu("d1", "AI+EXPO 2026", "2026-05-07", url),
           Eu("d2", "AI+EXPO 2026", "2026-05-08", url),
           Eu("d3", "AI+EXPO 2026", "2026-05-09", url)]
    kept, removed = dedupe(evs)
    assert len(kept) == 1 and removed == 2
    assert kept[0].start[:10] == "2026-05-07"
    assert (kept[0].end or "")[:10] == "2026-05-09"
    assert kept[0].raw.get("days") == ["2026-05-07", "2026-05-08", "2026-05-09"]


def test_weekly_same_url_not_collapsed():
    # 7-day gaps (> SERIES_MAX_GAP_DAYS) -> distinct occurrences, kept separate.
    url = "https://lu.ma/weekly-ai-office-hours"
    evs = [Eu("w1", "AI Office Hours", "2026-06-01", url),
           Eu("w2", "AI Office Hours", "2026-06-08", url),
           Eu("w3", "AI Office Hours", "2026-06-15", url)]
    kept, removed = dedupe(evs)
    assert len(kept) == 3 and removed == 0


def test_same_title_different_url_not_collapsed():
    evs = [Eu("a", "Tech Summit", "2026-07-01", "https://x/a"),
           Eu("b", "Tech Summit", "2026-07-02", "https://y/b")]
    kept, removed = dedupe(evs)
    assert len(kept) == 2 and removed == 0


# --- P3: cross-language / fuzzy dedupe ---
from aggregator.dedupe import _token_set_ratio, semantic_ratio


def test_token_set_ratio_word_order_insensitive():
    assert _token_set_ratio("AI Policy Panel", "Panel on AI Policy") >= 0.9


def test_token_set_ratio_distinct_titles_low():
    assert _token_set_ratio("Quantum Computing Talk", "AI Policy Panel") < 0.3


def test_paraphrase_same_day_same_geo_collapses():
    evs = [
        Event(id="x1", title="AI Policy Panel", start="2026-06-10", source="cset",
              lat=38.90, lng=-77.03),
        Event(id="x2", title="Panel on AI Policy", start="2026-06-10", source="csis",
              lat=38.901, lng=-77.031),   # ~0.1 km away
    ]
    kept, removed = dedupe(evs)
    assert len(kept) == 1 and removed == 1


def test_paraphrase_far_apart_not_collapsed():
    evs = [
        Event(id="y1", title="AI Policy Panel", start="2026-06-10", source="cset",
              lat=38.90, lng=-77.03),
        Event(id="y2", title="Panel on AI Policy", start="2026-06-10", source="x",
              lat=40.71, lng=-74.00),     # NYC -> different event
    ]
    kept, removed = dedupe(evs)
    assert len(kept) == 2 and removed == 0


def test_semantic_ratio_is_noop_without_model():
    r = semantic_ratio("hola mundo IA", "hello AI world")
    assert r is None or isinstance(r, float)
