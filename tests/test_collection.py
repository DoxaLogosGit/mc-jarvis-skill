"""Pack ownership (spec §10, corrected by §10.1)."""
import pytest

from mc_jarvis import collection, index


def _mkdb(tmp_path):
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO packs (code, name) VALUES (?, ?)",
        [("core", "Core Set"), ("sm", "Sinister Motives"),
         ("aos", "Agents of S.H.I.E.L.D.")])
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, pack_code, duplicate_of, "
        "canonical_code, is_reprint, raw) VALUES (?, ?, ?, ?, ?, ?, ?, '{}')",
        [("01001a", "Spider-Man", "hero", "core", None, "01001a", 0),
         ("27047", "Dum Dum Dugan", "ally", "sm", None, "27047", 0),
         ("50021", "Dum Dum Dugan", "ally", "aos", "27047", "27047", 1),
         ("27099", "Web-Shooter", "upgrade", "sm", None, "27099", 0)])
    conn.commit()
    return conn


def test_owning_a_reprint_pack_gives_you_the_card(tmp_path):
    """§10.1's correction. `WHERE pack_code IN (owned)` - §10's filter -
    would hide Dum Dum Dugan from a player who owns only Agents of
    S.H.I.E.L.D., because his canonical printing is in Sinister Motives."""
    conn = _mkdb(tmp_path)
    collection.set_packs(conn, ["core", "aos"])
    assert "27047" in collection.filter_codes(conn, ["27047", "27099"])


def test_a_card_from_no_owned_pack_is_filtered_out(tmp_path):
    conn = _mkdb(tmp_path)
    collection.set_packs(conn, ["core", "aos"])
    assert "27099" not in collection.filter_codes(conn, ["27047", "27099"])


def test_an_empty_collection_filters_nothing_out(tmp_path):
    """No collection means the player has not said, which is different
    from owning nothing. Filtering everything away would look like a
    broken index."""
    conn = _mkdb(tmp_path)
    assert collection.owned_packs(conn) == []
    assert set(collection.filter_codes(conn, ["27047", "27099"])) == {
        "27047", "27099"}


def test_setting_packs_replaces_rather_than_appends(tmp_path):
    conn = _mkdb(tmp_path)
    collection.set_packs(conn, ["core", "sm"])
    collection.set_packs(conn, ["core"])
    assert collection.owned_packs(conn) == ["core"]


def test_an_unknown_pack_code_is_named_not_ignored(tmp_path):
    """A typo that silently sets an empty collection is the worst
    outcome: every later search quietly returns less."""
    conn = _mkdb(tmp_path)
    with pytest.raises(collection.UnknownPack, match="corr"):
        collection.set_packs(conn, ["core", "corr"])


def test_a_rejected_set_leaves_the_previous_collection_intact(tmp_path):
    """A typo must not clear what was there. `DELETE` before validating
    would leave the player owning nothing after a one-character slip."""
    conn = _mkdb(tmp_path)
    collection.set_packs(conn, ["core"])
    with pytest.raises(collection.UnknownPack):
        collection.set_packs(conn, ["core", "corr"])
    assert collection.owned_packs(conn) == ["core"]


def test_owned_is_offered_only_where_it_means_something():
    """`cli._leaf` adds `--owned` to all 14 leaf commands (§10.1), so
    un-stubbing it is a per-command decision. It is meaningless on
    `doctor`, `status`, `update`, `install-skill`, `timing` and
    `rules search`, and offering it there implies a filter that never
    happens."""
    assert "card search" in collection.OWNED_COMMANDS
    assert "identity" in collection.OWNED_COMMANDS
    for name in ("doctor", "status", "update", "install-skill", "timing",
                 "rules search"):
        assert name not in collection.OWNED_COMMANDS
