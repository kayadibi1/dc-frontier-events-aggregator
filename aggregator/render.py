"""Headless rendering for JS-built event pages (the jsrender adapter).

Company / association event pages inject their content with client-side JS, which
plain httpx/curl_cffi can't see. `render(url)` drives a shared headless Chromium
(Playwright) to render the page and return the final HTML; `extract.py` then applies
the same structured-extraction discipline as every other source.

Design:
- ONE shared browser per process, launched lazily and reused (launching per page is
  far too costly). It and the concurrency semaphore are created inside the running
  loop on first use and reset by `close_render()`, so they never leak across event
  loops (each test / each pipeline run gets a clean lifecycle).
- Bounded concurrency (<=3 pages) caps memory on a modest box.
- NEVER raises: any launch/navigation/timeout error returns "" so the calling adapter
  quarantines the source (logged, never fabricated), exactly like other fetch failures.
`gather_all` calls `close_render()` in its finally, so the browser closes inside the
same loop it was created in.
"""
from __future__ import annotations

import asyncio

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_MAX_CONCURRENT = 3
_SETTLE_MS = 3000          # let JS render when no wait_for selector is given

_pw = None
_browser = None
_sem: asyncio.Semaphore | None = None
_launch_lock: asyncio.Lock | None = None


async def _ensure_browser():
    global _pw, _browser, _launch_lock
    if _browser is not None:
        return _browser
    if _launch_lock is None:
        _launch_lock = asyncio.Lock()
    async with _launch_lock:                 # serialize the first launch (no double-launch race)
        if _browser is None:
            from playwright.async_api import async_playwright
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(headless=True)
    return _browser


async def render(url: str, wait_for: str | None = None, timeout_ms: int = 15000) -> str:
    """Render `url` and return its final HTML, or "" on any failure. `wait_for` is a
    CSS selector to await before reading content; without it we give JS a short
    settle window."""
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(_MAX_CONCURRENT)
    try:
        browser = await _ensure_browser()
    except Exception:  # noqa: BLE001 -- browser unavailable -> caller quarantines
        return ""
    async with _sem:
        ctx = None
        try:
            ctx = await browser.new_context(user_agent=_UA)
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=timeout_ms)
            else:
                await page.wait_for_timeout(_SETTLE_MS)
            return await page.content()
        except Exception:  # noqa: BLE001 -- nav/timeout/etc -> "" (never raise)
            return ""
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001
                    pass


async def close_render() -> None:
    """Close the shared browser. No-op if never launched. Resets module state so the
    next render() re-launches cleanly (in whatever loop is then running)."""
    global _pw, _browser, _sem, _launch_lock
    try:
        if _browser is not None:
            await _browser.close()
        if _pw is not None:
            await _pw.stop()
    except Exception:  # noqa: BLE001
        pass
    finally:
        _browser = None
        _pw = None
        _sem = None
        _launch_lock = None
