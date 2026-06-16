"""Persistence with idempotent upsert.

GOAL.md: Postgres if reachable via DATABASE_URL, otherwise local SQLite so the
loop is NEVER blocked on infra. `open_store` selects PostgresStore when
DATABASE_URL is set and a connection succeeds, else falls back to SQLite (logged,
never raises). Both backends share COLUMNS + Event.to_row/from_row, so an event
round-trips identically through either.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from .models import Event

COLUMNS = [
    "id", "title", "description", "start", "end", "tz", "venue_name", "address",
    "lat", "lng", "organizer", "speakers", "source", "source_url", "topics",
    "is_big_name", "raw", "dedupe_key", "updated_at", "first_seen", "last_seen",
    "status",
]
# Columns NOT overwritten on a conflicting upsert (preserve original insert).
_PRESERVE = {"id", "first_seen"}

_DDL = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, title TEXT, description TEXT,
  start TEXT, "end" TEXT, tz TEXT,
  venue_name TEXT, address TEXT, lat REAL, lng REAL,
  organizer TEXT, speakers TEXT, source TEXT, source_url TEXT,
  topics TEXT, is_big_name INTEGER, raw TEXT, dedupe_key TEXT, updated_at TEXT,
  first_seen TEXT, last_seen TEXT, status TEXT
);
"""


def _rows(events: list[Event], now: str) -> list[tuple]:
    out = []
    for ev in events:
        r = ev.to_row()
        r["dedupe_key"] = ev.id
        r["updated_at"] = now
        r["first_seen"] = now   # kept only on INSERT (excluded from UPDATE set)
        r["last_seen"] = now
        r["status"] = "active"  # this run saw it; mark_archived demotes the rest
        out.append(tuple(r[c] for c in COLUMNS))
    return out


