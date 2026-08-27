"""Scenario assembly and its threat profile (plan Tasks 5-6).

The fixtures here are shaped from the built index, never from an
assumption about it: the plan's own worked example was an assumption and
was wrong in three of its four numbers.
"""
import pytest

from mc_jarvis import assess, index


def _mkdb(tmp_path, sets, cards, roles, modulars=(), keywords=()):
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
    conn.executemany(
        "INSERT INTO card_keywords (code, keyword, printed) VALUES (?, ?, ?)",
        keywords)
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


# --- aggregation (plan Task 6) ---------------------------------------

def test_boost_mean_is_quantity_weighted(conn):
    """Stampede x3 boost 1 and Charge x2 boost 2 give (3 + 4)/5, not the
    row mean of 1.5. A mean over distinct rows is not the expected boost
    of a card the player draws (§4.5)."""
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["deck_size"] == 6
    assert round(got["boost"]["mean"], 3) == round((3 * 1 + 2 * 2 + 1) / 6, 3)


def test_a_card_with_no_boost_counts_as_zero_not_as_missing(conn):
    """§4.3: absent means zero boost icons, measured flat across seven
    years of releases. Excluding those cards from the denominator inflates
    the mean."""
    conn.execute(
        "INSERT INTO cards (code, name, type_code, set_code, quantity, boost, "
        "text, traits, is_reprint, canonical_code, raw) VALUES "
        "('t9','Quiet','treachery','rhino',1,NULL,'','',0,'t9','{}')")
    conn.execute("INSERT INTO encounter_role (code, role, returns_to_deck, "
                 "decided_by) VALUES ('t9','deck',1,'test')")
    conn.commit()
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["deck_size"] == 7
    assert round(got["boost"]["mean"], 3) == round((3 + 4 + 1) / 7, 3)


def test_the_histogram_sums_to_the_deck_size(conn):
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert sum(got["boost"]["histogram"].values()) == got["deck_size"]


def test_boost_star_is_counted_never_averaged(conn):
    """§4.4: the star is an additional icon with a card-specific effect,
    not a numeric value. 134 cards carry both."""
    conn.execute("UPDATE cards SET boost_star = 1 WHERE code = 'a1'")
    conn.commit()
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["boost"]["star_copies"] == 2       # Charge x2
    assert round(got["boost"]["mean"], 3) == round((3 * 1 + 2 * 2 + 1) / 6, 3)


def test_every_number_can_name_its_cards(conn):
    """§8: so the model can cite rather than assert."""
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["by_type"]["treachery"]["cards"]


def test_the_denominator_is_reported_with_the_mean(conn):
    """§8: reported with the deck size it is drawn over, so the reader can
    see the denominator."""
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["boost"]["over"] == got["deck_size"]


def test_the_opening_deck_is_reported_apart_from_what_cycles_in(tmp_path):
    """The [[Setting]] environments start in play and rejoin the deck when
    another is revealed. They belong in the composition, but a player
    shuffling their opening deck does not hold them. One number cannot say
    both, so `profile` reports two."""
    c = _mkdb(
        tmp_path,
        sets=[("v", "V", "villain"), ("standard", "Standard", "standard")],
        cards=[("m1", "A Scheme", "main_scheme", "v", 1, None, "", "", None,
                0),
               ("t1", "Thing", "treachery", "v", 2, 1, "", "", None, 0),
               ("e1", "The Savage Land", "environment", "v", 1, 3, "", "",
                None, 0)],
        roles=[("m1", "starts_in_play", 0), ("t1", "deck", 1),
               ("e1", "starts_in_play", 1)],
        modulars=[("v", "prescribed", None)])
    got = assess.profile(c, assess.resolve(c, "v"))
    assert got["deck_size"] == 3
    assert got["opening_deck_size"] == 2
    assert got["cycles_in"] == [{"code": "e1", "name": "The Savage Land",
                                 "quantity": 1}]


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


# --- minions, treacheries, schemes, keywords (plan Task 7) -----------

