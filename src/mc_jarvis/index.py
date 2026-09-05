"""SQLite index build (spec §8, §10)."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import schema

# Bump whenever SCHEMA changes shape. The index is derived entirely from
# fetched data, so a mismatch is resolved by rebuilding rather than by
# migrating - there is nothing here that cannot be regenerated.
SCHEMA_VERSION = 23


class InvariantError(RuntimeError):
    """An upstream assumption this design relies on no longer holds."""


@dataclass
class BuildReport:
    cards: int = 0
    player_cards: int = 0
    packs: int = 0
    sets: int = 0
    reprints: int = 0
    warnings: list[str] = field(default_factory=list)


# "Player-legal" is not simply "not encounter". `campaign` cards (146)
# belong to a campaign's own pool rather than a constructed deck, and
# `encounter` is the villain side. Verified 2026-08-22; spec §16's
# "1,607 player-legal" excludes campaign, while a bare
# `faction_code != 'encounter'` counts 2,154.
PLAYER_FACTIONS = ("aggression", "justice", "leadership", "protection",
                   "basic", "hero", "pool")

# Two columns are renamed on the way in. Upstream calls the main
# scheme's target threat plainly `threat`, which in this schema would sit
# confusingly beside `base_threat`, `escalation_threat` and the villain's
# `scheme`; `target_threat` is what RR p.43 calls it.
UPSTREAM_NAME = {"target_threat": "threat",
                 "target_threat_fixed": "threat_fixed"}

COLUMNS = (
    "code name subname type_code faction_code pack_code set_code back_link "
    "double_sided is_unique permanent duplicate_of cost quantity "
    "resource_physical resource_mental resource_energy resource_wild "
    "attack thwart attack_cost thwart_cost defense recover health health_per_hero scheme "
    "stage hand_size text flavor traits "
    "boost base_threat escalation_threat scheme_acceleration scheme_amplify "
    "scheme_crisis scheme_hazard hidden base_threat_fixed "
    "escalation_threat_fixed boost_star attack_star scheme_star "
    "target_threat target_threat_fixed"
).split()


class StaleIndex(RuntimeError):
    """The index on disk was built against an older schema."""


def connect(db_path: Path, *, rebuild: bool = False) -> sqlite3.Connection:
    """Open the index.

    `rebuild=True` permits dropping an index built against an older
    schema, and ONLY `init` and `update` pass it. Every other command
    reads, and a read must never destroy what it is reading: dropping on
    open meant `card show 01001a` against a stale index silently emptied
    all 39 tables and then answered "no card named", which is a wrong
    answer rather than an error. `status` afterwards reported a fresh
    index holding zero cards.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if rebuild:
        _reset_if_stale(conn)
    else:
        _refuse_if_stale(conn)
    conn.executescript(schema.SCHEMA)
    return conn


def _refuse_if_stale(conn: sqlite3.Connection) -> None:
    """Stop before a read touches an index from an older schema.

    A brand-new file reports version 0 and holds no tables; that is not
    stale, it is empty, and the caller creates it below.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    has_tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'").fetchone()[0]
    if not has_tables:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return
    raise StaleIndex(
        f"this index was built against schema {version}, and this "
        f"mc-jarvis expects {SCHEMA_VERSION}. Run `mc-jarvis update` to "
        f"rebuild it. (Nothing has been changed.)")


def _reset_if_stale(conn: sqlite3.Connection) -> bool:
    """Drop a index built against an older schema.

    Without this, `CREATE TABLE IF NOT EXISTS` silently keeps the old
    table and the first query against a new column fails with a bare
    "no such column" - a confusing error for what is really a stale
    derived artifact.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return False
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        " AND name NOT LIKE 'sqlite_%'")]
    # Drops go in no particular order, so a foreign key between two of
    # these tables would abort the reset half-done - which is the one
    # state this function exists to prevent. Suspend the checks for the
    # teardown; every table here is rebuilt from source immediately after.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for name in tables:
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return bool(tables)


def resolve_deck_limit(card: dict) -> int | None:
    """`deck_limit: null` is not unlimited - it falls back to `quantity`
    (spec §10). 120 player cards depend on this."""
    limit = card.get("deck_limit")
    return card.get("quantity") if limit is None else limit


def assert_boost_invariant(rows: list[dict]) -> None:
    """`boost` is absent or 1-4 (§4.3, re-measured in §14.3).

    Two assertions, not one. An explicit 0 means upstream started using a
    different encoding for "no boost icons", so the corpus now mixes two
    and `absent means zero` stops being safe. A value outside 1-4 means
    the printed scale changed. Either way the quantity-weighted mean
    quietly stops meaning what it says, which is the headline statistic
    of the whole assess feature.
    """
    bad = [r for r in rows
           if r.get("boost") is not None and r["boost"] not in (1, 2, 3, 4)]
    if bad:
        raise InvariantError(
            f"{len(bad)} cards have a boost value outside 1-4: "
            f"{[(r['code'], r.get('boost')) for r in bad[:5]]}. "
            f"`absent means zero boost icons` is no longer a safe reading.")


