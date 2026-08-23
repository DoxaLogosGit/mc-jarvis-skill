"""Refresh sources and report staleness (spec §11)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import index, init, manifest, paths, sources
from .cli import emit

STALE_DAYS = 14


def _age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400


def run(args) -> int:
    root = paths.ensure_data_dir()

    print("refreshing card data...")
    fetched = sources.fetch_card_data(root / "marvelsdb")
    print(f"  {fetched.pack_files} pack files")

    known = manifest.read(root / "rules" / "manifest.json")
    if known.docs:
        # `update` deliberately does not re-read FFG. A wayback-sourced
        # manifest re-reads the same archived capture, so re-fetching it
        # would imply a currency it cannot deliver (see
        # manifest.currency_warning).
        print(f"  {len(known.docs)} rulebooks known (source: {known.source})")
        warning = manifest.currency_warning(known)
        if warning:
            print(warning)

        # A new Rules Reference supersedes the old one, and `update` is
        # where that is meant to be noticed. The mirror check can see a
        # release the archived capture cannot, so this is the one currency
        # question `update` can actually answer.
        if init.take_current_rr(root, known):
            print("  Rules Reference replaced with the current edition")

    # Rulings change between Rules Reference releases - that is the whole
    # point of them - so `update` re-fetches even though it will not
    # re-read the archived rulebook list.
    from . import rulings
    found = rulings.fetch(root)
    if found.ok:
        print(f"  {len(found.rulings)} designer rulings fetched")
    else:
        print(f"  no designer rulings: {found.detail}")

    extracted = init.extract_rules_text(root)
    if extracted:
        print(f"  {extracted} rulebook(s) re-extracted to text")

    print("building index...")
    conn = index.connect(paths.db_path())
    counts = init.rebuild_index(conn, root)
    if getattr(args, "json", False):
        emit(counts, as_json=True)
    else:
        for key, value in counts.items():
            print(f"  {key}: {value}")
    return 0


def status(args) -> int:
    db = paths.db_path()
    if not db.exists():
        print("no index — run `mc-jarvis init`")
        return 1

    conn = index.connect(db)
    age = _age_days(db)
    meta = {r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM build_meta")}

    def count(table: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    payload = {
        "data_dir": str(paths.data_dir()),
        "built_at": meta.get("built_at"),
        "age_days": round(age, 1),
        "stale": age > STALE_DAYS,
        "cards": count("cards"),
        "identities": count("identities"),
        # A complete index holds 287 rows across two rulebooks: 217 Rules
        # Reference index entries (216 resolve) plus 46 redirects, and 24
        # page-chunks of Learn to Play. Reporting only the total reads as
        # "287 terms you can look up", which is not true. `rules_resolved`
        # is the build's own count, not a second figure computed here.
        "rules_entries": count("rules_entries"),
        "rules_resolved": int(meta.get("rules_resolved") or 0),
        "rr_version": meta.get("rr_version") or "unknown",
        # Naming the documents, not just counting rows: a data directory
        # that never completed an `init` holds only the Rules Reference,
        # and no total reveals which rulebook is absent.
        "rules_docs": {r["source_doc"]: r["n"] for r in conn.execute(
            "SELECT source_doc, COUNT(*) n FROM rules_entries "
            "GROUP BY source_doc ORDER BY source_doc")},
        "unmapped_glyphs": meta.get("unmapped_glyphs", ""),
        "timing_triggers": count("timing_triggers"),
        # 0 active right after a Rules Reference release is the correct
        # steady state, not a problem: the new edition absorbed them.
        "rulings": count("rulings"),
        "rulings_active": conn.execute(
            "SELECT COUNT(*) FROM rulings WHERE status = 'active'"
        ).fetchone()[0],
        "timing_broken": json.loads(meta.get("timing_broken") or "[]"),
    }
    if getattr(args, "json", False):
        emit(payload, as_json=True)
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
        if payload["stale"]:
            print(f"\nIndex is {age:.0f} days old — run `mc-jarvis update`")
        if payload["unmapped_glyphs"]:
            print(f"\nUnmapped icon codepoints: "
                  f"{payload['unmapped_glyphs']} — add them to glyphs.yaml")
        missing = [d for d in ("marvel-champions-rules-reference",
                               "learn-to-play")
                   if d not in payload["rules_docs"]]
        if missing:
            print(f"\nNo rules indexed from: {', '.join(missing)}\n"
                  f"`update` cannot fetch a rulebook — run `mc-jarvis init`")
        if payload["timing_broken"]:
            print("\nThe timing reference no longer matches the rules it "
                  "is built from:")
            for b in payload["timing_broken"]:
                print(f"  {b}")
    return 0
