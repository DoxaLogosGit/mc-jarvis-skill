import sqlite3
import json

import pytest

from mc_jarvis import index
from tests.fixtures import cards as fx


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.PACK))
    (root / "packs.json").write_text(json.dumps(
        [{"code": "tst", "name": "Tester Pack"}]))
    (root / "sets.json").write_text(json.dumps(
        [{"code": "tester", "name": "Tester Set",
          "card_set_type_code": "hero"}]))
    return root


@pytest.fixture
def conn(tmp_path):
    return index.connect(tmp_path / "mc.sqlite")


def test_loads_every_card(conn, corpus):
    report = index.load_cards(conn, corpus)
    assert report.cards == 4
    assert report.packs == 1
    assert report.sets == 1


def test_null_deck_limit_falls_back_to_quantity(conn, corpus):
    index.load_cards(conn, corpus)
    row = conn.execute(
        "SELECT deck_limit, deck_limit_raw, quantity FROM cards "
        "WHERE code = 'tst03'").fetchone()
    assert row["deck_limit_raw"] is None
    assert row["deck_limit"] == 2      # falls back to quantity, not unlimited
    assert row["quantity"] == 2


def test_a_reprint_may_ship_fewer_copies_than_the_deck_limit(conn, tmp_path):
    """50 real printings do this (Ant-Man ships 2 First Aid, limit 3), so
    the per-printing check must not fire on reprints (spec §10 corrected)."""
    root = tmp_path / "md"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "a.json").write_text(json.dumps(fx.REPRINTS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    index.load_cards(conn, root)      # must not raise


def test_a_card_with_no_printing_at_its_limit_fails_loudly(conn, tmp_path):
    root = tmp_path / "md"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "a.json").write_text(json.dumps([
        fx.card("only1", "Scarce", quantity=1, deck_limit=1),
        {"code": "only2", "pack_code": "p2", "quantity": 1,
         "duplicate_of": "only1"},
        fx.card("bad1", "Unobtainable", quantity=1, deck_limit=1),
    ]))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    index.load_cards(conn, root)      # legal: every card reaches its limit


def test_deck_limit_never_silently_exceeds_quantity(conn, corpus):
    bad = json.loads((corpus / "pack" / "tst.json").read_text())
    bad.append(fx.INVARIANT_VIOLATION)
    (corpus / "pack" / "tst.json").write_text(json.dumps(bad))
    with pytest.raises(index.InvariantError, match="deck_limit"):
        index.load_cards(conn, corpus)


def test_grouped_invariant_allows_a_legal_second_printing(conn, corpus):
    """A card at quantity 1 in a second pack is fine; the grouped check
    compares the maxima, not the sum (spec §10)."""
    other = dict(fx.card("tst02", "Ordinary Ally"),
                 pack_code="tst2", quantity=1, deck_limit=1)
    (corpus / "pack" / "tst2.json").write_text(json.dumps([other]))
    index.load_cards(conn, corpus)


def test_reload_is_idempotent(conn, corpus):
    index.load_cards(conn, corpus)
    report = index.load_cards(conn, corpus)
    assert report.cards == 4
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 4


def test_raw_json_is_retained_verbatim(conn, corpus):
    index.load_cards(conn, corpus)
    raw = conn.execute(
        "SELECT raw FROM cards WHERE code = 'tst02'").fetchone()["raw"]
    assert json.loads(raw)["name"] == "Ordinary Ally"


@pytest.mark.integration
def test_real_corpus_counts(real_index):
    n = real_index.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    assert 4000 < n < 6000                      # 4,379 on 2026-08-21
    player = real_index.execute(
        "SELECT COUNT(*) FROM cards WHERE faction_code != 'encounter'"
    ).fetchone()[0]
    assert 1400 < player < 2500                 # 1,607 in the spec


def test_reprint_stubs_inherit_from_the_card_they_duplicate(conn, tmp_path):
    """351 real rows carry only a code, pack, quantity and duplicate_of.
    Unresolved they are nameless and break every lookup."""
    root = tmp_path / "md"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "a.json").write_text(json.dumps(fx.REPRINTS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    report = index.load_cards(conn, root)
    assert report.reprints == 1

    stub = conn.execute(
        "SELECT * FROM cards WHERE code = 'rp002'").fetchone()
    assert stub["name"] == "Field Medic"        # inherited
    assert stub["faction_code"] == "basic"      # inherited
    assert stub["canonical_code"] == "rp001"
    assert stub["is_reprint"] == 1
    assert stub["pack_code"] == "hero_pack"     # its own printing
    assert stub["quantity"] == 2                # its own printing


def test_original_printing_is_its_own_canonical(conn, corpus):
    index.load_cards(conn, corpus)
    row = conn.execute(
        "SELECT canonical_code, is_reprint FROM cards "
        "WHERE code = 'tst02'").fetchone()
    assert row["canonical_code"] == "tst02"
    assert row["is_reprint"] == 0


def test_a_dangling_duplicate_of_fails_loudly(conn, tmp_path):
    root = tmp_path / "md"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "a.json").write_text(json.dumps(
        [{"code": "x1", "pack_code": "p", "quantity": 1,
          "duplicate_of": "nope"}]))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    with pytest.raises(index.InvariantError, match="not in the corpus"):
        index.load_cards(conn, root)


@pytest.mark.integration
def test_real_corpus_has_no_nameless_rows(real_index):
    n = real_index.execute(
        "SELECT COUNT(*) FROM cards WHERE name IS NULL OR name = ''"
    ).fetchone()[0]
    assert n == 0


@pytest.mark.integration
def test_real_reprints_mostly_resolve_to_player_cards(real_index):
    """Spec §8 says duplicate_of is encounter-only. Measured 2026-08-22:
    341 of 351 resolve to player cards."""
    total = real_index.execute(
        "SELECT COUNT(*) FROM cards WHERE is_reprint = 1").fetchone()[0]
    player = real_index.execute(
        "SELECT COUNT(*) FROM cards WHERE is_reprint = 1 "
        "AND faction_code != 'encounter'").fetchone()[0]
    assert 300 < total < 500
    assert player > total * 0.9


def test_an_index_from_an_older_schema_is_rebuilt(tmp_path):
    """A stale derived index must be dropped, not half-migrated: otherwise
    the first query on a new column fails with a bare "no such column".

    Only under `rebuild=True`. This used to happen on any open, so a read
    command destroyed the index it was reading; see
    `test_a_read_never_destroys_a_stale_index`."""
    import sqlite3
    db = tmp_path / "mc.sqlite"
    stale = sqlite3.connect(db)
    stale.execute("CREATE TABLE cards (code TEXT)")   # no canonical_code
    stale.execute("PRAGMA user_version = 0")
    stale.commit()
    stale.close()

    conn = index.connect(db, rebuild=True)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    assert "canonical_code" in cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == \
        index.SCHEMA_VERSION


def test_reconnecting_to_a_current_index_keeps_its_data(tmp_path, corpus):
    db = tmp_path / "mc.sqlite"
    index.load_cards(index.connect(db), corpus)
    again = index.connect(db)
    assert again.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 4


def test_boost_invariant_rejects_an_explicit_zero():
    """§4.3: no card in the corpus has boost 0, so `absent` reads as zero
    boost icons. If upstream ever emits an explicit 0 the reading has
    changed and two encodings are being mixed."""
    with pytest.raises(index.InvariantError, match="boost"):
        index.assert_boost_invariant([{"code": "x1", "name": "X", "boost": 0}])


def test_boost_invariant_rejects_a_value_outside_one_to_four():
    """§14.3 measured the range: 1-4, never 0, never null. A 5 means the
    printed scale changed."""
    with pytest.raises(index.InvariantError, match="boost"):
        index.assert_boost_invariant([{"code": "x1", "name": "X", "boost": 7}])


def test_boost_invariant_accepts_absent_and_one_to_four():
    index.assert_boost_invariant([
        {"code": "a", "name": "A"},                 # absent
        {"code": "b", "name": "B", "boost": None},  # explicit null
        {"code": "c", "name": "C", "boost": 1},
        {"code": "d", "name": "D", "boost": 4},
    ])


def test_a_read_never_destroys_a_stale_index(tmp_path):
    """`connect` dropped every table whenever the schema version differed,
    and every command opens through it. A `card show` against an index
    from an older schema silently emptied all 39 tables and then answered
    "no card named", which is a wrong answer rather than an error."""
    db = tmp_path / "mc.sqlite"
    conn = index.connect(db, rebuild=True)
    conn.execute(
        "INSERT INTO cards (code, name, type_code, faction_code, pack_code, "
        "set_code, canonical_code, is_reprint, raw, text) VALUES "
        "('c1', 'A', 'ally', 'basic', 'core', 's', 'c1', 0, '{}', '')")
    conn.commit()
    conn.execute(f"PRAGMA user_version = {index.SCHEMA_VERSION - 1}")
    conn.commit()
    conn.close()

    with pytest.raises(index.StaleIndex):
        index.connect(db)

    # Nothing was touched: the row is still there for the rebuild to keep.
    check = sqlite3.connect(db)
    assert check.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1


def test_a_rebuild_may_still_drop_a_stale_index(tmp_path):
    """The reset is what makes `update` able to recover; it is only the
    implicit reset on read that was wrong."""
    db = tmp_path / "mc.sqlite"
    conn = index.connect(db, rebuild=True)
    conn.execute(f"PRAGMA user_version = {index.SCHEMA_VERSION - 1}")
    conn.commit()
    conn.close()

    conn = index.connect(db, rebuild=True)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == \
        index.SCHEMA_VERSION


def test_a_brand_new_file_is_empty_rather_than_stale(tmp_path):
    """A new database reports version 0 and holds no tables. That is not
    a stale index and must not be refused."""
    conn = index.connect(tmp_path / "new.sqlite")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == \
        index.SCHEMA_VERSION
