from aggregator.models import Event
from aggregator.remote import is_remote, is_hybrid, safe_watch_url, detect_remote


def _ev(**raw):
    return Event(id="x", title="t", start="2026-07-01", source="csis",
                 address=raw.pop("address", ""), raw=raw)


def test_is_remote_from_virtual():
    assert is_remote(_ev(virtual=True)) is True


def test_is_remote_from_flag():
    assert is_remote(_ev(remote=True)) is True


def test_is_remote_false():
    assert is_remote(_ev()) is False


def test_is_hybrid_only_when_remote_inperson_not_virtual():
    assert is_hybrid(_ev(remote=True, address="100 K St, Washington, DC")) is True
    assert is_hybrid(_ev(virtual=True)) is False                 # fully virtual
    assert is_hybrid(_ev(remote=True)) is False                  # no address


def test_safe_watch_url_blocks_non_http():
    assert safe_watch_url(_ev(watch_url="javascript:alert(1)")) == ""
    assert safe_watch_url(_ev(watch_url="https://zoom.us/j/9")) == "https://zoom.us/j/9"


def test_detect_strong_host():
    html = '<main><p>Join us <a href="https://zoom.us/j/123">here</a></p></main>'
    assert detect_remote(html) == (True, "https://zoom.us/j/123")


def test_detect_youtube_live_path():
    html = '<article><a href="https://www.youtube.com/live/abc">stream</a></article>'
    assert detect_remote(html)[0] is True


def test_detect_phrase_plus_link():
    html = ('<main><p>This event will be livestreamed. '
            '<a href="https://example.org/register">Register here</a></p></main>')
    found, url = detect_remote(html)
    assert found is True and url == "https://example.org/register"


def test_detect_weak_host_needs_phrase():
    # bare youtube watch link with no live phrase -> not flagged
    html = '<main><p>More info <a href="https://youtube.com/watch?v=z">video</a></p></main>'
    assert detect_remote(html) == (False, "")
    # same link WITH a live phrase in the block -> flagged
    html2 = '<main><p>Watch live <a href="https://youtube.com/watch?v=z">here</a></p></main>'
    assert detect_remote(html2)[0] is True


def test_detect_negative_recording_guard():
    html = ('<main><p>Watch the recording of our past event '
            '<a href="https://zoom.us/rec/9">here</a></p></main>')
    assert detect_remote(html) == (False, "")


def test_detect_negation_guard():
    html = ('<main><p>This event will NOT be livestreamed. '
            '<a href="https://example.org/x">info</a></p></main>')
    assert detect_remote(html) == (False, "")


def test_detect_inperson_only_guard():
    html = '<main><p>In-person only. <a href="https://zoom.us/j/1">map</a></p></main>'
    assert detect_remote(html) == (False, "")


def test_detect_ignores_footer_and_channel():
    # footer youtube channel link outside <main> -> ignored
    html = ('<main><p>An in-person talk in DC.</p></main>'
            '<footer><a href="https://youtube.com/@org">Our channel</a></footer>')
    assert detect_remote(html) == (False, "")


def test_detect_relative_link_resolved():
    html = '<main><p>Watch online <a href="/live">stream</a></p></main>'
    found, url = detect_remote(html, base_url="https://csis.org/event/1")
    assert found is True and url == "https://csis.org/live"


# --- Codex stress-test regression cases ---

def test_detect_strong_host_privacy_link_not_flagged():
    # a footer/sponsor "powered by Zoom" privacy link must NOT flag the event
    html = '<main><article><h1>In-person AI talk</h1><p>Sponsored by ' \
           '<a href="https://zoom.us/privacy">Zoom</a></p></article></main>'
    assert detect_remote(html) == (False, "")


def test_detect_skips_related_events_block():
    html = ('<main><section class="related"><p>Watch live '
            '<a href="https://zoom.us/j/9">Other event</a></p></section>'
            '<article><h1>This event</h1><p>In-person in DC.</p></article></main>')
    assert detect_remote(html) == (False, "")


def test_detect_prefers_video_host_over_press_kit():
    html = ('<main><p>Watch live on YouTube. '
            '<a href="https://example.org/press-kit">Press kit</a> '
            '<a href="https://youtube.com/watch?v=abc">Video</a></p></main>')
    found, url = detect_remote(html)
    assert found is True and "youtube.com/watch" in url


def test_detect_webex_event_host():
    html = '<main><p>Register <a href="https://events.webex.com/event/abc">RSVP</a></p></main>'
    assert detect_remote(html)[0] is True


def test_safe_watch_url_non_string_is_empty():
    ev = Event(id="x", title="t", start="2026-07-01", source="csis",
               raw={"remote": True, "watch_url": ["https://zoom.us/j/1"]})
    assert safe_watch_url(ev) == ""


def test_detect_strong_link_in_layout_sidebar_content():
    # CSET-style: the register CTA lives in a layout "sidebar" content div, which
    # is the event body, NOT chrome. Must still flag (regression for an over-broad
    # exclusion that dropped real watch links).
    html = ('<main class="main"><div class="l-sidebar"><div class="l-sidebar__main post-content">'
            '<h1>Workforce</h1>'
            '<a href="https://georgetown.zoom.us/webinar/register/WN_x">Register</a>'
            '</div></div></main>')
    found, url = detect_remote(html)
    assert found is True and "georgetown.zoom.us" in url
