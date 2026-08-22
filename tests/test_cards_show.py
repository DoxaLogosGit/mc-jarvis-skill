import json

import pytest

from mc_jarvis import cards, index
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    pack = fx.PACK + fx.REPRINTS + [
        # The trap: one name, two genuinely different cards.
        fx.card("tst20", "Tester", type_code="ally",
                faction_code="leadership", cost=3),
    ]
    (root / "pack" / "tst.json").write_text(json.dumps(pack))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    return c


def test_lookup_by_code_is_exact(conn):
    assert cards.show(conn, "tst02")["card"]["name"] == "Ordinary Ally"


def test_unambiguous_name_resolves(conn):
    assert cards.show(conn, "Ordinary Ally")["card"]["code"] == "tst02"


def test_name_shared_by_a_hero_and_an_ally_is_ambiguous(conn):
    result = cards.show(conn, "Tester")
    assert "card" not in result
    assert {c["code"] for c in result["ambiguous"]} == {"tst01a", "tst20"}


def test_name_match_is_case_insensitive(conn):
    assert cards.show(conn, "ordinary ally")["card"]["code"] == "tst02"


def test_linked_faces_are_returned_together(conn):
    result = cards.show(conn, "tst01a")
    assert [f["code"] for f in result["faces"]] == ["tst01a", "tst01b"]


def test_unknown_name_returns_no_match(conn):
    assert cards.show(conn, "Nonexistent")["ambiguous"] == []


def test_a_reprint_code_resolves_to_its_canonical_card(conn):
    """Looking up the Ant-Man printing must show the real card, and say
    which packs carry it."""
    result = cards.show(conn, "rp002")
    assert result["card"]["code"] == "rp001"
    assert result["card"]["name"] == "Field Medic"
    assert {p["pack_code"] for p in result["printings"]} == \
        {"core", "hero_pack"}


def test_a_reprint_does_not_make_a_name_ambiguous(conn):
    """rp001 and rp002 are the same card. Two printings must not look
    like two candidates."""
    assert cards.show(conn, "Field Medic")["card"]["code"] == "rp001"


@pytest.mark.integration
def test_real_black_panther_is_ambiguous(real_index):
    """Two distinct heroes plus allies share this title (spec §8)."""
    result = cards.show(real_index, "Black Panther")
    assert "card" not in result
    assert len(result["ambiguous"]) >= 3


@pytest.mark.integration
def test_real_identity_returns_both_faces(real_index):
    result = cards.show(real_index, "01040a")
    codes = [f["code"] for f in result["faces"]]
    assert "01040a" in codes and "01040b" in codes
