import feedparser
from icalendar import Calendar

from aggregator.emit import filter_upcoming, write_ics, write_rss
from aggregator.models import Event


def sample():
    return [
        Event(id="evt-1", title="AI Workshop", start="2026-06-10T23:00:00+00:00",
              source="DC2", source_url="https://luma.com/a", address="Arlington VA",
              lat=38.9, lng=-77.0, topics=["ai"]),
        Event(id="evt-2", title="Anthropic Fireside", start="2026-06-12T18:00:00+00:00",
              source="DC2", source_url="https://luma.com/b", is_big_name=True,
              topics=["ai", "big:Anthropic"]),
    ]


def test_ics_parses_with_icalendar(tmp_path):
    p = tmp_path / "events.ics"
    n = write_ics(sample(), str(p))
    assert n == 2
    cal = Calendar.from_ical(p.read_bytes())
    vevents = list(cal.walk("VEVENT"))
    assert len(vevents) == 2
    summaries = [str(c.get("summary")) for c in vevents]
    assert any("Anthropic" in s for s in summaries)
    assert any(s.startswith("★") for s in summaries)  # big-name star


def test_rss_parses_with_feedparser(tmp_path):
    p = tmp_path / "feed.xml"
    n = write_rss(sample(), str(p))
    assert n == 2
    d = feedparser.parse(p.read_bytes())
    assert d.bozo == 0           # well-formed XML
    assert len(d.entries) == 2
    assert any("Anthropic" in e.title for e in d.entries)


def test_fixed_offset_start_emitted_as_utc(tmp_path):
    # A CSIS-style EDT (-04:00) start must serialize as unambiguous UTC 'Z',
    # not an invalid TZID like "UTC-04:00".
    ev = [Event(id="csis-x", title="AI Talk", start="2026-06-04T10:30:00-04:00",
                source="csis", topics=["ai"])]
    p = tmp_path / "e.ics"
    write_ics(ev, str(p))
    raw = p.read_text(encoding="utf-8")
    assert "TZID" not in raw
    assert "20260604T143000Z" in raw      # 10:30 EDT == 14:30 UTC
    cal = Calendar.from_ical(p.read_bytes())
    dt = list(cal.walk("VEVENT"))[0].get("dtstart").dt
    assert dt.tzinfo is not None


def test_filter_upcoming_boundary_and_mixed_formats():
    evs = [
        Event(id="past", title="p", start="2025-01-01", source="x"),
        Event(id="today", title="t", start="2026-05-29T18:00:00+00:00", source="x"),
        Event(id="future", title="f", start="2026-12-01", source="x"),
    ]
    up = {e.id for e in filter_upcoming(evs, "2026-05-29")}
    assert up == {"today", "future"}   # today is inclusive, past excluded


def test_empty_inputs_produce_valid_empty_feeds(tmp_path):
    ics = tmp_path / "e.ics"
    rss = tmp_path / "e.xml"
    assert write_ics([], str(ics)) == 0
    assert write_rss([], str(rss)) == 0
    assert Calendar.from_ical(ics.read_bytes()) is not None
    assert feedparser.parse(rss.read_bytes()).bozo == 0

def test_ics_per_event_color(tmp_path):
    evs = [
        Event(id="big", title="Fireside", start="2026-06-10", source="csis",
              is_big_name=True, topics=["ai"]),
        Event(id="comm", title="Meetup", start="2026-06-10", source="DC2", topics=["ai"]),
    ]
    p = tmp_path / "c.ics"
    write_ics(evs, str(p))
    cal = Calendar.from_ical(p.read_bytes())
    colors = {str(v.get("uid")): str(v.get("color")) for v in cal.walk("VEVENT")}
    assert colors["big"] == "red"      # big-name -> red
    assert colors["comm"] == "blue"    # Layer-1 community -> blue


def test_ics_valarm_only_for_upcoming(tmp_path):
    evs = [
        Event(id="future", title="Upcoming AI", start="2026-12-01", source="DC2", topics=["ai"]),
        Event(id="past", title="Old AI", start="2024-01-01", source="DC2", topics=["ai"]),
    ]
    p = tmp_path / "a.ics"
    write_ics(evs, str(p), "2026-05-29")
    cal = Calendar.from_ical(p.read_bytes())
    alarms = {str(v.get("uid")): len(list(v.walk("VALARM"))) for v in cal.walk("VEVENT")}
    assert alarms["future"] == 1
    assert alarms["past"] == 0


def test_ics_no_valarm_without_today(tmp_path):
    evs = [Event(id="x", title="AI", start="2026-12-01", source="DC2", topics=["ai"])]
    p = tmp_path / "n.ics"
    write_ics(evs, str(p))   # no today_iso -> no alarms (backward compatible)
    cal = Calendar.from_ical(p.read_bytes())
    assert len(list(list(cal.walk("VEVENT"))[0].walk("VALARM"))) == 0


# --- Google Calendar subscribe-readiness (backlog idea #1, the end goal) ---

def test_ics_has_subscription_headers(tmp_path):
    p = tmp_path / "events.ics"
    write_ics(sample(), str(p))
    raw = p.read_text(encoding="utf-8")
    # auto-refresh hints honored by Google/Apple/Outlook subscriptions
    assert "REFRESH-INTERVAL" in raw and "PT12H" in raw
    assert "X-PUBLISHED-TTL:PT12H" in raw
    assert "METHOD:PUBLISH" in raw
    assert "X-WR-TIMEZONE:UTC" in raw
    assert "X-WR-CALDESC" in raw


