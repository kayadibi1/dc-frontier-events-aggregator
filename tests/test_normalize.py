from aggregator.config import Source
from aggregator.normalize import parse_ics

SRC = Source("DC2", "DC Data & AI Events", "luma", 1, True, cal_id="cal-x")

# `\\n` here -> a literal backslash-n in the runtime string == the iCal in-value
# newline escape, which icalendar decodes to a real newline on parse.
SAMPLE_ICS = "\n".join([
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Test//EN",
    "BEGIN:VEVENT",
    "DTSTART:20260610T230000Z",
    "DTEND:20260611T010000Z",
    "DTSTAMP:20260529T105446Z",
    'ORGANIZER;CN="Data Community DC":MAILTO:x@lu.ma',
    "UID:evt-TEST123@events.lu.ma",
    "SUMMARY:Hands-on Machine Learning and AI Workshop",
    ("DESCRIPTION:Get up-to-date information at: https://luma.com/test-ml"
     "\\n\\nAddress:\\nExcella 2300 Wilson Blvd Arlington VA 22201"),
    "LOCATION:Excella 2300 Wilson Blvd Arlington VA 22201 USA",
    "GEO:38.8896;-77.0908",
    "END:VEVENT",
    "END:VCALENDAR",
])


def test_parse_basic_fields():
    events = parse_ics(SRC, SAMPLE_ICS)
    assert len(events) == 1
    ev = events[0]
    assert ev.id == "evt-TEST123"          # UID stripped of @domain
    assert ev.start.startswith("2026-06-10")
    assert ev.source == "DC2"
    assert ev.organizer == "Data Community DC"


def test_geo_parsed():
    ev = parse_ics(SRC, SAMPLE_ICS)[0]
    assert ev.lat is not None and ev.lng is not None
    assert abs(ev.lat - 38.8896) < 1e-4
    assert abs(ev.lng - (-77.0908)) < 1e-4


def test_source_url_and_address_from_description():
    ev = parse_ics(SRC, SAMPLE_ICS)[0]
    assert ev.source_url == "https://luma.com/test-ml"
    assert "Excella" in ev.address


def test_topics_detected():
    ev = parse_ics(SRC, SAMPLE_ICS)[0]
    assert "ml" in ev.topics
    assert "ai" in ev.topics


def test_event_without_title_skipped():
    ics = SAMPLE_ICS.replace("SUMMARY:Hands-on Machine Learning and AI Workshop", "SUMMARY:")
    assert parse_ics(SRC, ics) == []


def test_url_property_used_as_source_url():
    # An iCal URL property (Localist-style) is used when there's no Luma
    # "information at:" line in the description.
    ics = "\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Localist//EN", "BEGIN:VEVENT",
        "DTSTART:20260701T180000Z", "UID:evt-LOCALIST1@gwu",
        "SUMMARY:GWU AI Policy Seminar",
        "DESCRIPTION:A seminar on AI governance.",
        "URL:https://calendar.gwu.edu/ai_policy_seminar",
        "LOCATION:Marvin Center, Washington, DC",
        "END:VEVENT", "END:VCALENDAR",
    ])
    ev = parse_ics(SRC, ics)[0]
    assert ev.source_url == "https://calendar.gwu.edu/ai_policy_seminar"