class Store:
    backend = "sqlite"

    def __init__(self, path: str = "data/events.db"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_DDL)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        # Add first_seen/last_seen/status to pre-existing databases.
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(events)")}
        for col in ("first_seen", "last_seen", "status"):
            if col not in have:
                self.conn.execute(f'ALTER TABLE events ADD COLUMN {col} TEXT')

    def upsert_many(self, events: list[Event]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        rows = _rows(events, now)
        cols = ",".join(f'"{c}"' for c in COLUMNS)
        placeholders = ",".join(["?"] * len(COLUMNS))
        updates = ",".join(f'"{c}"=excluded."{c}"' for c in COLUMNS if c not in _PRESERVE)
        self.conn.executemany(
            f"INSERT INTO events ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}", rows
        )
        self.conn.commit()
        return len(rows)

    def all_events(self) -> list[Event]:
        cur = self.conn.execute("SELECT * FROM events ORDER BY start")
        return [Event.from_row(r) for r in cur.fetchall()]

    def existing_ids(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT id FROM events")}

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def mark_archived(self, active_ids) -> int:
        """Demote every row to 'archived', then re-mark this run's ids 'active'.
        Returns the number of archived (no-longer-seen) rows."""
        self.conn.execute("UPDATE events SET status='archived' WHERE status='active'")
        self.conn.executemany("UPDATE events SET status='active' WHERE id=?",
                              [(i,) for i in active_ids])
        self.conn.commit()
        return self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE status='archived'").fetchone()[0]

    def active_events(self) -> list[Event]:
        cur = self.conn.execute("SELECT * FROM events WHERE status='active' ORDER BY start")
        return [Event.from_row(r) for r in cur.fetchall()]

    def new_since(self, since_iso: str) -> list[Event]:
        """Active events first seen on/after since_iso (a date or ISO timestamp) --
        i.e. genuinely new listings, for the 'new this week' email section. ISO
        date/timestamp strings compare correctly lexicographically, so a date bound
        like '2026-05-24' matches any first_seen on that day or later."""
        cur = self.conn.execute(
            "SELECT * FROM events WHERE status='active' AND first_seen >= ? "
            "ORDER BY start", (since_iso,))
        return [Event.from_row(r) for r in cur.fetchall()]

    def archived_events(self) -> list[Event]:
        cur = self.conn.execute("SELECT * FROM events WHERE status='archived' ORDER BY start")
        return [Event.from_row(r) for r in cur.fetchall()]

    def prune(self, before_iso: str) -> int:
        """Delete archived rows whose start date is older than before_iso."""
        cur = self.conn.execute(
            "DELETE FROM events WHERE status='archived' AND start < ?", (before_iso,))
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self.conn.close()


_PG_DDL = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, title TEXT, description TEXT,
  start TEXT, "end" TEXT, tz TEXT,
  venue_name TEXT, address TEXT, lat DOUBLE PRECISION, lng DOUBLE PRECISION,
  organizer TEXT, speakers TEXT, source TEXT, source_url TEXT,
  topics TEXT, is_big_name INTEGER, raw TEXT, dedupe_key TEXT, updated_at TEXT,
  first_seen TEXT, last_seen TEXT, status TEXT
);
ALTER TABLE events ADD COLUMN IF NOT EXISTS first_seen TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS last_seen TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS status TEXT;
"""


class PostgresStore:
    """Postgres backend (psycopg2). Same schema/semantics as Store; uses
    INSERT ... ON CONFLICT (id) DO UPDATE for the idempotent upsert."""

    backend = "postgres"

    def __init__(self, dsn: str, connect_timeout: int = 3):
        import psycopg2
        import psycopg2.extras

        self._extras = psycopg2.extras
        self.conn = psycopg2.connect(dsn, connect_timeout=connect_timeout)
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            cur.execute(_PG_DDL)

    def upsert_many(self, events: list[Event]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        rows = _rows(events, now)
        cols = ",".join(f'"{c}"' for c in COLUMNS)
        placeholders = ",".join(["%s"] * len(COLUMNS))
        updates = ",".join(f'"{c}"=EXCLUDED."{c}"' for c in COLUMNS if c not in _PRESERVE)
        sql = (f"INSERT INTO events ({cols}) VALUES ({placeholders}) "
               f"ON CONFLICT (id) DO UPDATE SET {updates}")
        with self.conn.cursor() as cur:
            self._extras.execute_batch(cur, sql, rows)
        return len(rows)

    def all_events(self) -> list[Event]:
        with self.conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM events ORDER BY start')
            return [Event.from_row(dict(r)) for r in cur.fetchall()]

    def existing_ids(self) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM events")
            return {r[0] for r in cur.fetchall()}

    def count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM events")
            return cur.fetchone()[0]

    def mark_archived(self, active_ids) -> int:
        with self.conn.cursor() as cur:
            cur.execute("UPDATE events SET status='archived' WHERE status='active'")
            self._extras.execute_batch(
                cur, "UPDATE events SET status='active' WHERE id=%s",
                [(i,) for i in active_ids])
            cur.execute("SELECT COUNT(*) FROM events WHERE status='archived'")
            return cur.fetchone()[0]

    def active_events(self) -> list[Event]:
        with self.conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM events WHERE status='active' ORDER BY start")
            return [Event.from_row(dict(r)) for r in cur.fetchall()]

    def new_since(self, since_iso: str) -> list[Event]:
        """Active events first seen on/after since_iso (see Store.new_since)."""
        with self.conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM events WHERE status='active' AND first_seen >= %s "
                        "ORDER BY start", (since_iso,))
            return [Event.from_row(dict(r)) for r in cur.fetchall()]

    def archived_events(self) -> list[Event]:
        with self.conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM events WHERE status='archived' ORDER BY start")
            return [Event.from_row(dict(r)) for r in cur.fetchall()]

    def prune(self, before_iso: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE status='archived' AND start < %s",
                        (before_iso,))
            return cur.rowcount

    def close(self) -> None:
        self.conn.close()


def open_store(path: str = "data/events.db"):
    """PostgresStore if DATABASE_URL is set and connectable; else SQLite (logged)."""
    url = os.environ.get("DATABASE_URL")
    if url:
        try:
            store = PostgresStore(url)
            print("[storage] backend=postgres")
            return store
        except Exception as e:  # driver missing, connect refused, etc. -> never block
            print(f"[storage] Postgres unavailable ({e!r}); falling back to SQLite.")
    store = Store(path)
    print(f"[storage] backend=sqlite path={store.path}")
    return store
