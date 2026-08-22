"""Rebuild the local index from fetched data. Interim helper until
`mc-jarvis init` lands in Task 15."""
from mc_jarvis import (cardtext, deckrules, identity, index, outofdeck,
                       paths)

conn = index.connect(paths.db_path())
report = index.load_cards(conn, paths.data_dir() / "marvelsdb")
counts = {"cards": report.cards, "player": report.player_cards,
          "reprints": report.reprints, "fts": index.build_fts(conn),
          "identities": identity.build(conn)}
config = outofdeck.load_config()
counts["out_of_deck"] = outofdeck.classify(conn, config, strict=True)
counts.update(cardtext.build(conn))
counts.update(cardtext.build_limits(conn))
deckrules.check(conn, config)
counts["deckbuilding_overrides"] = len(deckrules.scan(conn))
for k, v in counts.items():
    print(f"  {k}: {v}")
