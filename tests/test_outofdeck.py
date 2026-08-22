import copy
import json

import pytest

from mc_jarvis import identity, index, outofdeck
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(
        fx.PACK + fx.OUT_OF_DECK + fx.SPDR))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text(json.dumps(fx.SETS))
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    identity.build(c)
    return c


def _codes(conn, mechanism=None):
    sql = "SELECT code FROM out_of_deck"
    args = ()
    if mechanism:
        sql += " WHERE mechanism = ?"
        args = (mechanism,)
    return {r["code"] for r in conn.execute(sql, args)}


def _bare():
    cfg = copy.deepcopy(fx.CONFIG_COVERING_EMBERLINE)
    cfg["out_of_deck"]["exceptions"] = []
    return cfg


def test_permanent_cards_are_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood01" in _codes(conn, "permanent")


def test_hero_special_set_members_are_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood02" in _codes(conn, "hero_special")


def test_config_exceptions_are_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood03" in _codes(conn, "config")


def test_ordinary_signature_cards_are_not_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood04" not in _codes(conn)


def test_identity_faces_are_never_in_the_deck(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert {"ood00a", "ood00b"} <= _codes(conn, "identity")


def test_audit_flags_an_uncovered_identity(conn):
    uncovered = [f for f in outofdeck.setup_audit(conn, _bare())
                 if not f.covered]
    assert [f.identity_key for f in uncovered] == ["edge"]
    assert "Kindling" in uncovered[0].quote


def test_audit_passes_once_the_config_covers_it(conn):
    findings = outofdeck.setup_audit(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert all(f.covered for f in findings)
    assert findings[0].covered_by == "config"


def test_audit_does_not_auto_resolve_prose_to_a_card(conn):
    """Brunnhilde's text says "Death Glow"; the card is "Death-Glow". Any
    exact-match resolution would silently miss it (spec §10)."""
    finding = outofdeck.setup_audit(conn, _bare())[0]
    assert not hasattr(finding, "resolved_code")


def test_classify_raises_when_audit_is_uncovered(conn):
    with pytest.raises(outofdeck.AuditError, match="edge"):
        outofdeck.classify(conn, _bare(), strict=True)


def test_spdr_permanent_does_not_match_its_hero_face(conn):
    """Spec §10 says Sp//dr forces exclusion to run before unique-match,
    because her hero face and her permanent support share a title.

    Under a correct reading of RR p.45 they do not match at all: the
    first clause fires only when BOTH cards have no subtitle and no
    alter-ego title, and the hero face has one. Verified on real data
    (31001a / 31001b). §10's constraint is an artifact of implementing
    matching as name equality - which §8 warns against three paragraphs
    earlier. Exclusion still runs first, for deck-size math, but it is
    not what makes Sp//dr legal.
    """
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert identity.matches(conn, "spd01a", "spd02") is False
    assert "spd02" in _codes(conn, "permanent")


def test_two_plain_unique_cards_sharing_a_title_do_match(conn):
    """The first clause must still fire when neither card has a subtitle
    or an alter-ego title - otherwise nothing would ever match by title."""
    conn.executemany(
        "INSERT INTO card_titles (code, role, title) VALUES (?, ?, ?)",
        [("z1", "title", "echo"), ("z2", "title", "echo")])
    assert identity.matches(conn, "z1", "z2") is True


@pytest.mark.integration
def test_real_audit_flags_eight_identities_and_covers_them_all(real_index):
    """Verified 2026-08-22: these patterns flag eight identities, not the
    four spec §10 claims - the spec's scan was narrower."""
    findings = outofdeck.setup_audit(real_index, outofdeck.load_config())
    keys = {f.identity_key for f in findings}
    assert {"daredevil", "doctor_strange", "hercules", "iceman",
            "ironheart", "rogue", "storm", "valk"} <= keys
    assert all(f.covered for f in findings), \
        [(f.identity_key, f.quote) for f in findings if not f.covered]


@pytest.mark.integration
def test_real_rogue_and_valkyrie_are_covered_only_by_config(real_index):
    """Neither set contains a permanent card, so nothing structural can
    stand in for the config entries."""
    findings = {f.identity_key: f for f in
                outofdeck.setup_audit(real_index, outofdeck.load_config())}
    for key in ("rogue", "valk"):
        assert findings[key].covered_by == "config", key


@pytest.mark.integration
def test_extra_hero_forms_are_not_blanket_exempted(real_index):
    """Angel, Ant-Man and Wasp have a third face but one alter-ego. If they
    ever gain set-aside text, the audit must still flag them."""
    for key in ("angel", "ant", "wsp"):
        n = real_index.execute(
            "SELECT COUNT(*) FROM identity_faces f JOIN cards c "
            "ON c.code = f.code WHERE f.identity_key = ? "
            "AND c.type_code = 'alter_ego'", (key,)).fetchone()[0]
        assert n == 1, key