def test_ics_calendar_name_default_and_override(tmp_path):
    d = tmp_path / "d.ics"
    write_ics(sample(), str(d))
    assert "X-WR-CALNAME:DC AI & Frontier Tech Events" in d.read_text(encoding="utf-8")
    o = tmp_path / "o.ics"
    write_ics(sample(), str(o), cal_name="DC AI — Upcoming")
    raw = o.read_text(encoding="utf-8")
    assert "X-WR-CALNAME:DC AI" in raw and "Upcoming" in raw


def test_ics_still_parses_with_subscription_headers(tmp_path):
    # The added calendar props must not break iCal parsing or change event count.
    p = tmp_path / "s.ics"
    n = write_ics(sample(), str(p))
    cal = Calendar.from_ical(p.read_bytes())
    assert n == 2 and len(list(cal.walk("VEVENT"))) == 2
    assert str(cal.get("x-wr-calname"))  # present and non-empty


def test_ics_location_suffix_and_notes_for_hq(tmp_path):
    from icalendar import Calendar
    from aggregator.provenance import prov_set
    ev = Event(id="h", title="Panel", start="2026-06-10", source="csis",
               address="CSIS, 1616 Rhode Island Ave NW, Washington, DC 20036")
    prov_set(ev, "location", "hq")
    p = str(tmp_path / "p.ics")
    write_ics([ev], p, "2026-06-01")
    ve = next(iter(Calendar.from_ical(open(p, "rb").read()).walk("VEVENT")))
    assert "approx" in str(ve.get("location"))
    assert "host venue" in str(ve.get("description"))


def test_ics_no_suffix_for_scraped(tmp_path):
    from icalendar import Calendar
    from aggregator.provenance import prov_set
    ev = Event(id="s", title="Panel", start="2026-06-10", source="brookings",
               address="Saul Auditorium, 1775 Massachusetts Ave NW, Washington, DC 20036")
    prov_set(ev, "location", "scraped")
    p = str(tmp_path / "s.ics")
    write_ics([ev], p, "2026-06-01")
    ve = next(iter(Calendar.from_ical(open(p, "rb").read()).walk("VEVENT")))
    assert "approx" not in str(ve.get("location"))


def test_li_map_marker_for_hq():
    from aggregator.emit import _li
    from aggregator.provenance import prov_set
    ev = Event(id="m", title="Panel", start="2026-06-10", source="csis",
               address="CSIS HQ", lat=38.9, lng=-77.04)
    prov_set(ev, "location", "hq")
    assert "📍approx" in _li(ev)


def test_json_carries_provenance(tmp_path):
    import json
    from aggregator.emit import write_json
    from aggregator.provenance import prov_set
    ev = Event(id="j", title="x", start="2026-06-10", source="csis", address="HQ")
    prov_set(ev, "location", "hq")
    p = str(tmp_path / "e.json")
    write_json([ev], p)
    rec = json.load(open(p, encoding="utf-8"))[0]
    assert rec["raw"]["provenance"]["location"] == "hq"


def test_map_is_pro_dark():
    from aggregator import emit
    assert "basemaps.cartocdn.com/dark_all" in emit._MAP_TAIL   # dark tiles
    assert "#1d1d1f" in emit._MAP_HEAD                          # dark surfaces
    assert "linear-gradient" not in emit._MAP_HEAD              # gradient nav gone


def test_map_has_canonical():
    from aggregator import emit
    assert '<link rel="canonical" href="https://events.emersus.ai/map.html">' in emit._MAP_HEAD


def test_map_has_home_screen_icon_links():
    from aggregator import emit
    assert 'rel="apple-touch-icon" href="/apple-touch-icon.png"' in emit._MAP_HEAD
    assert 'rel="manifest" href="/manifest.json"' in emit._MAP_HEAD


def test_rss_drops_javascript_source_url(tmp_path):
    # untrusted source_url must not survive as a javascript: link in the feed.
    evil = Event(id="e", title="E", start="2026-06-20T00:00:00+00:00", source="DC2",
                 source_url="javascript:alert(1)", topics=["ai"])
    p = tmp_path / "feed.xml"
    write_rss([evil], str(p))
    assert "javascript:" not in p.read_text(encoding="utf-8")


def test_ics_url_drops_javascript_source_url(tmp_path):
    evil = Event(id="e", title="E", start="2026-06-20T00:00:00+00:00", source="DC2",
                 source_url="javascript:alert(1)", topics=["ai"])
    p = tmp_path / "events.ics"
    write_ics([evil], str(p))
    assert b"javascript:" not in p.read_bytes()


def test_ics_description_has_remote_note():
    from aggregator.emit import build_ics
    from aggregator.models import Event
    ev = Event(id="x", title="AI hearing", start="2026-07-01", source="congress",
               address="Rayburn HOB, Washington, DC",
               raw={"remote": True, "watch_url": "https://www.congress.gov/m/1"})
    data, _ = build_ics([ev], "2026-06-01")
    text = data.decode("utf-8").replace("\r\n ", "")     # unfold 75-octet ICS lines
    assert "Remote viewing available" in text
    assert "congress.gov/m/1" in text


def test_ics_no_remote_note_for_inperson():
    from aggregator.emit import build_ics
    from aggregator.models import Event
    ev = Event(id="y", title="In person", start="2026-07-01", source="csis",
               address="100 K St, Washington, DC")
    data, _ = build_ics([ev], "2026-06-01")
    text = data.decode("utf-8").replace("\r\n ", "")
    assert "Remote viewing available" not in text
