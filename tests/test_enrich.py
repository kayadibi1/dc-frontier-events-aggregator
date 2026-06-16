import asyncio

from aggregator.config import SOURCE_HQ, Source
from aggregator.enrich import (
    enrich_layer2,
    extract_description,
    extract_location,
    extract_speakers,
)
from aggregator.models import Event

CSIS_HTML = """
<div class="event"><h1>Data Centers and AI</h1>
  <div class="speakers">
    <div class="speaker"><span class="speaker__name">Jensen Huang</span><span>NVIDIA</span></div>
    <div class="speaker"><span class="speaker__name">Gregory Allen</span><span>CSIS</span></div>
  </div></div>
"""

CSET_PROSE_HTML = """
<article><p>Please join CSET for a fireside chat featuring Dario Amodei and
Helen Toner, moderated by Jane Smith.</p></article>
"""


def test_extract_speakers_from_structured_nodes():
    names = extract_speakers(CSIS_HTML)
    assert "Jensen Huang" in names
    assert "Gregory Allen" in names


def test_extract_speakers_from_prose():
    names = extract_speakers(CSET_PROSE_HTML)
    assert "Dario Amodei" in names
    assert "Helen Toner" in names


def test_extract_speakers_dedupes_and_rejects_nonnames():
    html = '<div class="speaker">Register Now</div><div class="speaker">Sam Altman</div>'
    names = extract_speakers(html)
    assert "Sam Altman" in names
    assert "Register Now" not in names   # not a person name


def test_extract_speakers_empty_when_none():
    assert extract_speakers("<p>No speakers listed here.</p>") == []


def test_extract_speakers_rejects_org_affiliations():
    html = ('<div class="speaker"><span class="name">Carnegie Mellon University</span></div>'
            '<div class="speaker"><span class="name">Dario Amodei</span></div>'
            '<div class="speaker"><span class="name">Open Government Partnership</span></div>')
    names = extract_speakers(html)
    assert "Dario Amodei" in names
    assert "Carnegie Mellon University" not in names
    assert "Open Government Partnership" not in names


def test_extract_speakers_ignores_nav_and_footer_prose():
    # No structured speaker nodes -> the prose fallback runs. It must read only the
    # main content, not the site nav/footer that polluted live CSIS/CSET events
    # ("About CSIS", "Media Requests", "Events About Menu", ...).
    html = ('<nav>Explore with About CSIS Leadership Staff Media Requests</nav>'
            '<article><p>A discussion featuring Matt Pearl and Aalok Mehta.</p></article>'
            '<footer>Programs Topics Regions Privacy Policy</footer>')
    names = extract_speakers(html)
    assert "Matt Pearl" in names
    assert "Aalok Mehta" in names
    assert not any(("CSIS" in n) or ("Staff" in n) or ("Programs" in n)
                   or ("Discussion" in n) or ("Media" in n) for n in names), names


def test_extract_speakers_rejects_acronym_tokens():
    # All-caps acronyms (timezones, org initials) aren't names: "EDT Brought" (from
    # "...am EDT Brought to you by...") and "About CSIS" must not survive.
    html = '<article><p>A webcast featuring Arun Gupta and EDT Brought to you.</p></article>'
    names = extract_speakers(html)
    assert "Arun Gupta" in names
    assert not any(("EDT" in n) or ("CSIS" in n) for n in names), names


def test_extract_description_prefers_og_over_meta():
    html = ('<meta property="og:description" content="The og blurb is long enough '
            'to count as a real event description.">'
            '<meta name="description" content="A meta fallback that is also long enough.">')
    assert extract_description(html).startswith("The og blurb")


def test_extract_description_falls_back_to_meta_then_twitter():
    meta = '<meta name="description" content="Only a plain meta description, sufficiently long.">'
    assert extract_description(meta).startswith("Only a plain meta")
    tw = '<meta name="twitter:description" content="A twitter card description, long enough here.">'
    assert extract_description(tw).startswith("A twitter card")


