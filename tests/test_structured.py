from aggregator.structured import extract_structured

CSIS = open("tests/fixtures/csis_event_jsonld.html", encoding="utf-8").read()

PLACE = """<script type="application/ld+json">
{"@type":"Event","name":"Panel","startDate":"2026-06-10T10:00:00-04:00",
 "endDate":"2026-06-10T11:00:00-04:00",
 "location":{"@type":"Place","name":"Saul Auditorium","address":{"@type":"PostalAddress",
   "streetAddress":"1775 Massachusetts Ave NW","addressLocality":"Washington",
   "addressRegion":"DC","postalCode":"20036"}},
 "performer":[{"@type":"Person","name":"Neil Thompson"},{"@type":"Person","name":"Sanjay Patnaik"}]}
</script>"""

HYBRID = """<script type="application/ld+json">
{"@type":"Event","name":"Hybrid","startDate":"2026-06-10T10:00:00-04:00",
 "eventAttendanceMode":"https://schema.org/MixedEventAttendanceMode",
 "location":[{"@type":"Place","name":"HQ","address":{"@type":"PostalAddress",
   "streetAddress":"1400 L St NW","addressLocality":"Washington","addressRegion":"DC","postalCode":"20005"}},
   {"@type":"VirtualLocation","url":"https://x"}]}
</script>"""

ONLINE_MODE = """<script type="application/ld+json">
{"@type":"Event","name":"Webinar","startDate":"2026-06-10T10:00:00",
 "eventAttendanceMode":"https://schema.org/OnlineEventAttendanceMode"}
</script>"""

GRAPH = """<script type="application/ld+json">
{"@graph":[{"@type":"WebPage"},{"@type":["Event"],"name":"G","startDate":"2026-07-01"}]}
</script>"""


def test_csis_virtual_naive_start():
    out = extract_structured(CSIS)
    assert out["virtual"] is True
    assert out["start"] == "2026-06-04T14:30:00"
    assert out["end"] == "2026-06-04T15:30:00"
    assert "address" not in out and "venue_name" not in out


def test_place_offset_aware_with_address_and_speakers():
    out = extract_structured(PLACE)
    assert out["start"] == "2026-06-10T10:00:00-04:00"
    assert out["venue_name"] == "Saul Auditorium"
    assert "1775 Massachusetts Ave NW" in out["address"] and "20036" in out["address"]
    assert out["speakers"] == ["Neil Thompson", "Sanjay Patnaik"]
    assert "virtual" not in out


def test_hybrid_keeps_physical_address():
    out = extract_structured(HYBRID)
    assert "1400 L St NW" in out["address"]
    assert out.get("attendance_mode") == "mixed"
    assert out.get("virtual") is not True


def test_online_attendance_mode_without_virtuallocation():
    out = extract_structured(ONLINE_MODE)
    assert out["virtual"] is True and out.get("attendance_mode") == "online"


def test_graph_form_and_type_list():
    assert extract_structured(GRAPH)["start"] == "2026-07-01"


def test_malformed_and_missing_return_empty():
    assert extract_structured('<script type="application/ld+json">{bad json}</script>') == {}
    assert extract_structured("<p>no markup</p>") == {}
    assert extract_structured('<script type="application/ld+json">{"@type":"WebPage"}</script>') == {}


def test_og_meta_never_sets_event_fields():
    html = ('<meta property="og:title" content="X">'
            '<meta property="article:published_time" content="2020-01-01T00:00:00Z">')
    assert extract_structured(html) == {}


def test_extract_structured_returns_name():
    html = ('<script type="application/ld+json">{"@type":"Event","name":"AI Policy Panel",'
            '"startDate":"2026-07-01"}</script>')
    assert extract_structured(html)["name"] == "AI Policy Panel"
