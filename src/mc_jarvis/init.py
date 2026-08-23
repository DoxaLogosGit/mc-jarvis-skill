"""Bootstrap: fetch every source, then build the index (spec §11).

First run is a shell command, not an agent request. The skill is what
teaches an agent that `mc-jarvis` exists, so the agent cannot be what
installs it.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import sys
from pathlib import Path

from . import (cardtext, deckrules, doctor, identity, index, manifest,
               outofdeck, paths, pdf, rules, rules_chunk, rulings,
               sources, timing)

# Below this many index entries, a rulebook is treated as having no
# alphabetical index and is chunked by page instead: searchable, but not
# addressable by entry (spec §9). The Rules Reference yields 217 and
# Learn to Play yields 0, so the threshold sits in open space.
INDEX_MIN_ENTRIES = 50


def rebuild_index(conn: sqlite3.Connection, data_root: Path) -> dict[str, int]:
    """The single build pipeline, shared by `init` and `update`.

    Order matters. Out-of-deck classification needs identities to exist,
    and the card-rules link table needs both card keywords and rules
    entries (spec §8, §10).
    """
    counts: dict[str, int] = {}

    report = index.load_cards(conn, data_root / "marvelsdb")
    counts["cards"] = report.cards
    counts["player_cards"] = report.player_cards
    counts["reprints"] = report.reprints
    counts["fts"] = index.build_fts(conn)
    counts["identities"] = identity.build(conn)

    config = outofdeck.load_config()
    counts["out_of_deck"] = outofdeck.classify(conn, config, strict=True)

    counts.update(cardtext.build(conn))
    counts.update(cardtext.build_limits(conn))

    deckrules.check(conn, config)
    counts["deckbuilding_overrides"] = len(deckrules.scan(conn))

    counts.update(_rebuild_rules(conn, data_root))
    counts["rules_links"] = rules.build_links(conn)

    counts["timing_triggers"] = timing.build(conn)
    counts.update(_rebuild_rulings(conn, data_root))
    broken = timing.verify_chart(conn) + timing.verify_citations(conn)
    if broken:
        # Not fatal: the card index is still correct and useful. But the
        # timing reference would now be quoting rules text that no longer
        # says what it claims, so say so rather than serving it silently.
        print("WARNING: the timing reference no longer matches the rules "
              "it is built from:", file=sys.stderr)
        for b in broken:
            print(f"  {b}", file=sys.stderr)

    conn.executemany(
        "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
        [("built_at", _dt.datetime.now(_dt.timezone.utc).isoformat()),
         ("card_count", str(counts["cards"])),
         ("rules_resolved", str(counts.get("rules_resolved", 0))),
         ("timing_broken", json.dumps(broken))])
    conn.commit()
    return counts


def _rebuild_rules(conn: sqlite3.Connection,
                   data_root: Path) -> dict[str, int]:
    """Chunk every cached rulebook and store it.

    Glyphs are mapped **after** chunking, never before. `apply_glyphs`
    swaps one private-use codepoint for a multi-word bracketed token, and
    run over whole pages that rewrite changes how an index line parses:
    measured against the real Rules Reference, 13 of 217 entries are then
    stored as `Icon ([amplify])` rather than `Amplify Icon ([amplify])`,
    and `parse_index` derives 0 glyph names instead of 13. The entry count
    is identical either way, so nothing fails -- the entries simply stop
    being findable by name.
    """
    txt_dir = data_root / "rules" / "txt"
    glyphs = rules_chunk.load_glyphs()
    entries: list[rules_chunk.Entry] = []
    unmapped: set[str] = set()
    resolved = 0

    rr_version: str | None = None
    for path in sorted(txt_dir.glob("*.txt")):
        pages = path.read_text(encoding="utf-8").split("\f")
        if "rules-reference" in path.stem:
            # Which Rules Reference this index holds. Everything version
            # -sensitive keys off it, and a rules tool that will not say
            # which rulebook it is answering from is not much use.
            rr_version = rules_chunk.declared_version(pages)
        idx = rules_chunk.parse_index(pages)
        if len(idx.entries) > INDEX_MIN_ENTRIES:
            doc = rules_chunk.chunk_entries(pages, idx, source_doc=path.stem)
            resolved += rules_chunk.extraction_report(pages, idx)["resolved"]
        else:
            doc = rules_chunk.chunk_pages(pages, source_doc=path.stem)
        for entry in doc:
            entry.body, missing = rules_chunk.apply_glyphs(entry.body, glyphs)
            unmapped |= missing
            entry.term, missing = rules_chunk.apply_glyphs(entry.term, glyphs)
            unmapped |= missing
        entries += doc

    # Named as codepoints, not counted. A number tells you something is
    # wrong; "U+F532" tells you what to look up and add.
    conn.execute(
        "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
        ("unmapped_glyphs",
         " ".join(sorted(f"U+{ord(c):04X}" for c in unmapped))))
    conn.commit()

    conn.execute(
        "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
        ("rr_version", rr_version or ""))
    conn.commit()

    return {"rules_entries": rules_chunk.store(conn, entries) if entries else 0,
            "rules_resolved": resolved,
            "rr_version": rr_version or "unknown",
            "unmapped_glyphs": len(unmapped)}


def _rebuild_rulings(conn, data_root: Path) -> dict:
    """Classify the cached rulings against the indexed Rules Reference.

    Additive and optional: with no cache there are simply no rulings. A
    cache that no longer parses is reported, because "the page changed"
    and "there are no rulings" must never look alike.
    """
    from . import manifest

    found = rulings.load(data_root)

    version = conn.execute(
        "SELECT value FROM build_meta WHERE key = 'rr_version'").fetchone()
    version = version["value"] if version else None

    manifest_path = data_root / "rules" / "manifest.json"
    docs = []
    if manifest_path.is_file():
        docs = [d.__dict__ for d in manifest.read(manifest_path).docs]

    published = rulings.published_on(data_root, rr_version=version,
                                     manifest_docs=docs)
    if published is None:
        print("WARNING: could not determine when the Rules Reference was "
              "published, so every ruling is treated as still in force. "
              "Over-reporting a ruling is survivable; dropping a live one "
              "is not.", file=sys.stderr)

    if not found.ok:
        # Keep whatever is already stored. A parse that fails today
        # against a cache that parsed yesterday is a broken parser, not an
        # empty corpus, and discarding the rows makes the two
        # indistinguishable. The statuses are still refreshed against the
        # rulebook now indexed.
        if found.status != "disabled":
            print(f"WARNING: {found.detail}", file=sys.stderr)
        split = rulings.reclassify(conn, published)
        return {"rulings": split["total"],
                "rulings_active": split["active"],
                "rulings_superseded": split["superseded"]}

    pages = (data_root / "rules" / "txt"
             / "marvel-champions-rules-reference.txt")
    changelog = []
    if pages.is_file():
        first = pages.read_text(encoding="utf-8").split("\f")[0]
        changelog = rulings.parse_changelog(first, version or "unknown")
    conn.execute("DELETE FROM rr_changelog")
    conn.executemany(
        "INSERT INTO rr_changelog (rr_version, page, description, term) "
        "VALUES (?, ?, ?, ?)",
        [(e["rr_version"], e["page"], e["description"], e["term"])
         for e in changelog])

    total = rulings.store(conn, found.rulings, published=published,
                          changelog=changelog,
                          source_name=manifest.MIRROR_NAME)
    split = rulings.counts(conn)
    return {"rulings": total, "rulings_active": split["active"],
            "rulings_superseded": split["superseded"]}


def extract_rules_text(data_root: Path, *, backend: str | None = None) -> int:
    """Cache each downloaded PDF as page-separated text.

    Both backends were verified to agree on the real Rules Reference --
    71 pages, 13 private-use codepoints, 217 index entries, 46 redirects
    from each -- so the default is left to `pdf.extract_pages`.
    """
    pdf_dir = data_root / "rules" / "pdf"
    txt_dir = data_root / "rules" / "txt"
    txt_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for path in sorted(pdf_dir.glob("*.pdf")):
        pages = pdf.extract_pages(path, backend=backend)
        (txt_dir / f"{path.stem}.txt").write_text(
            "\f".join(pages), encoding="utf-8")
        written += 1
    return written


def _get_manifest(args) -> manifest.ManifestResult | None:
    """Saved HTML and a real browser both beat the archive, so an explicit
    flag wins. With neither, archive.org needs no browser at all."""
    if getattr(args, "from_html", None):
        return manifest.fetch_from_html(Path(args.from_html))
    if getattr(args, "browser", False):
        try:
            return manifest.fetch_with_browser()
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return None
    try:
        return manifest.fetch_from_wayback()
    except Exception as exc:
        print(f"could not reach archive.org: {exc}", file=sys.stderr)
        return None


RR_SLUG = "marvel-champions-rules-reference"


def _current_rr(result) -> dict | None:
    """The current Rules Reference, when the manifest's is superseded.

    The latest Rules Reference is the authority: when FFG publishes a new
    one it replaces the old, and nothing about the old edition survives
    except rulings issued after it. The archive.org capture the manifest
    comes from lags FFG by months, so left alone `init` indexes a
    superseded rulebook and every answer is cited to it.

    Returns None when the manifest is already current, or when the check
    could not run - never a guess. `check_rr_currency` reports a broken
    oracle as `unknown` rather than as a clean bill of health.
    """
    verdict = manifest.check_rr_currency(result)
    if verdict is None:
        return None
    if verdict.get("status") != "behind" or not verdict.get("url"):
        print(f"  could not confirm the Rules Reference is current: "
              f"{verdict.get('detail', verdict.get('status'))}",
              file=sys.stderr)
        return None
    return verdict


def _verify_rr(path: Path, expected: str) -> None:
    """A mirrored rulebook is only safe because the document states its own
    version on page 1. Refuse anything that will not say so."""
    found = rules_chunk.verify_version(pdf.extract_pages(path), expected)
    if found is None:
        raise rules_chunk.VersionMismatch(
            f"{path.name} does not declare a version; refusing to index it "
            f"as {expected}")


def take_current_rr(root: Path, result) -> str | None:
    """Replace the indexed Rules Reference when a newer one is published.

    Downloads beside the existing file and only swaps it in once the
    document has proved its own version, so a failed or mislabelled
    download leaves the rulebook already on disk untouched.

    Returns the version taken, or None if nothing was replaced.
    """
    current = _current_rr(result)
    if not current:
        return None
    print(f"  Rules Reference {current['have']} is superseded; "
          f"{current['source_name']} lists {current['current']} "
          f"- taking the current one")
    target = root / "rules" / "pdf" / f"{RR_SLUG}.pdf"
    staged = target.with_suffix(".pdf.incoming")
    try:
        pdf.download(current["url"], staged)
        _verify_rr(staged, current["current"])
    except (pdf.PdfError, rules_chunk.VersionMismatch) as exc:
        print(f"  {exc}", file=sys.stderr)
        staged.unlink(missing_ok=True)
        return None
    staged.replace(target)
    return current["current"]


def run(args) -> int:
    checks = doctor.run_checks(network=False)
    hard = [c for c in checks if c.hard and not c.ok]
    if hard:
        print("mc-jarvis init cannot start:", file=sys.stderr)
        for check in hard:
            print(f"  {check.name}: {check.detail}", file=sys.stderr)
        return 1

    root = paths.ensure_data_dir()
    print(f"data directory: {root}")

    print("fetching card data...")
    fetched = sources.fetch_card_data(root / "marvelsdb")
    print(f"  {fetched.pack_files} pack files "
          f"({fetched.bytes_downloaded / 1e6:.1f} MB)")

    result = _get_manifest(args)
    if result is None or not result.docs:
        print("\nNo rules manifest. Card commands will work; rules commands "
              "will not.\nRe-run with --from-html once you have saved the "
              f"product page:\n  {manifest.PRODUCT_PAGE}")
        docs = []
    else:
        manifest.write(result, root / "rules" / "manifest.json")
        docs = result.docs
        print(f"  {len(docs)} rulebooks listed (source: {result.source})")
        warning = manifest.currency_warning(result)
        if warning:
            print(warning)

    for doc in docs:
        if doc.slug not in manifest.DEFAULT_SLUGS:
            continue
        target = root / "rules" / "pdf" / f"{doc.slug}.pdf"
        print(f"downloading {doc.title}...")
        try:
            pdf.download(doc.url, target)
        except pdf.PdfError as exc:
            print(f"  {exc}", file=sys.stderr)
            continue

    # The archived capture lags FFG by months, and the latest Rules
    # Reference is the authority - so the archived edition is only ever a
    # floor. Swapping happens after the download above so a failure here
    # leaves a working, if superseded, rulebook rather than none.
    if docs:
        init_took = take_current_rr(root, result)
        if init_took:
            print(f"  Rules Reference {init_took} in place")

    found = rulings.fetch(root)
    if found.ok:
        print(f"  {len(found.rulings)} designer rulings fetched")
    else:
        print(f"  no designer rulings: {found.detail}", file=sys.stderr)

    pages = extract_rules_text(root)
    if pages:
        print(f"extracted {pages} rulebook(s) to text")

    print("building index...")
    conn = index.connect(paths.db_path())
    counts = rebuild_index(conn, root)
    for key, value in counts.items():
        print(f"  {key}: {value}")
    if counts.get("unmapped_glyphs"):
        print("\nSome icon codepoints are unmapped; see `mc-jarvis status`.")

    print("\nNext:  mc-jarvis install-skill      (in your deck workspace)")
    return 0
