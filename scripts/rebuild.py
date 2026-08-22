"""Rebuild the local index from fetched data.

Interim helper until `mc-jarvis init` lands in Task 15.
"""
from mc_jarvis import (cardtext, deckrules, identity, index, outofdeck,
                       paths, pdf, rules, rules_chunk)

conn = index.connect(paths.db_path())
root = paths.data_dir()

report = index.load_cards(conn, root / "marvelsdb")
counts = {"cards": report.cards, "player": report.player_cards,
          "reprints": report.reprints, "fts": index.build_fts(conn),
          "identities": identity.build(conn)}

config = outofdeck.load_config()
counts["out_of_deck"] = outofdeck.classify(conn, config, strict=True)
counts.update(cardtext.build(conn))
counts.update(cardtext.build_limits(conn))
deckrules.check(conn, config)
counts["deckbuilding_overrides"] = len(deckrules.scan(conn))

glyphs = rules_chunk.load_glyphs()
entries, unmapped = [], set()
for path in sorted((root / "rules" / "pdf").glob("*.pdf")):
    # Parse and chunk on RAW pages: the index derives glyph names from
    # its own text ("Amplify Icon (<glyph>)"), and mapping first destroys
    # both that and the entry terms.
    pages = pdf.extract_pages(path, backend="pypdf")
    idx = rules_chunk.parse_index(pages)
    if len(idx.entries) > 50:
        doc = rules_chunk.chunk_entries(pages, idx, source_doc=path.stem)
        counts["rules_resolved"] = rules_chunk.extraction_report(
            pages, idx)["resolved"]
    else:
        doc = rules_chunk.chunk_pages(pages, source_doc=path.stem)
    for entry in doc:
        entry.body, missing = rules_chunk.apply_glyphs(entry.body, glyphs)
        unmapped |= missing
        entry.term, missing = rules_chunk.apply_glyphs(entry.term, glyphs)
        unmapped |= missing
    entries += doc
if entries:
    counts["rules_entries"] = rules_chunk.store(conn, entries)
counts["rules_links"] = rules.build_links(conn)
counts["unmapped_glyphs"] = len(unmapped)

for key, value in counts.items():
    print(f"  {key}: {value}")
