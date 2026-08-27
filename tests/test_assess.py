"""Scenario assembly and its threat profile (plan Tasks 5-6).

The fixtures here are shaped from the built index, never from an
assumption about it: the plan's own worked example was an assumption and
was wrong in three of its four numbers.
"""
import pytest

from mc_jarvis import assess, index


def _mkdb(tmp_path, sets, cards, roles, modulars=()):
    """A minimal index.

    `cards` rows are (code, name, type_code, set_code, quantity, boost,
    text, traits, back_link, is_reprint). `canonical_code`, `is_reprint`
    and `raw` are NOT NULL, so a fixture that omits them fails on the
    constraint rather than on the behaviour under test.
    """
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO sets (code, name, card_set_type_code) VALUES (?, ?, ?)",
        sets)
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, set_code, quantity, boost, "
        "text, traits, back_link, is_reprint, canonical_code, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
        [c + (c[0],) for c in cards])
    conn.executemany(
        "INSERT INTO encounter_role (code, role, returns_to_deck, decided_by) "
        "VALUES (?, ?, ?, 'test')", roles)
    conn.executemany(
        "INSERT INTO scenario_modulars (scenario_set, kind, modular_set) "
        "VALUES (?, ?, ?)", modulars)
    conn.commit()
    return conn


@pytest.fixture
def conn(tmp_path):
    return _mkdb(
        tmp_path,
        sets=[("rhino", "Rhino", "villain"), ("bomb", "Bomb Scare", "modular"),
              ("standard", "Standard", "standard"),
              ("other", "Other", "modular")],
        cards=[
            ("m1", "The Break-In!", "main_scheme", "rhino", 1, None, "",
             "", None, 0),
            ("v1", "Rhino", "villain", "rhino", 1, None, "", "", None, 0),
            ("t1", "Stampede", "treachery", "rhino", 3, 1, "", "", None, 0),
            ("a1", "Charge", "attachment", "rhino", 2, 2, "", "", None, 0),
            ("b1", "Bomb", "treachery", "bomb", 2, 1, "", "", None, 0),
            ("s1", "Caught Off Guard", "treachery", "standard", 1, 1, "", "",
             None, 0),
        ],
        roles=[("m1", "starts_in_play", 0), ("v1", "starts_in_play", 0),
               ("t1", "deck", 1), ("a1", "deck", 1), ("b1", "deck", 1),
               ("s1", "deck", 1)],
        modulars=[("rhino", "recommended", "bomb")])


# --- resolution ------------------------------------------------------

def test_resolve_uses_the_prescribed_modulars(conn):
    s = assess.resolve(conn, "rhino")
    assert s.modulars == ["bomb"]
    assert s.scenario_set == "rhino"


def test_explicit_modulars_override_rather_than_add(conn):
    """A player naming modulars is describing the game on their table, not
    amending a recommendation (spec §6)."""
    s = assess.resolve(conn, "rhino", modular=["other"])
    assert s.modulars == ["other"]


def test_an_unknown_villain_is_named_not_guessed(conn):
    with pytest.raises(assess.UnknownScenario, match="galactus"):
        assess.resolve(conn, "galactus")


def test_a_scenario_absent_from_the_card_data_says_so(conn):
    """Coverage is bounded by marvelcdb, which carries no Bullseye villain
    set even though the scenario is playable online. `assess` must say the
    scenario is absent rather than report a partial deck."""
    with pytest.raises(assess.UnknownScenario, match="not in the card data"):
        assess.resolve(conn, "bullseye")


# --- a scenario is not a villain (spec §14.10) -----------------------

def test_a_component_set_names_its_host_scenario(tmp_path):
    """`marauders` is 7 villains with no main scheme: it is a component of
    `morlock_siege` and `on_the_run`, not a scenario. Reporting "no
    modular mapping, pass --modular" would invite the player to assess a
    deck that does not exist."""
    c = _mkdb(
        tmp_path,
        sets=[("marauders", "Marauders", "villain"),
              ("morlock_siege", "Morlock Siege", "villain"),
              ("on_the_run", "On the Run", "villain"),
              ("standard", "Standard", "standard")],
        cards=[("v1", "Arclight", "villain", "marauders", 1, None, "", "",
                None, 0),
               ("m1", "Knock, Knock", "main_scheme", "morlock_siege", 1,
                None, "<b>Contents</b>: Marauders on side A.", "", None, 0),
               ("m2", "On the Run", "main_scheme", "on_the_run", 1, None,
                "<b>Contents</b>: Marauders and Standard sets.", "", None,
                0)],
        roles=[("v1", "starts_in_play", 0), ("m1", "starts_in_play", 0),
               ("m2", "starts_in_play", 0)],
        modulars=[("morlock_siege", "prescribed", None),
                  ("on_the_run", "prescribed", None)])
    with pytest.raises(assess.UnknownScenario) as e:
        assess.resolve(c, "marauders")
    assert "morlock_siege" in str(e.value)
    assert "on_the_run" in str(e.value)