def test_extract_description_skips_short_and_missing():
    # Below _MIN_DESC_CHARS (40) -> treated as junk and ignored.
    assert extract_description('<meta property="og:description" content="Events">') == ""
    assert extract_description("<html><head></head><body>no meta tags</body></html>") == ""


def test_extract_location_finds_postal_address():
    html = ('<div class="event-venue">The Brookings Institution, Saul Auditorium, '
            '1775 Massachusetts Ave NW, Washington, DC 20036</div>')
    loc = extract_location(html)
    assert "1775 Massachusetts Ave NW" in loc
    assert "20036" in loc


def test_extract_location_ignores_nodes_without_zip():
    # An address-classed nav blob with no ZIP must not be mistaken for a venue.
    html = '<div class="location-nav">Locations | Contact | About</div>'
    assert extract_location(html) == ""
    assert extract_location("<p>no address here</p>") == ""


def test_enrich_layer2_fills_location_from_hq_when_page_has_none():
    ev = Event(id="csis-5", title="AI", start="2026-06-01", source="csis",
               source_url="https://www.csis.org/events/ai")

    async def fake_fetch(url, kind):
        return '<meta property="og:description" content="A long enough blurb about AI policy here.">'

    asyncio.run(enrich_layer2([ev], {"csis": 2}, fake_fetch))
    assert ev.address == SOURCE_HQ["csis"]        # HQ fallback, not "TBD"


def test_enrich_layer2_prefers_scraped_address_over_hq():
    ev = Event(id="brk-1", title="AI", start="2026-06-01", source="brookings",
               source_url="https://www.brookings.edu/events/ai")

    async def fake_fetch(url, kind):
        return ('<div class="address">Brookings, Saul/Zilkha Auditorium, '
                '1775 Massachusetts Ave NW, Washington, DC 20036</div>')

    asyncio.run(enrich_layer2([ev], {"brookings": 2}, fake_fetch))
    assert "Auditorium" in ev.address              # the real scraped venue won
    assert ev.address != SOURCE_HQ["brookings"]


def test_enrich_layer2_keeps_existing_address():
    ev = Event(id="csis-6", title="AI", start="2026-06-01", source="csis",
               source_url="https://www.csis.org/events/ai",
               address="123 Real Venue St, Washington, DC 20001")

    async def fake_fetch(url, kind):
        return '<meta property="og:description" content="A long enough blurb about AI policy here.">'

    asyncio.run(enrich_layer2([ev], {"csis": 2}, fake_fetch))
    assert ev.address == "123 Real Venue St, Washington, DC 20001"  # not overwritten


def test_enrich_layer2_skips_hq_pin_for_virtual_event():
    # A webcast / virtual-only event must NOT be pinned at the org HQ (misleading).
    ev = Event(id="cnas-x", title="The Pentagon and Silicon Valley", start="2026-03-10",
               source="cnas", source_url="https://www.cnas.org/events/x")

    async def fake_fetch(url, kind):
        return ('<article><p>Join us for a virtual conversation. This is a webcast; '
                'watch live online.</p></article>')

    asyncio.run(enrich_layer2([ev], {"cnas": 2}, fake_fetch))
    assert ev.address == ""          # no physical pin for an online-only event


def test_enrich_layer2_keeps_hq_for_inperson_despite_webcast_mention():
    # "Webcast available" + an in-person signal = hybrid in-person -> HQ fallback stays.
    ev = Event(id="cnas-y", title="In person panel", start="2026-06-10",
               source="cnas", source_url="https://www.cnas.org/events/y")

    async def fake_fetch(url, kind):
        return ('<article><p>Join us in person; doors open at 9. A webcast is also '
                'available.</p></article>')

    asyncio.run(enrich_layer2([ev], {"cnas": 2}, fake_fetch))
    assert ev.address == SOURCE_HQ["cnas"]    # in-person -> HQ pin kept


def test_enrich_layer2_sets_speakers():
    events = [
        Event(id="csis-1", title="AI Talk", start="2026-06-01", source="csis",
              source_url="https://www.csis.org/events/ai-talk"),
        Event(id="dc2-1", title="Meetup", start="2026-06-01", source="DC2"),  # L1: skipped
    ]
    layer = {"csis": 2, "DC2": 1}

    async def fake_fetch(url, kind):
        return '<div class="speaker"><span class="name">Sam Altman</span></div>'

    asyncio.run(enrich_layer2(events, layer, fake_fetch))
    assert events[0].speakers == ["Sam Altman"]
    assert events[1].speakers == []          # Layer-1 event untouched


