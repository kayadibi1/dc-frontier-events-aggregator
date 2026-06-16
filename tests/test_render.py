import asyncio
import os

import pytest

from aggregator.render import close_render, render


def _has_browser() -> bool:
    """True only if a Playwright chromium is actually installed (so the test skips
    cleanly on hosts where the browser isn't/can't be installed, e.g. the box)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


@pytest.mark.skipif(not _has_browser(), reason="no Playwright chromium installed")
def test_render_returns_html_and_never_raises():
    async def go():
        html = await render("data:text/html,<h1 id=x>Hi there</h1>", wait_for="#x")
        assert "Hi there" in html
        bad = await render("http://nonexistent.invalid.localhost:1/")
        assert bad == ""                         # failures return "" not raise
        await close_render()

    asyncio.run(go())