@pytest.fixture
def rhinolike(tmp_path):
    """Shaped from the real `rhino` set: three minions with the keywords
    those cards actually print, and two side schemes, one fixed-threat and
    one per-hero."""
    c = _mkdb(
        tmp_path,
        sets=[("rhino", "Rhino", "villain"),
              ("standard", "Standard", "standard")],
        cards=[
            ("m0", "The Break-In!", "main_scheme", "rhino", 1, None, "", "",
             None, 0),
            ("m1", "Hydra Mercenary", "minion", "rhino", 2, 1, "Guard.", "",
             None, 0),
            ("m2", "Sandman", "minion", "rhino", 1, 2, "Toughness.", "", None,
             0),
            ("m3", "Shocker", "minion", "rhino", 1, 2, "", "", None, 0),
            ("t1", "Stampede", "treachery", "rhino", 3, 1,
             "<b>When Revealed (Alter-Ego)</b>: This card gains surge.", "",
             None, 0),
            ("t2", "Diabolical Discs", "treachery", "rhino", 1, 1, "Surge.",
             "", None, 0),
            ("ss1", "Breakin' & Takin'", "side_scheme", "rhino", 1, 2, "", "",
             None, 0),
            ("ss2", "Crowd Control", "side_scheme", "rhino", 1, 2, "", "",
             None, 0),
        ],
        roles=[("m0", "starts_in_play", 0), ("m1", "deck", 1),
               ("m2", "deck", 1), ("m3", "deck", 1), ("t1", "deck", 1),
               ("t2", "deck", 1), ("ss1", "deck", 1), ("ss2", "deck", 1)],
        modulars=[("rhino", "prescribed", None)],
        keywords=[("m1", "guard", 1), ("m2", "toughness", 1),
                  ("t1", "surge", 0), ("t2", "surge", 1)])
    c.executemany("UPDATE cards SET health=?, attack=?, scheme=?, "
                  "health_per_hero=? WHERE code=?",
                  [(3, 1, 0, None, "m1"), (4, 3, 2, 1, "m2"),
                   (3, 2, 1, None, "m3")])
    c.executemany("UPDATE cards SET base_threat=?, base_threat_fixed=? "
                  "WHERE code=?", [(2, 1, "ss1"), (2, None, "ss2")])
    c.commit()
    return c


def test_minion_profile_reports_ranges_and_keywords(rhinolike):
    got = assess.profile(rhinolike, assess.resolve(rhinolike, "rhino"))
    m = got["minions"]
    assert m["copies"] == 4
    assert m["health"] == {"min": 3, "max": 4}
    assert m["scales_per_hero"] == 1          # Sandman only
    assert m["keywords"]["guard"] == 2        # quantity-weighted
    assert m["keywords"]["toughness"] == 1


def test_a_granted_keyword_is_never_folded_into_a_printed_count(rhinolike):
    """The defect this task uncovered. `Stampede` says "this card gains
    surge"; counting it as Surge reports an 86% surge rate for a deck
    whose printed rate is 25%. The two are reported apart and never
    summed, because the condition is the point of the card."""
    t = assess.profile(rhinolike,
                       assess.resolve(rhinolike, "rhino"))["treacheries"]
    assert t["copies"] == 4
    assert t["surge_copies"] == 1                       # Diabolical Discs
    assert t["conditional_surge_copies"] == 3           # Stampede x3
    assert t["surge_rate"] == pytest.approx(1 / 4)
    assert "surge_total" not in t


def test_fixed_threat_is_not_scaled_by_player_count(rhinolike):
    """§4.6: applying per-hero scaling to a fixed-threat scheme produces a
    wrong number in exactly the way printing raw villain HP did."""
    at_one = assess.profile(
        rhinolike, assess.resolve(rhinolike, "rhino", players=1))
    at_four = assess.profile(
        rhinolike, assess.resolve(rhinolike, "rhino", players=4))
    assert at_one["side_schemes"]["threat_total"] == 2 + 2
    assert at_four["side_schemes"]["threat_total"] == 2 + 2 * 4


def test_every_number_can_name_its_cards(rhinolike):
    """§8: so the model can cite rather than assert."""
    got = assess.profile(rhinolike, assess.resolve(rhinolike, "rhino"))
    assert got["by_type"]["treachery"]["cards"]
    assert got["minions"]["cards"]
    assert got["side_schemes"]["cards"][0]["threat"]


@pytest.mark.integration
def test_rhino_sections_match_a_hand_count(real_index):
    """Rhino + Standard at 2 players, no modulars. The plan's expected
    numbers were derived from its own wrong deck size of 22 and are
    corrected here: treacheries are 14 copies, not 12.

    Minions: Hydra Mercenary x2 (Guard, 3 HP), Sandman (Toughness, 4 HP),
    Shocker (3 HP). Side schemes: Breakin' & Takin' 2 fixed, Crowd Control
    2 per hero -> 2 + 4 at two players.
    """
    p = assess.profile(
        real_index, assess.resolve(real_index, "rhino", modular=[],
                                   players=2))
    assert p["deck_size"] == 24
    assert p["minions"]["copies"] == 4
    assert p["minions"]["health"] == {"min": 3, "max": 4}
    assert p["minions"]["keywords"] == {"guard": 2, "toughness": 1}
    assert p["treacheries"]["copies"] == 14
    assert p["side_schemes"]["threat_total"] == 6


@pytest.mark.integration
def test_rhino_prints_no_surge_at_all(real_index):
    """The measurement that made this task worth doing. Every Rhino and
    Standard treachery reads "this card gains surge" - conditional. The
    naive keyword match reported 12 of 14 copies as Surge; the deck's
    printed surge rate is zero."""
    t = assess.profile(
        real_index,
        assess.resolve(real_index, "rhino", modular=[]))["treacheries"]
    assert t["surge_copies"] == 0
    assert t["conditional_surge_copies"] == 12
    assert t["surge_rate"] == 0.0