def test_enrich_layer2_fills_description_when_empty():
    ev = Event(id="csis-3", title="AI", start="2026-06-01", source="csis",
               source_url="https://www.csis.org/events/ai")

    async def fake_fetch(url, kind):
        return ('<meta property="og:description" content="A deep dive into AI compute '
                'policy and export controls in 2026.">')

    n = asyncio.run(enrich_layer2([ev], {"csis": 2}, fake_fetch))
    assert n == 1
    assert ev.description.startswith("A deep dive into AI compute policy")


def test_enrich_layer2_keeps_existing_description():
    ev = Event(id="csis-4", title="AI", start="2026-06-01", source="csis",
               source_url="https://www.csis.org/events/ai",
               description="Original listing blurb.")

    async def fake_fetch(url, kind):
        return ('<meta property="og:description" content="Meta blurb that must not '
                'overwrite the listing one.">'
                '<div class="speaker"><span class="name">Jane Roe</span></div>')

    asyncio.run(enrich_layer2([ev], {"csis": 2}, fake_fetch))
    assert ev.description == "Original listing blurb."   # not overwritten
    assert ev.speakers == ["Jane Roe"]                   # speakers still extracted


def test_enrich_structured_location_and_virtual_win():
    ev = Event(id="csis-z", title="AI", start="2026-06-04", source="csis",
               source_url="https://www.csis.org/events/z")

    async def fake_fetch(url, kind):
        return ('<script type="application/ld+json">{"@type":"Event",'
                '"startDate":"2026-06-04T14:30:00","location":{"@type":"VirtualLocation","url":"x"}}'
                '</script>')

    asyncio.run(enrich_layer2([ev], {"csis": 2}, fake_fetch))
    assert ev.raw.get("virtual") is True
    assert ev.address == ""


def test_enrich_structured_address_overrides_hq():
    ev = Event(id="brk-z", title="AI", start="2026-06-10", source="brookings",
               source_url="https://www.brookings.edu/events/z")

    async def fake_fetch(url, kind):
        return ('<script type="application/ld+json">{"@type":"Event",'
                '"location":{"@type":"Place","name":"Saul Auditorium","address":'
                '{"@type":"PostalAddress","streetAddress":"1775 Massachusetts Ave NW",'
                '"addressLocality":"Washington","addressRegion":"DC","postalCode":"20036"}}}</script>')

    asyncio.run(enrich_layer2([ev], {"brookings": 2}, fake_fetch))
    assert "1775 Massachusetts Ave NW" in ev.address
    assert ev.venue_name == "Saul Auditorium"
    assert ev.address != SOURCE_HQ["brookings"]


def test_reconcile_csis_naive_agrees_sets_end():
    from aggregator.enrich import _reconcile_time
    ev = Event(id="csis-a", title="A", start="2026-06-04T10:30:00-04:00", tz="EDT",
               source="csis", end=None)
    _reconcile_time(ev, {"start": "2026-06-04T14:30:00", "end": "2026-06-04T15:30:00"})
    assert ev.start == "2026-06-04T10:30:00-04:00"
    assert ev.end == "2026-06-04T11:30:00-04:00"
    assert ev.raw.get("start_conflict") is not True


def test_reconcile_csis_naive_conflict_downgrades():
    from aggregator.enrich import _reconcile_time
    ev = Event(id="csis-b", title="B", start="2026-06-04T10:30:00-04:00", tz="EDT",
               source="csis", end="2026-06-04T11:30:00-04:00")
    _reconcile_time(ev, {"start": "2026-06-04T20:00:00"})
    assert ev.start == "2026-06-04" and ev.end == "2026-06-04" and ev.tz is None
    assert ev.raw.get("start_conflict") is True


