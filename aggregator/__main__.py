"""Entry point: python -m aggregator [--out DIR] [--db PATH] [--today YYYY-MM-DD]"""

from __future__ import annotations

import argparse

from .pipeline import run


def main() -> None:
    p = argparse.ArgumentParser(
        prog="aggregator",
        description="DC AI & frontier-tech event aggregator: fetch -> normalize -> "
                    "dedupe -> filter -> rank -> emit (ICS/RSS/JSON).",
    )
    p.add_argument("--out", default="out", help="output directory for feeds (default: out)")
    p.add_argument("--db", default="data/events.db", help="SQLite path (default: data/events.db)")
    p.add_argument("--today", default=None,
                   help="override 'today' (YYYY-MM-DD) for the upcoming/ranking window")
    p.add_argument("--no-enrich", action="store_true",
                   help="skip Layer-2 detail-page speaker enrichment (faster, fewer requests)")
    args = p.parse_args()
    run(out_dir=args.out, db_path=args.db, today=args.today, enrich=not args.no_enrich)


if __name__ == "__main__":
    main()
