# dc-frontier-events-aggregator

A multi-source event aggregator that pulls **AI, semiconductor, and frontier-tech events**
in the Washington, DC metro into a single, deduplicated, relevance-ranked feed.

There is no single calendar for AI and tech-policy events in DC; they are scattered across
think-tank sites, university calendars, community pages, and the Congress website. This engine
ingests all of them, verifies titles and dates against the original source pages, deduplicates
cross-posted events, ranks what is worth attending, and emits standard calendar / RSS / JSON feeds.

Live calendar built from this engine: **https://events.emersus.ai**

## Sources (three layers)

| Layer | What | Examples |
|------:|------|----------|
| **1 — community** | native iCal / API community calendars | Luma (DC Data & AI, DC Tech, AI Collective DC, city-wide discover), Meetup |
| **2 — policy / big-name** | think tanks (HTML / JSON scrape) | CSIS, Brookings, CNAS, CSET, Atlantic Council, ITIF, CDT, NIST, NASEM, U.S. Congress hearings |
| **3 — university** | campus event calendars | Georgetown Law, UMD CS |

Empty or failed sources are **quarantined and logged, never faked** — a 404 or an empty feed is
reported, not silently dropped. Per-source health and regressions are tracked across runs.

## Pipeline

```
fetch → normalize → enrich → validate → dedupe → filter → geocode → rank → store → emit
```

- **fetch** — `aggregator/fetchers/` adapters (httpx / curl_cffi browser-TLS impersonation /
  headless Chromium for JS-rendered pages). Each returns already-normalized `Event`s.
- **normalize** — one schema (`aggregator/models.Event`): id, title, start/end/tz, venue/address,
  lat/lng, organizer, speakers, source, topics, is_big_name.
- **enrich / validate** — detail-page enrichment (speakers, descriptions) plus a two-phase
  validation gate: date/tz/virtual sanity before the filter, geo-vs-address contradiction checks
  after geocoding.
- **dedupe** — exact-UID + fuzzy title-within-day + same-instant cross-platform merge (optional
  cross-language semantic pass).
- **filter** — keep iff `(DC-metro OR virtual-from-a-DC-curated-source) AND (on-topic OR big-name)`.
  GEO is authoritative for in-person events.
- **rank** — `score = topic strength + big-name + upcoming + DC proximity`.
- **store** — idempotent SQLite upsert; the store is the durable archive.
- **emit** — ICS, RSS, and JSON feeds (see Outputs).

## Outputs (written to `out/`)

| File | What |
|------|------|
| `events.ics` / `feed.xml` | full deduped + filtered set (iCalendar / RSS) |
| `events-upcoming.ics` / `feed-upcoming.xml` | events with start ≥ today |
| `feed-top.xml` | top-25 upcoming, relevance-ranked |
| `events-big-names.ics` / `feed-big-names.xml` | big-name (marquee lab/org) subset |
| `events-archive.ics` | full durable archive |
| `events.json` | machine-readable export (incl. `layer`, `score`) |
| `health.json` | per-source fetch health |

## Install & run

```bash
pip install -r requirements.txt
python -m aggregator                      # writes feeds to ./out, db at ./data/events.db
python -m aggregator --today 2026-06-01   # override the upcoming/ranking window
python -m aggregator --no-enrich          # skip detail-page enrichment (faster, fewer requests)
```

Requires Python 3.11+. Postgres is optional (`DATABASE_URL`); it falls back to SQLite so a run is
never blocked on infra.

## Tests

```bash
python -m pytest -q     # offline, deterministic (parsers / dedupe / filter / rank / emit)
```

## Configuration

Sources, the topic keyword set, the big-name watchlist, and the DC bounding box all live in
[`aggregator/config.py`](aggregator/config.py). Add a Luma calendar or any iCal feed with one line;
add a think-tank scraper as a new `fetchers/<name>.py` adapter registered in `fetchers/__init__.py`.

## License

MIT — see [LICENSE](LICENSE).
