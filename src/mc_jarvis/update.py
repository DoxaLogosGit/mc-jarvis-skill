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
        "rules_entries": count("rules_entries"),
        "unmapped_glyphs": meta.get("unmapped_glyphs", ""),
        "timing_triggers": count("timing_triggers"),
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
        if payload["timing_broken"]:
            print("\nThe timing reference no longer matches the rules it "
                  "is built from:")
            for b in payload["timing_broken"]:
                print(f"  {b}")
    return 0
