from aggregator.models import Event
from aggregator.validate import validate_pre_filter

T = "2026-06-02"
NAMES = ["Alpha Bravo", "Charlie Delta", "Echo Foxtrot", "Golf Hotel", "India Juliet",
         "Kilo Lima", "Mike November", "Oscar Papa", "Quebec Romeo", "Sierra Tango",
         "Uniform Victor", "Whiskey Xray", "Yankee Zulu"]   # 13 digit-free names


def _ev(**kw):
    kw.setdefault("title", "x"); kw.setdefault("source", "csis"); kw.setdefault("start", "2026-06-10")
    return Event(id=kw.pop("id", "e1"), **kw)


def test_pre_excludes_implausible_date():
    clean, dropped = validate_pre_filter([_ev(start="0202-01-01")], T)
    assert clean == [] and dropped[0][1] == "date"


def test_pre_downgrades_timed_without_tz():
    ev = _ev(start="2026-06-10T11:00:00", end="2026-06-10T12:00:00", tz=None)
    clean, dropped = validate_pre_filter([ev], T)
    assert ev.start == "2026-06-10" and ev.end == "2026-06-10"
    assert any(d[1] == "time" for d in dropped)


def test_pre_drops_overlong_speaker_list_wholesale():
    ev = _ev(speakers=list(NAMES))
    validate_pre_filter([ev], T)
    assert ev.speakers == []


def test_pre_removes_junk_speakers_keeps_real():
    ev = _ev(speakers=["EDT Brought", "Arun Gupta"])
    validate_pre_filter([ev], T)
    assert ev.speakers == ["Arun Gupta"]


def test_pre_clears_address_for_pure_virtual():
    ev = _ev(address="CSIS, 1616 Rhode Island Ave NW, Washington, DC 20036",
             raw={"virtual": True})
    validate_pre_filter([ev], T)
    assert ev.address == ""


def test_pre_keeps_zipless_address():
    ev = _ev(address="Marvin Center, Washington, DC")
    validate_pre_filter([ev], T)
    assert ev.address == "Marvin Center, Washington, DC"


from aggregator.validate import validate_post_geocode

DC = (38.90, -77.04)


def test_post_nulls_out_of_bbox(tmp_path):
    ev = _ev(lat=-8.5, lng=179.2)
    validate_post_geocode([ev], T, query=None, cache_path=str(tmp_path / "gc.json"))
    assert ev.lat is None and ev.lng is None


def test_post_geo_far_from_address_pruned(tmp_path):
    ev = _ev(lat=DC[0], lng=DC[1], address="123 Far Away Rd, Washington, DC 20001")
    validate_post_geocode([ev], T, query=lambda a: (38.99, -77.20),
                          cache_path=str(tmp_path / "gc.json"), sleep=lambda *_: None)
    assert ev.lat is None


def test_post_geo_near_address_kept(tmp_path):
    ev = _ev(lat=DC[0], lng=DC[1], address="123 Near St, Washington, DC 20001")
    validate_post_geocode([ev], T, query=lambda a: (38.901, -77.041),
                          cache_path=str(tmp_path / "gc.json"), sleep=lambda *_: None)
    assert ev.lat == DC[0]


def test_post_geocoder_exception_does_not_prune_pin(tmp_path):
    def boom(a): raise OSError("down")
    ev = _ev(lat=DC[0], lng=DC[1], address="123 Some St, Washington, DC 20001")
    validate_post_geocode([ev], T, query=boom, cache_path=str(tmp_path / "gc.json"),
                          sleep=lambda *_: None)
    assert ev.lat == DC[0]


def test_post_geocoder_exception_keeps_zipless_address(tmp_path):
    def boom(a): raise OSError("down")
    ev = _ev(address="Some Hall, Washington, DC", lat=None, lng=None)
    validate_post_geocode([ev], T, query=boom, cache_path=str(tmp_path / "gc.json"),
                          sleep=lambda *_: None)
    assert ev.address == "Some Hall, Washington, DC"


def test_post_definitive_miss_nulls_zipless_address(tmp_path):
    ev = _ev(source="aic-washington", address="Nowhere Plaza", lat=None, lng=None, title="x")
    validate_post_geocode([ev], T, query=lambda a: None,
                          cache_path=str(tmp_path / "gc.json"), sleep=lambda *_: None)
    assert ev.address == ""


def test_post_zipless_address_kept_when_no_geocoder(tmp_path):
    ev = _ev(address="Marvin Center, Washington, DC", lat=None, lng=None)
    validate_post_geocode([ev], T, query=None, cache_path=str(tmp_path / "gc.json"))
    assert ev.address == "Marvin Center, Washington, DC"


def test_post_dc_recheck_excludes_nonDC_after_address_nulled(tmp_path):
    ev = _ev(source="aic-washington", address="Nowhere Plaza", raw={"location": "Nowhere Plaza"},
             lat=None, lng=None, title="AI talk")
    clean, dropped = validate_post_geocode([ev], T, query=lambda a: None,
                                           cache_path=str(tmp_path / "gc.json"), sleep=lambda *_: None)
    assert clean == [] and any(d[1] == "dc" for d in dropped)


from aggregator.provenance import prov_get, prov_set


def test_validate_clears_time_tag_on_downgrade():
    ev = _ev(start="2026-06-10T11:00:00", tz=None)
    prov_set(ev, "time", "assumed_et")
    validate_pre_filter([ev], T)
    assert prov_get(ev, "time") is None


def test_validate_clears_location_tag_on_virtual_clear():
    ev = _ev(address="CSIS HQ", raw={"virtual": True, "provenance": {"location": "hq"}})
    validate_pre_filter([ev], T)
    assert prov_get(ev, "location") is None


def test_validate_clears_speakers_tag_when_emptied():
    ev = _ev(speakers=["EDT Brought"])
    prov_set(ev, "speakers", "extracted")
    validate_pre_filter([ev], T)
    assert ev.speakers == [] and prov_get(ev, "speakers") is None


def test_validate_post_clears_location_tag_on_address_null(tmp_path):
    ev = _ev(source="aic-washington", address="Nowhere Plaza", lat=None, lng=None, title="x")
    prov_set(ev, "location", "scraped")
    validate_post_geocode([ev], T, query=lambda a: None,
                          cache_path=str(tmp_path / "gc.json"), sleep=lambda *_: None)
    assert ev.address == "" and prov_get(ev, "location") is None
