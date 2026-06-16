"""Orchestrate fetch -> normalize -> dedupe -> filter -> store -> emit, logging
concrete counts at each stage. Returns a summary dict (also used by tests).
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

from .config import SOURCES
from .dedupe import dedupe
from .emit import filter_upcoming, write_ics, write_json, write_rss
from .enrich import default_fetch, enrich_layer2, recompute_topics
from .geocode import DEFAULT_CACHE, geocode_events, nominatim_query, scrub_far_geo
from .validate import validate_pre_filter, validate_post_geocode
from .fetchers import gather_all
from .filter import apply_filters
from .health import healthy_count, load_health, update_health, write_health
from .rank import score_event, top_upcoming
from .storage import open_store


def same_day_actives(active, clean_ids, today: str) -> list:
    """Future-only sources (Luma JSON) stop reporting an event the moment it
    starts; keep already-started same-day events active and visible until the
    day ends instead of archiving them mid-day. (They roll off naturally on
    the first build after their date.)"""
    return [e for e in active
            if (e.start or "")[:10] == today and e.id not in clean_ids]


def run(out_dir: str = "out", db_path: str = "data/events.db",
        today: str | None = None, enrich: bool = True) -> dict:
    today = today or datetime.now(timezone.utc).date().isoformat()
    results = asyncio.run(gather_all(SOURCES))

    per_source: dict[str, int] = {}
    layers_live: set[int] = set()
    raw_events = []
    quarantined = []
    for res in results:
        per_source[res.source.slug] = len(res.events)
        if not res.healthy:
            per_source[res.source.slug] = 0
            quarantined.append((res.source.slug, res.reason))
            print(f"[fetch] QUARANTINE {res.source.slug}: {res.reason}")
            continue
        if res.events:
            layers_live.add(res.source.layer)
            raw_events.extend(res.events)
        print(f"[fetch] {res.source.slug} (layer {res.source.layer}): {len(res.events)} events")

    # Per-source health + regression detection (observability): persist each run's
    # per-source status and flag any source that was healthy last run and is now
    # broken, so a silently-failing scraper is caught, not just absorbed.
    health_path = os.path.join(os.path.dirname(db_path) or ".", "source_health.json")
    prior_health = load_health(health_path)
    observations = [(r.source.slug, len(r.events), r.error) for r in results]
    health, regressions = update_health(prior_health, observations, today)
    write_health(health, health_path)
    if regressions:
        print(f"[health] REGRESSIONS (healthy -> broken since last run): {', '.join(regressions)}")
    healthy = healthy_count(health)

    total_raw = len(raw_events)
    if enrich:
        layer_by_source = {s.slug: s.layer for s in SOURCES}
        n_enriched = asyncio.run(enrich_layer2(raw_events, layer_by_source, default_fetch))
        print(f"[enrich] enriched {n_enriched} Layer-2 events (descriptions + speakers)")
        # Re-derive topics from enriched blurbs for curated Layer-2 policy sources,
        # so a vague-titled but on-topic event ("A Conversation With...") is kept.
        curated_l2 = {s.slug for s in SOURCES if s.layer == 2 and s.dc_curated}
        recompute_topics(raw_events, curated_l2)
    raw_events, pre_dropped = validate_pre_filter(raw_events, today)
    print(f"[validate] pre-filter: excluded "
          f"{sum(1 for d in pre_dropped if d[1] == 'date')}, cleaned {len(pre_dropped)} field(s)")
    deduped, removed = dedupe(raw_events)
    kept, fstats = apply_filters(deduped)

    store = open_store(db_path)
    prior_ids = store.existing_ids()          # ids known before this run -> new diff
    store.close()

    # Scrub junk feed GEO BEFORE geocode so a real DC address can re-pin.
    scrub_far_geo(kept)
    if enrich:
        n_geo = geocode_events(kept)
        print(f"[geocode] added coordinates to {n_geo} event(s)")
    clean, post_dropped = validate_post_geocode(
        kept, today, query=nominatim_query if enrich else None,
        cache_path=DEFAULT_CACHE if enrich else None)
    print(f"[validate] post-geocode: dropped {len(post_dropped)} field(s); "
          f"kept {len(clean)}/{len(kept)}")

    # Persist the VALIDATED active set; the store is the durable archive.
    store = open_store(db_path)
    store.upsert_many(clean)
    clean_ids = {e.id for e in clean}
    keep_today = same_day_actives(store.active_events(), clean_ids, today)
    archived_total = store.mark_archived(clean_ids | {e.id for e in keep_today})
    # Prune archived events older than ~2 years to bound store growth.
    cutoff = (date.fromisoformat(today) - timedelta(days=730)).isoformat()
    pruned = store.prune(cutoff)
    roundtrip = store.all_events()
    store_total = store.count()
    store.close()
    assert len(roundtrip) >= len(clean), "storage round-trip lost rows"
    gone = sorted(set(prior_ids) - {e.id for e in clean})  # in store, not in this run

    emitted = sorted(clean + keep_today, key=lambda e: e.start or "")
    for e in emitted:
        e.raw["score"] = score_event(e, today)   # ephemeral; AFTER store
    big = [e for e in emitted if e.is_big_name]
    upcoming = filter_upcoming(emitted, today)
    top = top_upcoming(emitted, today, 25)
    ics_n = write_ics(emitted, f"{out_dir}/events.ics", today,
                      cal_name="DC AI & Frontier Tech Events")
    rss_n = write_rss(emitted, f"{out_dir}/feed.xml")
    write_ics(big, f"{out_dir}/events-big-names.ics", today,
              cal_name="DC AI / Marquee")
    write_rss(big, f"{out_dir}/feed-big-names.xml", "DC AI & Frontier Tech -- Marquee")
    up_n = write_ics(upcoming, f"{out_dir}/events-upcoming.ics", today,
                     cal_name="DC AI & Frontier Tech / Upcoming")
    write_rss(upcoming, f"{out_dir}/feed-upcoming.xml", "DC AI & Frontier Tech -- Upcoming")
    write_rss(top, f"{out_dir}/feed-top.xml", "DC AI & Frontier Tech -- Top Picks")
    write_json(emitted, f"{out_dir}/events.json")
    write_health(health, f"{out_dir}/health.json")
    archive_n = write_ics(sorted(roundtrip, key=lambda e: e.start or ""),
                          f"{out_dir}/events-archive.ics", today,
                          cal_name="DC AI & Frontier Tech / Archive")

    new_events = [e for e in emitted if e.id not in prior_ids]
    new_big = [e for e in new_events if e.is_big_name]

    summary = {
        "sources_total": len(SOURCES),
        "sources_live": sum(1 for v in per_source.values() if v > 0),
        "sources_healthy": healthy,
        "regressions": regressions,
        "layers_live": sorted(layers_live),
        "per_source": per_source,
        "quarantined": quarantined,
        "raw_events": total_raw,
        "after_dedupe": len(deduped),
        "deduped_removed": removed,
        "kept_after_filter": len(clean),
        "pre_excluded": sum(1 for d in pre_dropped if d[1] == "date"),
        "post_excluded": sum(1 for d in post_dropped if d[1] == "dc"),
        "dropped_location": fstats["dropped_location"],
        "dropped_topic": fstats["dropped_topic"],
        "dropped_admin": fstats["dropped_admin"],
        "big_name": len(big),
        "new_events": len(new_events),
        "new_big_name": len(new_big),
        "upcoming": up_n,
        "today": today,
        "archive_events": archive_n,
        "gone": len(gone),
        "archived_total": archived_total,
        "pruned": pruned,
        "stored_total": store_total,
        "ics_events": ics_n,
        "rss_items": rss_n,
    }
    _print_summary(summary)
    return summary


def _print_summary(s: dict) -> None:
    live = ", ".join(f"{k}={v}" for k, v in s["per_source"].items())
    print("\n=== RUN SUMMARY ===")
    print(f"sources:           {s['sources_live']}/{s['sources_total']} live  ({live})")
    print(f"layers live:       {s['layers_live']}")
    if s["quarantined"]:
        q = ", ".join(f"{slug} [{why}]" for slug, why in s["quarantined"])
        print(f"quarantined:       {q}")
    print(f"raw events:        {s['raw_events']}")
    print(f"after dedupe:      {s['after_dedupe']}  (removed {s['deduped_removed']})")
    print(f"kept after filter: {s['kept_after_filter']}  "
          f"(dropped {s['dropped_location']} loc, {s['dropped_topic']} topic, "
          f"{s['dropped_admin']} admin)")
    print(f"validated:         pre-excluded={s['pre_excluded']} post-excluded={s['post_excluded']}")
    print(f"big-name events:   {s['big_name']}")
    print(f"new since last run:{s['new_events']}  (new big-name: {s['new_big_name']})")
    print(f"upcoming (>= {s['today']}): {s['upcoming']}")
    print(f"stored total:      {s['stored_total']}  (archive.ics={s['archive_events']}, "
          f"gone-from-sources={s['gone']})")
    print(f"partition:         active={s['kept_after_filter']} archived={s['archived_total']} "
          f"pruned={s['pruned']}")
    print(f"emitted:           events.ics={s['ics_events']}  feed.xml={s['rss_items']}  events.json")