def test_a_scenario_with_no_villain_set_of_its_own_resolves(tmp_path):
    """`morlock_siege` holds the main scheme and draws its villain from
    `marauders`. The profile keys on the scenario, so this is the normal
    case, not an exception."""
    c = _mkdb(
        tmp_path,
        sets=[("morlock_siege", "Morlock Siege", "villain"),
              ("mil", "Military Grade", "modular"),
              ("standard", "Standard", "standard")],
        cards=[("m1", "Knock, Knock", "main_scheme", "morlock_siege", 1, None,
                "", "", None, 0),
               ("t1", "Routed", "environment", "morlock_siege", 1, 2, "", "",
                None, 0)],
        roles=[("m1", "starts_in_play", 0), ("t1", "deck", 1)],
        modulars=[("morlock_siege", "prescribed", "mil")])
    s = assess.resolve(c, "morlock_siege")
    assert s.scenario_set == "morlock_siege"
    assert s.modulars == ["mil"]


# --- deck membership -------------------------------------------------

def test_the_difficulty_set_is_included(conn):
    """Omitting it understates the boost curve (spec §4.2)."""
    codes = {c["code"]
             for c in assess.deck_cards(conn, assess.resolve(conn, "rhino"))}
    assert "s1" in codes


def test_cards_that_are_not_in_the_deck_are_excluded(conn):
    codes = {c["code"]
             for c in assess.deck_cards(conn, assess.resolve(conn, "rhino"))}
    assert "v1" not in codes


def test_a_back_face_is_not_a_second_card(tmp_path):
    """A double-sided card is two rows in marvelsdb. 70 deck-role rows are
    back faces; `aoa_mission` returns 10 rows for 5 missions. The rule is
    `back_link`, cross-checked against the code-suffix pattern."""
    c = _mkdb(
        tmp_path,
        sets=[("aoa", "Missions", "villain"),
              ("standard", "Standard", "standard")],
        cards=[("m1", "A Scheme", "main_scheme", "aoa", 1, None, "", "", None,
                0),
               ("x1a", "Liberate", "side_scheme", "aoa", 1, 1, "", "", "x1b",
                0),
               ("x1b", "Liberate", "side_scheme", "aoa", 1, 1, "", "", None,
                0)],
        roles=[("m1", "starts_in_play", 0), ("x1a", "deck", 1),
               ("x1b", "deck", 1)],
        modulars=[("aoa", "prescribed", None)])
    codes = {r["code"] for r in assess.deck_cards(c, assess.resolve(c, "aoa"))}
    assert codes == {"x1a"}


def test_a_reprint_is_not_a_second_card(tmp_path):
    c = _mkdb(
        tmp_path,
        sets=[("v", "V", "villain"), ("standard", "Standard", "standard")],
        cards=[("m1", "A Scheme", "main_scheme", "v", 1, None, "", "", None,
                0),
               ("t1", "Thing", "treachery", "v", 1, 1, "", "", None, 0),
               ("t2", "Thing", "treachery", "v", 1, 1, "", "", None, 1)],
        roles=[("m1", "starts_in_play", 0), ("t1", "deck", 1),
               ("t2", "deck", 1)],
        modulars=[("v", "prescribed", None)])
    codes = {r["code"] for r in assess.deck_cards(c, assess.resolve(c, "v"))}
    assert codes == {"t1"}


def test_a_card_that_starts_in_play_but_cycles_back_is_carried(tmp_path):
    """The three [[Setting]] environments start in play, are discarded when
    another is revealed, and rejoin the deck. Each carries a boost value
    and a When Revealed ability, which are meaningless from outside the
    deck. Carried, and tagged with its role so the opening deck can still
    be reported apart."""
    c = _mkdb(
        tmp_path,
        sets=[("v", "V", "villain"), ("standard", "Standard", "standard")],
        cards=[("m1", "A Scheme", "main_scheme", "v", 1, None, "", "", None,
                0),
               ("e1", "The Savage Land", "environment", "v", 1, 3, "", "",
                None, 0)],
        roles=[("m1", "starts_in_play", 0), ("e1", "starts_in_play", 1)],
        modulars=[("v", "prescribed", None)])
    rows = assess.deck_cards(c, assess.resolve(c, "v"))
    assert [(r["code"], r["role"]) for r in rows] == [("e1", "starts_in_play")]


