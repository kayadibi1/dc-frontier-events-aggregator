from aggregator.health import classify, healthy_count, update_health


def test_classify():
    assert classify(5, None) == "ok"
    assert classify(0, None) == "empty"
    assert classify(3, "HTTP 403") == "error"   # error wins even with a count


def test_ok_source_records_success_today():
    health, regressions = update_health({}, [("itif", 5, None)], "2026-06-02")
    assert health["itif"]["status"] == "ok"
    assert health["itif"]["count"] == 5
    assert health["itif"]["last_success"] == "2026-06-02"
    assert health["itif"]["fail_streak"] == 0
    assert regressions == []


def test_empty_source_is_healthy_success_today():
    health, regressions = update_health({}, [("dctech", 0, None)], "2026-06-02")
    assert health["dctech"]["status"] == "empty"
    assert health["dctech"]["last_success"] == "2026-06-02"
    assert health["dctech"]["fail_streak"] == 0
    assert healthy_count(health) == 1
    assert regressions == []


def test_regression_when_previously_ok_now_failing():
    prior = {"cdt": {"status": "ok", "count": 12, "last_success": "2026-06-01", "fail_streak": 0}}
    health, regressions = update_health(prior, [("cdt", 0, "HTTP 403")], "2026-06-02")
    assert "cdt" in regressions
    assert health["cdt"]["status"] == "error"
    assert health["cdt"]["fail_streak"] == 1
    assert health["cdt"]["last_success"] == "2026-06-01"   # carried forward


def test_empty_to_error_is_regression():
    prior = {"x": {"status": "empty", "count": 0, "last_success": "2026-06-01", "fail_streak": 0}}
    health, regressions = update_health(prior, [("x", 0, "HTTP 500")], "2026-06-02")
    assert "x" in regressions
    assert health["x"]["status"] == "error"
    assert health["x"]["last_success"] == "2026-06-01"
    assert health["x"]["fail_streak"] == 1


def test_still_erroring_is_not_a_new_regression():
    prior = {"x": {"status": "error", "count": 0, "last_success": None, "fail_streak": 2}}
    health, regressions = update_health(prior, [("x", 0, "HTTP 500")], "2026-06-02")
    assert regressions == []                # already failing, not newly broken
    assert health["x"]["fail_streak"] == 3


def test_brand_new_failing_source_is_not_a_regression():
    health, regressions = update_health({}, [("new", 0, "HTTP 500")], "2026-06-02")
    assert regressions == []
    assert health["new"]["fail_streak"] == 1


def test_ok_to_empty_is_quiet_not_regression():
    # A community calendar with a legitimately empty upcoming slate is not a
    # newly-broken source; only ok->error alerts.
    prior = {"dctech": {"status": "ok", "count": 24,
                        "last_success": "2026-06-08", "fail_streak": 0}}
    health, regressions = update_health(prior, [("dctech", 0, None)], "2026-06-09")
    assert regressions == []
    assert health["dctech"]["status"] == "empty"
    assert health["dctech"]["last_success"] == "2026-06-09"
    assert health["dctech"]["fail_streak"] == 0


def test_status_page_is_noindex():
    from aggregator.health import render_status_html
    html = render_status_html({}, "2026-06-09")
    assert '<meta name="robots" content="noindex">' in html


def test_status_page_counts_empty_as_healthy():
    from aggregator.health import render_status_html
    health = {
        "a": {"slug": "a", "status": "ok", "count": 2, "last_success": "2026-06-09"},
        "b": {"slug": "b", "status": "empty", "count": 0, "last_success": "2026-06-09"},
        "c": {"slug": "c", "status": "error", "count": 0, "last_success": None},
    }
    html = render_status_html(health, "2026-06-09")
    assert "2/3 healthy" in html