def test_reconcile_offset_aware_structured_wins():
    from aggregator.enrich import _reconcile_time
    ev = Event(id="x-c", title="C", start="2026-06-10", source="brookings")
    _reconcile_time(ev, {"start": "2026-06-10T09:00:00-04:00", "end": "2026-06-10T10:00:00-04:00"})
    assert ev.start == "2026-06-10T09:00:00-04:00" and ev.end == "2026-06-10T10:00:00-04:00"


def test_provenance_location_hq_tag():
    from aggregator.provenance import prov_get
    ev = Event(id="csis-p", title="AI", start="2026-06-04", source="csis",
               source_url="https://www.csis.org/events/p")

    async def fake_fetch(url, kind):
        return "<p>nothing structured, no venue</p>"

    asyncio.run(enrich_layer2([ev], {"csis": 2}, fake_fetch))
    assert ev.address == SOURCE_HQ["csis"] and prov_get(ev, "location") == "hq"


def test_provenance_location_structured_tag():
    from aggregator.provenance import prov_get
    ev = Event(id="brk-p", title="AI", start="2026-06-10", source="brookings",
               source_url="https://www.brookings.edu/events/p")

    async def fake_fetch(url, kind):
        return ('<script type="application/ld+json">{"@type":"Event","location":'
                '{"@type":"Place","address":{"@type":"PostalAddress","streetAddress":"1 A St",'
                '"addressLocality":"Washington","addressRegion":"DC","postalCode":"20001"}}}</script>')

    asyncio.run(enrich_layer2([ev], {"brookings": 2}, fake_fetch))
    assert prov_get(ev, "location") == "structured"


def test_provenance_speakers_extracted_tag():
    from aggregator.provenance import prov_get
    ev = Event(id="cset-p", title="AI", start="2026-06-10", source="cset",
               source_url="https://cset.georgetown.edu/event/p")

    async def fake_fetch(url, kind):
        return "<article><p>A discussion featuring Jane Roe and John Doe.</p></article>"

    asyncio.run(enrich_layer2([ev], {"cset": 2}, fake_fetch))
    assert ev.speakers and prov_get(ev, "speakers") == "extracted"


def test_provenance_time_structured_on_offset_win():
    from aggregator.provenance import prov_get
    from aggregator.enrich import _reconcile_time
    ev = Event(id="t1", title="T", start="2026-06-10", source="brookings")
    _reconcile_time(ev, {"start": "2026-06-10T09:00:00-04:00"})
    assert prov_get(ev, "time") == "structured"


def test_provenance_time_cleared_on_csis_conflict():
    from aggregator.provenance import prov_get, prov_set
    from aggregator.enrich import _reconcile_time
    ev = Event(id="t2", title="T", start="2026-06-04T10:30:00-04:00", tz="EDT", source="csis")
    prov_set(ev, "time", "assumed_et")
    _reconcile_time(ev, {"start": "2026-06-04T20:00:00"})
    assert prov_get(ev, "time") is None


def test_enrich_layer2_tolerates_fetch_failure():
    events = [Event(id="csis-2", title="X", start="2026-06-01", source="csis",
                    source_url="https://www.csis.org/events/x")]

    async def boom(url, kind):
        raise RuntimeError("network down")

    n = asyncio.run(enrich_layer2(events, {"csis": 2}, boom))
    assert n == 0 and events[0].speakers == []   # best-effort, no crash


def test_waf_fetch_returns_empty_on_challenge(monkeypatch):
    # A Cloudflare challenge page must never be parsed as the detail page.
    from aggregator import enrich
    monkeypatch.setattr(enrich, "curl_get", lambda url, proxy=None: (403, "Just a moment..."))
    html = asyncio.run(enrich.default_fetch("https://cdt.org/event/x/", "cdt"))
    assert html == ""


def test_waf_fetch_returns_body_on_200(monkeypatch):
    from aggregator import enrich
    monkeypatch.setattr(enrich, "curl_get", lambda url, proxy=None: (200, "<html>real</html>"))
    html = asyncio.run(enrich.default_fetch("https://cdt.org/event/x/", "cdt"))
    assert html == "<html>real</html>"
