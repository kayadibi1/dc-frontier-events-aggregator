from aggregator.models import Event
from aggregator.storage import Store, open_store


def test_open_store_defaults_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = open_store(str(tmp_path / "e.db"))
    assert s.backend == "sqlite"
    s.close()


def test_open_store_falls_back_when_postgres_unreachable(tmp_path, monkeypatch):
    # Connection-refused dsn -> psycopg2 connect fails fast -> SQLite fallback,
    # and open_store must NOT raise (never block the run on infra).
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1:1/db")
    s = open_store(str(tmp_path / "e.db"))
    assert s.backend == "sqlite"
    s.close()


def test_sqlite_roundtrip_and_idempotent_upsert(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    evs = [Event(id="a", title="X", start="2026-06-01", source="cset",
                 topics=["ai"], is_big_name=True)]
    s.upsert_many(evs)
    s.upsert_many(evs)                 # re-upsert is idempotent
    assert s.count() == 1
    back = s.all_events()
    assert back[0].id == "a"
    assert back[0].topics == ["ai"]
    assert back[0].is_big_name is True
    assert s.existing_ids() == {"a"}
    s.close()


def test_first_seen_preserved_last_seen_refreshed(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    ev = [Event(id="a", title="X", start="2026-06-01", source="cset")]
    s.upsert_many(ev)
    f1, l1 = s.conn.execute("SELECT first_seen,last_seen FROM events WHERE id='a'").fetchone()
    s.upsert_many(ev)  # re-upsert (idempotent in count, but last_seen refreshes)
    f2, l2 = s.conn.execute("SELECT first_seen,last_seen FROM events WHERE id='a'").fetchone()
    assert f1 and l1
    assert f2 == f1          # first_seen preserved across upserts
    assert l2 >= l1          # last_seen refreshed
    assert s.count() == 1
    s.close()


def test_upsert_marks_status_active(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    s.upsert_many([Event(id="a", title="X", start="2026-06-01", source="cset")])
    status = s.conn.execute("SELECT status FROM events WHERE id='a'").fetchone()[0]
    assert status == "active"
    s.close()


def test_mark_archived_partitions(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    s.upsert_many([
        Event(id="a", title="A", start="2026-06-01", source="cset"),
        Event(id="b", title="B", start="2026-06-02", source="cset"),
        Event(id="c", title="C", start="2026-06-03", source="cset"),
    ])
    archived = s.mark_archived({"a", "b"})   # 'c' no longer seen -> archived
    assert archived == 1
    assert {e.id for e in s.active_events()} == {"a", "b"}
    assert {e.id for e in s.archived_events()} == {"c"}
    s.close()


def test_new_since_returns_recently_first_seen(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    # Two events inserted now; first_seen is stamped at insert time.
    s.upsert_many([
        Event(id="a", title="A", start="2026-06-01", source="cset"),
        Event(id="b", title="B", start="2026-06-02", source="cset"),
    ])
    # Backdate one event's first_seen to before the window.
    s.conn.execute("UPDATE events SET first_seen='2026-05-01T00:00:00+00:00' WHERE id='a'")
    s.conn.commit()
    new = s.new_since("2026-05-24")
    ids = {e.id for e in new}
    assert "b" in ids          # first_seen is today -> in the last-7-days window
    assert "a" not in ids      # backdated -> excluded
    s.close()


def test_new_since_excludes_archived(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    s.upsert_many([Event(id="a", title="A", start="2026-06-01", source="cset")])
    s.mark_archived(set())     # archive everything (none active this run)
    assert s.new_since("2026-05-01") == []   # archived rows never count as "new"
    s.close()


def test_prune_deletes_old_archived_only(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    s.upsert_many([
        Event(id="old", title="Old", start="2020-01-01", source="cset"),
        Event(id="new", title="New", start="2026-06-01", source="cset"),
    ])
    s.mark_archived(set())            # archive both
    deleted = s.prune("2021-01-01")   # only 'old' (start < cutoff) removed
    assert deleted == 1
    assert s.existing_ids() == {"new"}
    s.close()