def _assert_copy_invariant(rows: list[dict]) -> None:
    """Check what is actually true about copies (spec §10, as corrected).

    Spec §10 claims `deck_limit` never exceeds `quantity` per printing and
    concludes that owning any pack containing a card gives you enough
    copies to play it to its limit. Measured 2026-08-22, after reprint
    stubs are resolved, that per-printing claim is **false**: 50 reprint
    printings ship fewer copies than the limit - the Ant-Man pack contains
    2 First Aid against a limit of 3.

    What does hold, with zero violations, is the grouped form: every card
    has some printing with at least `deck_limit` copies. So the invariant
    is asserted in two parts:

      - per printing, on original printings only;
      - grouped across all printings of a card, on everything.

    The consequence for the collection work in the next plan: ownership is
    binary per *card*, but only because the printing carrying a full set
    of copies is generally one a player already owns. It is not a licence
    to treat every printing as sufficient.
    """
    for c in rows:
        if c.get("is_reprint"):
            continue
        raw, qty = c.get("deck_limit"), c.get("quantity")
        if raw is not None and qty is not None and raw > qty:
            raise InvariantError(
                f"deck_limit {raw} exceeds quantity {qty} for {c['code']} "
                f"({c.get('name')}) in its original printing (spec §10)")

    grouped = defaultdict(lambda: {"limit": 0, "qty": 0})
    for c in rows:
        key = c.get("canonical_code") or c["code"]
        agg = grouped[key]
        agg["limit"] = max(agg["limit"], resolve_deck_limit(c) or 0)
        agg["qty"] = max(agg["qty"], c.get("quantity") or 0)
    for key, agg in grouped.items():
        if agg["limit"] > agg["qty"]:
            raise InvariantError(
                f"no printing of {key} has {agg['limit']} copies "
                f"(most is {agg['qty']}); collection logic assumes every "
                f"card is obtainable at its deck limit (spec §10)")


# Display fields a reprint stub inherits from the card it duplicates.
INHERITED = (
    "name subname type_code faction_code set_code back_link double_sided "
    "is_unique permanent cost deck_limit resource_physical resource_mental "
    "resource_energy resource_wild attack thwart defense recover health "
    "hand_size text flavor traits"
).split()


def resolve_reprints(rows: list[dict]) -> int:
    """Fill in reprint stubs from the card they duplicate.

    351 rows in the real corpus carry `duplicate_of` and nothing else -
    no name, no text, just a code, pack, and quantity. Verified
    2026-08-22: every one resolves in a single hop, none chain, and no
    card carries `duplicate_of` alongside a name of its own.

    Spec §8 states these are all encounter cards and that no player card
    uses the field. That is wrong: 341 of 351 resolve to player cards,
    211 of them to `basic`. They are hero-pack reprints, and they are how
    player-side reprints are marked. Leaving them unresolved gives 351
    nameless rows and breaks collection lookups - owning the Ant-Man pack
    would not tell you that you own First Aid.

    Each stub keeps its own code, pack, quantity, and position, because
    those are properties of the printing rather than of the card.
    """
    by_code = {c["code"]: c for c in rows}
    resolved = 0
    for card in rows:
        target_code = card.get("duplicate_of")
        card["canonical_code"] = target_code or card["code"]
        card["is_reprint"] = 1 if target_code else 0
        if not target_code:
            continue
        target = by_code.get(target_code)
        if target is None:
            raise InvariantError(
                f"{card['code']} duplicates {target_code}, which is not in "
                f"the corpus")
        if target.get("duplicate_of"):
            raise InvariantError(
                f"{card['code']} duplicates {target_code}, which is itself "
                f"a reprint; chained stubs are not handled")
        for field_name in INHERITED:
            if card.get(field_name) in (None, "", []):
                card[field_name] = target.get(field_name)
        resolved += 1
    return resolved


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_cards(conn: sqlite3.Connection, marvelsdb_dir: Path) -> BuildReport:
    marvelsdb_dir = Path(marvelsdb_dir)
    report = BuildReport()

    pack_dir = marvelsdb_dir / "pack"
    if not pack_dir.is_dir():
        raise InvariantError(f"no pack/ directory under {marvelsdb_dir}")

    rows: list[dict] = []
    for path in sorted(pack_dir.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, list):
            report.warnings.append(f"{path.name}: not a list, skipped")
            continue
        rows.extend(payload)

    if not rows:
        raise InvariantError(f"no cards found under {pack_dir}")

    # Stubs must be filled in before the invariant check and before
    # insert: they have no name until resolved.
    report.reprints = resolve_reprints(rows)
    _assert_copy_invariant(rows)
    assert_boost_invariant(rows)

    conn.execute("DELETE FROM cards")
    conn.executemany(
        f"INSERT OR REPLACE INTO cards ({', '.join(COLUMNS)}, "
        f"canonical_code, is_reprint, deck_limit, deck_limit_raw, raw) "
        f"VALUES ({', '.join('?' * len(COLUMNS))}, ?, ?, ?, ?, ?)",
        [
            tuple(c.get(UPSTREAM_NAME.get(col, col)) for col in COLUMNS)
            + (c["canonical_code"], c["is_reprint"],
               resolve_deck_limit(c), c.get("deck_limit"),
               json.dumps(c, ensure_ascii=False))
            for c in rows
        ],
    )
    report.cards = len(rows)
    report.player_cards = sum(
        1 for c in rows if c.get("faction_code") in PLAYER_FACTIONS)

    for name, table, cols in (
        ("packs.json", "packs", ("code", "name")),
        ("sets.json", "sets", ("code", "name", "card_set_type_code")),
    ):
        path = marvelsdb_dir / name
        if not path.exists():
            report.warnings.append(f"{name} missing")
            continue
        payload = _read_json(path)
        conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            [tuple(item.get(c) for c in cols) for item in payload])
        setattr(report, table, len(payload))

    conn.commit()
    return report


def build_fts(conn: sqlite3.Connection) -> int:
    """Repopulate the external-content FTS table.

    Populated explicitly rather than by triggers: the index is rebuilt
    wholesale rather than edited, so triggers would only add write cost.
    """
    conn.execute("INSERT INTO cards_fts(cards_fts) VALUES('delete-all')")
    conn.execute(
        "INSERT INTO cards_fts(rowid, name, subname, text, traits, flavor) "
        "SELECT rowid, name, subname, text, traits, flavor FROM cards")
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM cards_fts").fetchone()[0]
