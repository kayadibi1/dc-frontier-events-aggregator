from aggregator.config import Source
from aggregator.fetchers.policy_ngos import (
    DetailSeed,
    _event_from_detail,
    parse_fas_item,
    parse_newamerica_item,
)
from aggregator.filter import apply_filters


def _src(slug: str, kind: str | None = None, dc: bool = True) -> Source:
    return Source(slug, slug, kind or slug, 2, dc, url=f"https://example.test/{slug}")


def test_hudson_detail_uses_event_date_not_unrelated_page_dates():
    html = """
    <html><body>
      <nav>Commentary May 25, 2026 7 Min Read</nav>
      <main class="p-event-detail">
        <div>25 June 2026</div>
        <div>In-Person Event</div>
        <h1>Securing America's AI Advantage</h1>
        <div>THURSDAY 8:30 a.m. - 9:30 a.m.</div>
        <p>Join a fireside chat on export controls, technology, and AI development.</p>
      </main>
    </body></html>
    """
    ev = _event_from_detail(
        _src("hudson"), DetailSeed("https://www.hudson.org/events/ai-advantage"), html,
        "Hudson Institute")
    assert ev is not None
    assert ev.start == "2026-06-25T08:30:00-04:00"
    assert ev.end == "2026-06-25T09:30:00-04:00"
    assert ev.address.startswith("Hudson Institute")
    assert "ai" in ev.topics


def test_aei_detail_extracts_live_online_time_and_virtual_flag():
    html = """
    <main>
      <h1>The Commission on AI and the Future of the American Workforce</h1>
      <div class="date">Thursday, June 11, 2026 | 10:00 AM to 11:00 AM ET</div>
      <div class="location">Live Online</div>
      <p>Artificial Intelligence, Technology & Innovation, Workforce Development.</p>
    </main>
    """
    ev = _event_from_detail(
        _src("aei"), DetailSeed("https://www.aei.org/events/commission-ai-workforce/"),
        html, "AEI")
    assert ev is not None
    assert ev.start == "2026-06-11T10:00:00-04:00"
    assert ev.end == "2026-06-11T11:00:00-04:00"
    assert ev.raw["virtual"] is True
    assert not ev.address


def test_bpc_detail_extracts_when_where_block():
    html = """
    <article>
      <h1>Smarter by Design: Trust, Adoption, and the Future of AI Wearables</h1>
      <p>Past Event</p>
      <p>When May 11, 2026 4:00 p.m. to 6:00 p.m. EDT</p>
      <p>Where Rayburn HOB Washington, D.C.</p>
      <p>Use and applications of AI-powered wearable devices are rapidly growing.</p>
    </article>
    """
    ev = _event_from_detail(
        _src("bpc"), DetailSeed("https://bipartisanpolicy.org/event/ai-wearables/"),
        html, "Bipartisan Policy Center")
    assert ev is not None
    assert ev.start == "2026-05-11T16:00:00-04:00"
    assert ev.end == "2026-05-11T18:00:00-04:00"
    assert ev.address == "Rayburn HOB Washington, D.C."
    assert "ai" in ev.topics


def test_newamerica_rest_item_uses_acf_event_datetime():
    item = {
        "slug": "online-on-sovereign-ai",
        "link": "https://www.newamerica.org/events/online-on-sovereign-ai/",
        "title": {"rendered": "On Sovereign AI"},
        "acf": {"details": {
            "abstract": "A keynote panel on national approaches to AI governance.",
            "location": "",
            "location_line_2": "",
            "location_line_3": "",
            "helper_taxonomies": {"event_type": 3864},
            "date_time": {
                "all_day": False,
                "start_date": "20260610",
                "start_time": "13:00:00",
                "end_date": "20260610",
                "end_time": "14:30:00",
            },
        }},
    }
    ev = parse_newamerica_item(_src("newamerica"), item)
    assert ev is not None
    assert ev.start == "2026-06-10T13:00:00-04:00"
    assert ev.end == "2026-06-10T14:30:00-04:00"
    assert ev.raw["virtual"] is True
    assert "ai" in ev.topics


def test_fas_rest_item_extracts_compact_date_line_and_dc_location():
    item = {
        "slug": "ai-global-risk-gala",
        "link": "https://fas.org/event/ai-global-risk-gala/",
        "title": {"rendered": "AI &amp; Global Risk Gala"},
        "excerpt": {"rendered": "AI and global risk."},
        "content": {"rendered": """
            <h1>AI &amp; Global Risk Gala</h1>
            <p>05.20.26 | 6:00 PM - 9:00 PM | Washington, DC</p>
            <p>Artificial intelligence and global risks nexus.</p>
        """},
    }
    ev = parse_fas_item(_src("fas"), item)
    assert ev is not None
    assert ev.start == "2026-05-20T18:00:00-04:00"
    assert ev.end == "2026-05-20T21:00:00-04:00"
    assert ev.address == "Washington, DC"


def test_scsp_jsonld_event_gets_hq_when_offline_location_is_blank():
    html = """
    <script type="application/ld+json">{
      "@context": "https://schema.org/",
      "@type": "Event",
      "name": "AI+ Fusion",
      "description": "Artificial intelligence and fusion policy.",
      "eventAttendanceMode": "OfflineEventAttendanceMode",
      "startDate": "2026-07-23T00:00:00-04:00",
      "location": [{"@type": "Place", "name": ""}]
    }</script>
    <h1>AI+ Fusion</h1>
    """
    ev = _event_from_detail(
        _src("scsp"), DetailSeed("https://www.scsp.ai/event/ai-fusion/"), html, "SCSP")
    assert ev is not None
    assert ev.start == "2026-07-23T00:00:00-04:00"
    assert ev.address.startswith("Special Competitive Studies Project")


def test_rand_jsonld_virtual_event_keeps_no_dc_address_for_strict_filtering():
    html = """
    <script type="application/ld+json">{
      "@context": "https://schema.org",
      "@type": "Event",
      "name": "AI and Adolescent Mental Health",
      "eventAttendanceMode": "https://schema.org/OnlineEventAttendanceMode",
      "location": {"@type": "VirtualLocation", "url": "https://www.rand.org/events/x.html"},
      "startDate": "2026-05-27T12:00:00-04:00",
      "endDate": "2026-05-27T13:00:00-04:00"
    }</script>
    """
    ev = _event_from_detail(
        _src("rand", dc=False), DetailSeed("https://www.rand.org/events/x.html"),
        html, "RAND")
    assert ev is not None
    assert ev.raw["virtual"] is True
    assert ev.address == ""


def test_irrelevant_policy_event_is_dropped_by_topic_gate():
    html = """
    <main>
      <h1>France, Islam, and Immigration: Lessons for America</h1>
      <p>Jun 11, 2026 5:00 p.m. - 5:45 p.m.</p>
      <p>Where Online</p>
      <p>A foreign policy discussion.</p>
    </main>
    """
    ev = _event_from_detail(
        _src("heritage"), DetailSeed("https://www.heritage.org/europe/event/x"),
        html, "Heritage Foundation")
    assert ev is not None
    kept, stats = apply_filters([ev])
    assert kept == []
    assert stats["dropped_topic"] == 1


def test_canceled_detail_is_not_emitted():
    html = """
    <main>
      <h1>CANCELED - Documentary Screening: Artifact War</h1>
      <div>April 4, 2026</div>
    </main>
    """
    ev = _event_from_detail(
        _src("wilson"), DetailSeed("https://www.wilsoncenter.org/event/canceled"), html,
        "Wilson Center")
    assert ev is None

