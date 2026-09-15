import json

import pytest

from mc_jarvis import cards, index
from tests.fixtures import cards as fx

ENCOUNTER = [
    fx.card("enc01", "The Collector", type_code="villain",
            faction_code="encounter", set_code="collector",
            health=12, attack=2, thwart=2, quantity=1, deck_limit=None,
            text="Stage 1."),
    fx.card("enc02", "The Collector", type_code="villain",
            faction_code="encounter", set_code="collector",
            health=16, attack=3, thwart=2, quantity=1, deck_limit=None,
            text="Stage 2."),
    fx.card("enc03", "Gathering Swarm", type_code="minion",
            faction_code="encounter", set_code="collector",
            health=3, attack=1, thwart=1, quantity=3, deck_limit=None),
]


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.PACK + ENCOUNTER))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text(json.dumps(
        [{"code": "collector", "name": "The Collector",
          "card_set_type_code": "villain"}]))
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    return c


def test_villain_stages_are_returned_in_order(conn):
    assert [v["health"] for v in
            cards.encounter(conn, "The Collector")["villain"]] == [12, 16]


def test_set_contents_include_quantities(conn):
    swarm = next(c for c in cards.encounter(conn, "The Collector")["contents"]
                 if c["name"] == "Gathering Swarm")
    assert swarm["quantity"] == 3


def test_lookup_by_set_code_works(conn):
    assert cards.encounter(conn, "collector")["set_code"] == "collector"


def test_lookup_by_villain_name_works(conn):
    assert cards.encounter(conn, "Gathering Swarm")["set_code"] == "collector"


def test_unknown_set_returns_empty(conn):
    assert cards.encounter(conn, "Nobody")["set_code"] is None


@pytest.mark.integration
def test_real_villain_has_multiple_stages(real_index):
    result = cards.encounter(real_index, "Rhino")
    assert result["set_code"] is not None
    assert len(result["villain"]) >= 2
    healths = [v["health"] for v in result["villain"]]
    assert healths == sorted(healths)      # stages escalate


@pytest.mark.integration
def test_real_set_contents_are_not_duplicated_by_reprints(real_index):
    codes = [c["code"] for c in
             cards.encounter(real_index, "Rhino")["contents"]]
    assert len(codes) == len(set(codes))


@pytest.mark.integration
def test_villains_carry_scheme_stage_and_per_hero_health(real_index):
    """Villains scheme rather than thwart, and their hit points are
    multiplied by the player count - which the output must say, because
    the printed number is not what you write on the tracker."""
    villains = cards.encounter(real_index, "Rhino")["villain"]
    assert [v["stage"] for v in villains] == ["I", "II", "III"]
    assert all(v["scheme"] is not None for v in villains)
    assert all(v["thwart"] is None for v in villains)
    assert all(v["health_per_hero"] for v in villains)


def test_a_leader_has_stages_like_a_villain(tmp_path):
    """A PvP leader is the opposition the table plays against: its cards
    carry stages, hit points per hero, ATK and SCH exactly as a villain's
    do. Filtering the stage line to `type_code = 'villain'` printed a
    leader set's contents with no stats for the card being fought."""
    from mc_jarvis import cards, index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.execute("INSERT INTO sets (code, name, card_set_type_code) "
                 "VALUES ('iron_man_leader', 'Iron Man', 'leader')")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, set_code, stage, health, "
        "health_per_hero, attack, scheme, faction_code, pack_code, "
        "canonical_code, is_reprint, raw, text) VALUES "
        "(?, 'Iron Man', 'leader', 'iron_man_leader', ?, ?, 1, ?, 1, "
        "'encounter', 'cw', ?, 0, '{}', '')",
        [("l1", "I", 12, 1, "l1"), ("l2", "II", 16, 2, "l2")])
    conn.commit()

    got = cards.encounter(conn, "iron_man_leader")
    assert [v["stage"] for v in got["villain"]] == ["I", "II"]
    assert got["villain"][0]["health"] == 12


# --- main scheme stages ----------------------------------------------

SCHEMES = [
    fx.card("enc10a", "Big Plan", type_code="main_scheme",
            faction_code="encounter", set_code="collector", quantity=1,
            deck_limit=None, back_link="enc10b", stage="1A",
            text="Setup: Advance to stage 1B."),
    fx.card("enc10b", "Big Plan", type_code="main_scheme",
            faction_code="encounter", set_code="collector", quantity=1,
            deck_limit=None, stage="1B", base_threat=1,
            escalation_threat=1, threat=6),
    fx.card("enc11", "Heist", type_code="side_scheme",
            faction_code="encounter", set_code="collector", quantity=1,
            deck_limit=None, base_threat=3, base_threat_fixed=True,
            scheme_hazard=1, boost=2),
]


@pytest.fixture
def schemed(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(
        json.dumps(fx.PACK + ENCOUNTER + SCHEMES))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text(json.dumps(
        [{"code": "collector", "name": "The Collector",
          "card_set_type_code": "villain"}]))
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    return c


def test_main_scheme_stages_carry_their_threat(schemed):
    """An agent asked about The Hood read `encounter`, saw villain stages
    and no scheme numbers, and told the player the index did not have
    them. It did; nothing printed them."""
    stages = cards.encounter(schemed, "collector")["main_scheme"]
    assert [s["code"] for s in stages] == ["enc10b"]
    assert cards.scheme_line(stages[0]) == (
        "threat: starts at 1 per hero, +1 per hero each villain phase, "
        "completes at 6 per hero")


def test_card_show_prints_scheme_threat_icons_and_boost(
        schemed, capsys, monkeypatch):
    import argparse

    monkeypatch.setattr(cards, "_open", lambda: schemed)
    cards.handle_show(argparse.Namespace(name="Heist", json=False))
    out = capsys.readouterr().out
    assert "threat: starts at 3\n" in out
    assert "icons: hazard" in out
    assert "boost 2" in out


def test_both_faces_of_one_card_are_not_ambiguous(schemed):
    got = cards.show(schemed, "Big Plan")
    assert [f["code"] for f in got["faces"]] == ["enc10a", "enc10b"]


def test_an_X_value_is_not_printed_as_a_number():
    line = cards.scheme_line({"base_threat": 4, "escalation_threat": -1,
                              "escalation_threat_fixed": 1,
                              "target_threat": 11})
    assert "+X each villain phase" in line


def test_every_real_scenario_shows_its_main_scheme_threat(real_index):
    """The invariant the Hood case broke, over every villain set."""
    sets = [r[0] for r in real_index.execute(
        "SELECT DISTINCT set_code FROM cards WHERE type_code = 'main_scheme' "
        "AND target_threat IS NOT NULL AND is_reprint = 0")]
    assert len(sets) > 40
    missing = [s for s in sets
               if not cards.encounter(real_index, s)["main_scheme"]]
    assert not missing, missing


def test_a_shared_set_name_opens_the_villain_not_the_hero(real_index):
    """`encounter venom` printed Venom's hero cards."""
    got = cards.encounter(real_index, "Venom")
    assert got["set_code"] == "venom"
    assert "vnm" in got["also"]
    assert cards.encounter(real_index, "vnm")["set_code"] == "vnm"
