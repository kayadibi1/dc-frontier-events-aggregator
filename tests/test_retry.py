import asyncio

from aggregator.config import Source
from aggregator.fetchers import _fetch_with_retry, _is_transient
from aggregator.fetchers.base import SourceResult
from aggregator.models import Event

SRC = Source("x", "X", "x", 2, True)


async def _nosleep(_):
    pass


def _ok_result(src):
    return SourceResult(src, [Event(id="e", title="t", start="2026-07-01", source="x")], 200, None)


def test_is_transient_classification():
    assert _is_transient(SourceResult(SRC, [], None, "boom"))        # raised exception
    assert _is_transient(SourceResult(SRC, [], 503, "HTTP 503"))     # 5xx
    assert _is_transient(SourceResult(SRC, [], 429, "HTTP 429"))     # rate-limited
    assert not _is_transient(SourceResult(SRC, [], 404, "HTTP 404"))  # permanent
    assert not _is_transient(SourceResult(SRC, [], 200, None))        # real empty slate


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    async def flaky(src):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("net blip")
        return _ok_result(src)

    res = asyncio.run(_fetch_with_retry(SRC, flaky, tries=3, sleep=_nosleep))
    assert res.ok and calls["n"] == 3


def test_no_retry_on_permanent_404():
    calls = {"n": 0}

    async def notfound(src):
        calls["n"] += 1
        return SourceResult(src, [], 404, "HTTP 404")

    res = asyncio.run(_fetch_with_retry(SRC, notfound, tries=3, sleep=_nosleep))
    assert calls["n"] == 1 and not res.ok          # not retried


def test_no_retry_on_real_empty_result():
    calls = {"n": 0}

    async def empty(src):
        calls["n"] += 1
        return SourceResult(src, [], 200, None)

    res = asyncio.run(_fetch_with_retry(SRC, empty, tries=3, sleep=_nosleep))
    assert calls["n"] == 1                          # empty is a real answer, not retried


def test_gives_up_after_max_tries():
    calls = {"n": 0}

    async def always_fail(src):
        calls["n"] += 1
        raise OSError("down")

    res = asyncio.run(_fetch_with_retry(SRC, always_fail, tries=3, sleep=_nosleep))
    assert calls["n"] == 3 and not res.ok