@pytest.mark.integration
def test_printed_keywords_stay_a_minority_of_surge_mentions(real_index):
    """Corpus-wide gate on the rule itself, not on one scenario. If a
    change makes these two converge, the printed/granted split has
    stopped discriminating and every keyword number is suspect.

    Measured 2026-08-27 over deck-role cards: 261 mentions, 80 printed.
    `piercing`, `overkill` and `ranged` are printed by NO encounter-deck
    card - every instance grants the keyword to an attack - which is why
    a zero there is a fact rather than a broken rule.
    """
    rows = {r["keyword"]: (r["mentions"], r["printed"])
            for r in real_index.execute(
                "SELECT k.keyword, COUNT(*) mentions, SUM(k.printed) printed "
                "FROM card_keywords k JOIN encounter_role e ON e.code = k.code "
                "WHERE e.role = 'deck' GROUP BY 1")}
    assert rows["surge"] == (261, 80)
    for word in ("piercing", "overkill", "ranged"):
        assert rows[word][1] == 0, (word, rows[word])
    assert rows["permanent"][0] == rows["permanent"][1]


# --- growing decks (plan Task 8, spec §14.9) -------------------------

def test_a_growing_scenario_reports_the_opening_and_grown_decks(tmp_path):
    """The Hood, Mojo and Dark Beast add modular sets DURING play. One
    profile is the wrong answer for most of the game, so report both
    ends."""
    c = _mkdb(
        tmp_path,
        sets=[("dark_beast", "Dark Beast", "villain"),
              ("blue_moon", "Blue Moon", "modular"),
              ("standard", "Standard", "standard")],
        cards=[("m1", "A Scheme", "main_scheme", "dark_beast", 1, None, "",
                "", None, 0),
               ("t1", "Thing", "treachery", "dark_beast", 2, 1, "", "", None,
                0),
               ("p1", "Extra", "treachery", "blue_moon", 4, 3, "", "", None,
                0)],
        roles=[("m1", "starts_in_play", 0), ("t1", "deck", 1),
               ("p1", "deck", 1)],
        modulars=[("dark_beast", "prescribed", None)])
    s = assess.resolve(c, "dark_beast")
    s.pool = ["blue_moon"]
    steps = assess.trajectory(c, s)
    assert [x["added"] for x in steps] == [0, 1]
    assert steps[0]["deck_size"] == 2
    assert steps[1]["deck_size"] == 6


def test_a_fixed_scenario_reports_one_step(rhinolike):
    steps = assess.trajectory(rhinolike, assess.resolve(rhinolike, "rhino"))
    assert len(steps) == 1
    assert steps[0]["added"] == 0


def test_the_pool_is_read_from_config(tmp_path):
    c = _mkdb(
        tmp_path,
        sets=[("dark_beast", "Dark Beast", "villain"),
              ("blue_moon", "Blue Moon", "modular"),
              ("genosha", "Genosha", "modular"),
              ("savage_land", "Savage Land", "modular"),
              ("standard", "Standard", "standard")],
        cards=[("m1", "A Scheme", "main_scheme", "dark_beast", 1, None, "",
                "", None, 0)],
        roles=[("m1", "starts_in_play", 0)],
        modulars=[("dark_beast", "prescribed", None)])
    s = assess.resolve(c, "dark_beast")
    assert s.pool == ["blue_moon", "genosha", "savage_land"]
    assert s.growth == "random"


def test_the_hood_refuses_rather_than_assessing_an_empty_pool(tmp_path):
    """Its seven sets come from the whole collection and nothing can infer
    them. Assessing it against no pool would report a deck the player
    never faces."""
    c = _mkdb(
        tmp_path,
        sets=[("the_hood", "The Hood", "villain"),
              ("standard", "Standard", "standard")],
        cards=[("m1", "A Scheme", "main_scheme", "the_hood", 1, None, "", "",
                None, 0)],
        roles=[("m1", "starts_in_play", 0)],
        modulars=[("the_hood", "open", None)])
    with pytest.raises(assess.UnknownScenario, match="--modular"):
        assess.resolve(c, "the_hood")
    # Naming the sets on the table is enough.
    s = assess.resolve(c, "the_hood", modular=[])
    assert s.growth == "player_chosen"


@pytest.mark.integration
def test_every_growing_scenario_is_examined(real_index):
    """The reverse gate. §14.9 named three scenarios; the corpus has six
    cards that shuffle a SET into the encounter deck mid-game, and the
    other three had to be read and classified. A seventh appearing
    unexamined means a scenario is being reported as a fixed deck when it
    is not."""
    assert assess.growth_gate(real_index) == []


@pytest.mark.integration
def test_dark_beast_grows_by_three_environment_sets(real_index):
    s = assess.resolve(real_index, "dark_beast")
    assert s.pool == ["blue_moon", "genosha", "savage_land"]
    steps = assess.trajectory(real_index, s)
    assert [x["added"] for x in steps] == [0, 3]
    assert steps[1]["deck_size"] > steps[0]["deck_size"]