def test_a_modular_set_is_not_a_scenario(tmp_path):
    """`aoa_mission` and `exp_kang` have no main scheme and are typed
    `modular`. Calling them components of a scenario would be true but
    unhelpful; they are sets the player adds."""
    c = _mkdb(
        tmp_path,
        sets=[("exp_kang", "Expert Kang", "modular"),
              ("standard", "Standard", "standard")],
        cards=[("v1", "Kang", "villain", "exp_kang", 1, None, "", "", None,
                0)],
        roles=[("v1", "starts_in_play", 0)])
    with pytest.raises(assess.UnknownScenario, match="--modular"):
        assess.resolve(c, "exp_kang")


# --- real-corpus gates -----------------------------------------------

@pytest.mark.integration
def test_rhino_standard_matches_a_hand_count(real_index):
    """The plan's own worked example was wrong in three of four numbers;
    this is the arithmetic re-done from the index, card by card.

        rhino     Charge              x2  boost 2  ->  4
        rhino     Enhanced Ivory Horn x1  boost 2  ->  2
        rhino     Armored Rhino Suit  x1  boost -  ->  0
        rhino     Hydra Mercenary     x2  boost 1  ->  2
        rhino     Sandman             x1  boost 2  ->  2
        rhino     Shocker             x1  boost 2  ->  2
        rhino     Hard to Keep Down   x2  boost -  ->  0
        rhino     "I'm Tough"         x2  boost -  ->  0
        rhino     Stampede            x3  boost 1  ->  3
        rhino     Breakin' & Takin'   x1  boost 2  ->  2
        rhino     Crowd Control       x1  boost 2  ->  2
        standard  Advance             x2  boost -  ->  0
        standard  Assault             x2  boost -  ->  0
        standard  Caught Off Guard    x1  boost 1  ->  1
        standard  Gang-Up             x1  boost 1  ->  1
        standard  Shadow of the Past  x1  boost 2  ->  2

    17 + 7 = 24 copies, 19 + 4 = 23 boost. The three villain stages and
    both main scheme faces are excluded by type.
    """
    s = assess.resolve(real_index, "rhino", modular=[], difficulty="standard")
    rows = assess.deck_cards(real_index, s)
    copies = sum(r["quantity"] for r in rows)
    boost = sum((r["boost"] or 0) * r["quantity"] for r in rows)

    by_set = {}
    for r in rows:
        by_set[r["set_code"]] = by_set.get(r["set_code"], 0) + r["quantity"]

    assert by_set == {"rhino": 17, "standard": 7}, by_set
    assert copies == 24
    assert boost == 23


@pytest.mark.integration
def test_a_double_sided_set_is_not_counted_twice(real_index):
    """`aoa_mission` is five missions and ten rows. rhino has no a/b deck
    rows, so the gate above cannot catch the back-face double-count; this
    one can."""
    raw = real_index.execute(
        "SELECT COUNT(*) n FROM cards c JOIN encounter_role e ON e.code = "
        "c.code WHERE c.set_code = 'aoa_mission' AND e.role = 'deck'"
    ).fetchone()["n"]
    assert raw == 10

    s = assess.Scenario(scenario_set="rhino", modulars=["aoa_mission"])
    rows = [r for r in assess.deck_cards(real_index, s)
            if r["set_code"] == "aoa_mission"]
    assert len(rows) == 5, [r["code"] for r in rows]


@pytest.mark.integration
def test_no_unexamined_back_face_remains(real_index):
    assert assess.back_face_gate(real_index) == []


@pytest.mark.integration
def test_every_component_set_can_name_its_scenario_or_say_it_cannot(
        real_index):
    """The six sets with a villain but no main scheme. Each must produce a
    message that sends the player somewhere, not a partial deck."""
    for code in ("marauders", "wrecker", "bulldozer", "piledriver",
                 "thunderball"):
        with pytest.raises(assess.UnknownScenario) as e:
            assess.resolve(real_index, code)
        assert "component of a scenario" in str(e.value), code
        assert "faced in:" in str(e.value), code


@pytest.mark.integration
def test_the_pvp_difficulty_set_ships_each_card_twice(real_index):
    """Not a bug to fix here, a fact to keep visible. `standard_pvp` holds
    two originals of each card - `cw` prints the set once per scenario -
    plus two reprints. Filtering reprints leaves 2x, so any PvP profile
    would report a doubled difficulty set. Part 2's problem; this asserts
    the shape so it cannot change unnoticed."""
    rows = real_index.execute(
        "SELECT name, COUNT(*) n, SUM(is_reprint) r FROM cards "
        "WHERE set_code = 'standard_pvp' GROUP BY name").fetchall()
    assert rows
    for row in rows:
        assert row["n"] == 4, dict(row)
        assert row["r"] == 2, dict(row)
