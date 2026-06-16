"""Per-source health tracking + regression detection (enterprise observability).

Each run records, per source: last status (ok|empty|error), last event count,
last-success date, and a consecutive-failure streak. Comparing against the prior
run surfaces REGRESSIONS -- a source that fetched cleanly and now errors -- so a
silently-broken scraper is caught and alerted on, instead of just quietly shrinking
the feed. Health is persisted as JSON (durable across runs) and rendered to a
public status page.
"""
from __future__ import annotations

import json
import os
from datetime import date
from xml.sax.saxutils import escape


def classify(count: int, error: str | None) -> str:
    """ok = produced events; empty = fetched but 0 events; error = fetch failed."""
    if error:
        return "error"
    if count <= 0:
        return "empty"
    return "ok"


def is_healthy_status(status: str | None) -> bool:
    """Healthy means the source fetch completed, even with no current events."""
    return status in {"ok", "empty"}


def healthy_count(health: dict) -> int:
    return sum(1 for h in health.values() if is_healthy_status(h.get("status")))


def update_health(prior: dict, observations: list[tuple[str, int, str | None]],
                  today: str) -> tuple[dict, list[str]]:
    """Fold this run's per-source observations into the prior health map.

    `observations` is a list of (slug, count, error_or_None). Returns the new
    health map and a list of REGRESSED slugs -- sources that were healthy last run
    and now `error` (a newly-broken fetch, worth alerting on). An `ok -> empty`
    transition is NOT a regression: future-only feeds (Luma) legitimately go
    quiet, and the status page still shows them as empty. A source that was
    already failing is not a new regression.
    """
    health: dict = {}
    regressions: list[str] = []
    for slug, count, error in observations:
        st = classify(count, error)
        prev = prior.get(slug) or {}
        if is_healthy_status(st):
            health[slug] = {"slug": slug, "status": st, "count": count,
                            "last_success": today, "fail_streak": 0,
                            "reason": "" if st == "ok" else "0 events"}
        else:
            health[slug] = {"slug": slug, "status": st, "count": count,
                            "last_success": prev.get("last_success"),
                            "fail_streak": int(prev.get("fail_streak", 0)) + 1,
                            "reason": error or "0 events"}
            if is_healthy_status(prev.get("status")) and st == "error":
                regressions.append(slug)
    return health, regressions


def load_health(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_health(health: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)


def _days_since(iso: str | None, today: str) -> str:
    if not iso:
        return "never"
    try:
        d = (date.fromisoformat(today) - date.fromisoformat(iso[:10])).days
    except ValueError:
        return "?"
    return "today" if d == 0 else f"{d}d ago"


_BADGE = {"ok": ("#30d158", "● healthy"), "empty": ("#ffd60a", "○ empty"),
          "error": ("#ff453a", "✕ error")}


def render_status_html(health: dict, today: str, names: dict | None = None,
                       layers: dict | None = None) -> str:
    """A self-contained source-health status page (ops view)."""
    names = names or {}
    layers = layers or {}
    rows = sorted(health.values(), key=lambda r: (r["status"] != "error",
                                                  r["status"] != "empty", r["slug"]))
    n_healthy = healthy_count({r["slug"]: r for r in rows})
    body = []
    for r in rows:
        color, label = _BADGE.get(r["status"], ("#666", r["status"]))
        nm = escape(names.get(r["slug"], r["slug"]))
        ly = layers.get(r["slug"], "")
        streak = r.get("fail_streak", 0)
        streak_txt = f' · {streak} fail(s)' if streak else ""
        body.append(
            f'<tr><td><b>{nm}</b><br><small>{escape(r["slug"])}'
            f'{f" · L{ly}" if ly else ""}</small></td>'
            f'<td style="color:{color};font-weight:600">{label}</td>'
            f'<td style="text-align:right">{r.get("count", 0)}</td>'
            f'<td><small>{_days_since(r.get("last_success"), today)}{streak_txt}</small></td>'
            f'<td><small>{escape(str(r.get("reason") or ""))[:60]}</small></td></tr>')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Source Health · DC AI &amp; Frontier Tech Events</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;background:#000;color:#f5f5f7}}
.wrap{{max-width:780px;margin:0 auto;padding:24px}}
h1{{font-size:20px;margin:0 0 4px;letter-spacing:-.02em}}
.sub{{color:#a1a1a6;font-size:13px;margin-bottom:18px}}
table{{width:100%;border-collapse:collapse;background:#1d1d1f;border:1px solid #424245;
border-radius:16px;overflow:hidden}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #2c2c2e;font-size:14px}}
th{{background:#000;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#86868b}}
tr:last-child td{{border-bottom:none}}
small{{color:#86868b}}
.pill{{display:inline-block;padding:3px 10px;border-radius:980px;background:rgba(48,209,88,.16);color:#30d158;font-weight:600;font-size:13px}}
</style></head>
<body><div class="wrap">
<h1>Source health</h1>
<div class="sub">DC AI &amp; Frontier Tech Events · updated {escape(today)} ·
<span class="pill">{n_healthy}/{len(rows)} healthy</span></div>
<table><thead><tr><th>Source</th><th>Status</th><th>Events</th>
<th>Last OK</th><th>Detail</th></tr></thead>
<tbody>{''.join(body)}</tbody></table>
<div class="sub" style="margin-top:14px">A source is <b>empty</b> when it fetches cleanly but returns
0 events (often a genuinely empty upcoming slate); it still counts as healthy.
<b>Error</b> means the fetch itself failed.
Regressions (healthy&nbsp;→&nbsp;broken) trigger an ops alert.</div>
</div></body></html>"""
