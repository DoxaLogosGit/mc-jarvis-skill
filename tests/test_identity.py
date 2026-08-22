import json

import pytest

from mc_jarvis import cards, identity, index
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(
        fx.PACK + fx.MATCH_FAMILY + fx.EXTRA_FORMS + fx.MULTI_IDENTITY))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    identity.build(c)
    return c


def test_extra_hero_form_is_part_of_the_identity(conn):
    """frm01c has back_link None; grouping on back_link would drop it."""
    faces = [r["code"] for r in conn.execute(
        "SELECT code FROM identity_faces WHERE identity_key = 'skyward' "
        "ORDER BY code")]
    assert faces == ["frm01a", "frm01b", "frm01c"]


def test_multi_card_identity_is_one_identity(conn):
    """The Ironheart shape: three identity cards, six faces, one identity."""
    assert conn.execute(
        "SELECT COUNT(*) FROM identity_faces WHERE identity_key = 'cascade'"
    ).fetchone()[0] == 6
    assert conn.execute(
        "SELECT COUNT(*) FROM identities WHERE identity_key = 'cascade'"
    ).fetchone()[0] == 1


def test_titles_include_every_linked_face(conn):
    assert identity.titles_for(conn, "mtc01a") == {"nightjar", "ada vance"}


def test_subname_participates_in_matching(conn):
    """mtc03's title differs from mtc02's; they match via subname."""
    assert identity.matches(conn, "mtc03", "mtc02") is True
    assert identity.matches(conn, "mtc01a", "mtc03") is True


def test_same_title_different_alter_ego_does_not_match(conn):
    """The false positive string equality produces: two heroes share the
    title 'Nightjar' but their alter-egos differ (spec §8)."""
    assert identity.matches(conn, "mtc01a", "mtc04a") is False


def test_non_unique_cards_never_match(conn):
    assert identity.matches(conn, "tst02", "tst02") is False


def test_identity_command_returns_all_faces(conn):
    result = cards.identity(conn, "Skyward")
    assert len(result["faces"]) == 3
    assert {f["hand_size"] for f in result["faces"]} == {4, 5, 6}


def test_identity_found_by_an_alter_ego_name(conn):
    assert cards.identity(conn, "Nell Cross")["identity_key"] == "skyward"


@pytest.mark.integration
def test_real_ironheart_has_six_faces(real_index):
    assert len(cards.identity(real_index, "Ironheart")["faces"]) == 6


@pytest.mark.integration
def test_real_angel_keeps_its_third_form(real_index):
    faces = cards.identity(real_index, "Angel")["faces"]
    assert len(faces) == 3
    assert "Archangel" in {f["name"] for f in faces}


@pytest.mark.integration
def test_real_black_panther_heroes_do_not_match(real_index):
    """The RR's own worked example, in both directions (spec §8)."""
    assert identity.matches(real_index, "01040a", "51001a") is False
    assert identity.matches(real_index, "01040a", "23012") is True
    assert identity.matches(real_index, "01040a", "51002") is True


# --- the four matching scopes (RR p.45-46), verified 2026-08-22 ---

@pytest.mark.integration
def test_deckbuilding_scope_daredevil(real_index):
    """The subtitle is what makes it illegal. Daredevil "Matt Murdock"
    cannot go in a Daredevil / Matt Murdock deck; the plain Daredevil
    ally can, because nothing on it says Matt Murdock."""
    pairs = identity.matching_pairs(
        real_index, ["60001a", "60001b", "01058", "31014"])
    flat = {frozenset(p) for p in pairs}
    assert frozenset({"60001a", "01058"}) in flat      # subtitle matches
    assert frozenset({"60001a", "31014"}) not in flat  # no subtitle: legal


@pytest.mark.integration
def test_an_identitys_own_faces_never_conflict(real_index):
    assert identity.matching_pairs(real_index, ["60001a", "60001b"]) == []


@pytest.mark.integration
def test_rr_clause_one_example_ally_and_minion(real_index):
    """The RR's own example: the Jessica Jones ally and the Jessica Jones
    minion match, because neither has a subtitle or alter-ego title."""
    assert identity.matches(real_index, "01059", "56185") is True


@pytest.mark.integration
def test_alter_ego_title_decides_the_minion_case(real_index):
    """Jessica Jones's alter-ego is also Jessica Jones, so her identity
    matches the minion. Daredevil's is Matt Murdock, so his does not -
    clause one needs BOTH cards to lack a subtitle and alter-ego title."""
    assert identity.matches(real_index, "61001a", "56185") is True
    assert identity.matches(real_index, "60001a", "56189") is False


@pytest.mark.integration
def test_play_scope_spans_the_whole_table(real_index):
    """RR p.46: a non-villain card matching a card in play cannot enter
    play - from any player's deck. Gamora's signature Nebula ally is
    blocked while the Nebula identity is in play, and vice versa."""
    assert identity.blocks_entering_play(
        real_index, "18002", ["22001a", "22001b"])
    assert identity.blocks_entering_play(
        real_index, "22002", ["18001a", "18001b"])


@pytest.mark.integration
def test_a_villain_never_blocks_and_is_never_blocked(real_index):
    """RR p.45 explicitly permits a scenario whose villain matches a
    chosen identity, so Nebula may face the Nebula villain."""
    assert identity.villain_matches_identity(real_index, "16088", "nebu")
    assert identity.blocks_entering_play(real_index, "16088", ["22001a"]) == []


@pytest.mark.integration
def test_identity_selection_scope(real_index):
    """RR p.45: players cannot choose matching identities at setup."""
    assert identity.identities_conflict(real_index, ["nebu", "gam"]) == []
    conflict = identity.identities_conflict(real_index, ["daredevil", "echo"])
    assert isinstance(conflict, list)
