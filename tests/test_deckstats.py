"""Deck shape (spec §10).

Reads `deckcheck.included` - the draw pile - never `deck.slots` and never
`deckbuilding_cards`. §10 requires it: a permanent upgrade left in the
cost curve describes a deck the player never shuffles.
"""
import pytest

from mc_jarvis import deckfetch, deckstats, index


def _mkdb(tmp_path, cards, out_of_deck=()):
    """cards: (code, name, type, cost, phys, mental, energy, wild, qty)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, cost, resource_physical, "
        "resource_mental, resource_energy, resource_wild, deck_limit, "
        "quantity, pack_code, set_code, canonical_code, is_reprint, raw, "
        "text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 3, ?, 'core', 'core', ?, 0, '{}', "
        "'')",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[0])
         for c in cards])
    conn.executemany(
        "INSERT INTO out_of_deck (code, mechanism, note) VALUES (?, ?, NULL)",
        out_of_deck)
    conn.commit()
    return conn


def _deck(**kw):
    base = {"name": "D", "hero_code": "h1", "hero_name": "H",
            "aspects": ["justice"], "slots": {}}
    base.update(kw)
    return deckfetch.Deck(**base)


def test_the_cost_curve_is_copy_weighted(tmp_path):
    """Three copies of a 1-cost card are three cards at cost 1, not one.
    A curve over distinct rows is not the curve the player draws from."""
    conn = _mkdb(tmp_path, [("a1", "Cheap", "ally", 1, 1, 0, 0, 0, 3),
                            ("a2", "Dear", "ally", 4, 0, 1, 0, 0, 2)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "a2": 2}))
    assert got["cost_curve"] == {1: 3, 4: 2}
    assert round(got["mean_cost"], 3) == round((3 * 1 + 2 * 4) / 5, 3)


def test_a_card_with_no_cost_is_not_a_card_costing_zero(tmp_path):
    """A null cost is the absence of a cost, not a cost of nothing.
    Resources and some upgrades have none, and folding them in as 0 drags
    the mean toward a number no card in the deck has."""
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3),
                            ("r1", "Resource", "resource", None,
                             0, 0, 0, 1, 3)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "r1": 3}))
    assert got["cost_curve"] == {2: 3}
    assert got["no_cost"] == 3
    assert round(got["mean_cost"], 3) == 2.0
    assert got["over"] == 3


def test_a_real_zero_cost_card_is_in_the_curve(tmp_path):
    """The other half of the rule: cost 0 is a cost, and belongs at 0."""
    conn = _mkdb(tmp_path, [("e1", "Free", "event", 0, 1, 0, 0, 0, 2)])
    got = deckstats.profile(conn, _deck(slots={"e1": 2}))
    assert got["cost_curve"] == {0: 2}
    assert got["no_cost"] == 0


def test_out_of_deck_cards_do_not_skew_the_curve(tmp_path):
    """§10 states it: the exclusions apply to `deck stats` as well as
    `deck check`. A permanent upgrade in the curve describes a deck the
    player never shuffles."""
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3),
                            ("p1", "Claws", "upgrade", 0, 0, 0, 0, 0, 1)],
                 out_of_deck=[("p1", "permanent")])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "p1": 1}))
    assert got["cost_curve"] == {2: 3}
    assert got["size"] == 3


def test_a_set_aside_card_is_out_of_the_curve_but_was_in_the_deck(tmp_path):
    """Touched counts toward the 40 (§10.3) and is still never drawn, so
    it belongs in `deckbuilding_cards` and not here. The two numbers
    disagreeing is correct, and the profile reports both so the
    difference is visible rather than puzzling."""
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3),
                            ("t1", "Touched", "upgrade", 1, 0, 0, 0, 0, 1)],
                 out_of_deck=[("t1", "config")])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "t1": 1}))
    assert got["size"] == 3
    assert got["deckbuilding_size"] == 4


def test_the_resource_mix_is_copy_weighted_too(tmp_path):
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3),
                            ("e1", "Ev", "event", 1, 0, 0, 0, 1, 2)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "e1": 2}))
    assert got["resources"] == {"physical": 3, "wild": 2}


def test_every_number_names_its_cards(tmp_path):
    """§8: so the model can cite rather than assert."""
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3}))
    assert got["by_type"]["ally"]["cards"] == [
        {"code": "a1", "name": "Ally", "quantity": 3}]


def test_an_empty_deck_reports_zeroes_rather_than_dividing_by_zero(tmp_path):
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3)])
    got = deckstats.profile(conn, _deck(slots={}))
    assert got["size"] == 0
    assert got["mean_cost"] == 0.0


@pytest.mark.integration
def test_a_real_deck_profiles_and_reconciles(real_index):
    """The gate. The curve must account for every card in the deck: a
    curve that does not reconcile with the size means the exclusion set
    differs between `check` and `stats`, which is the bug the shared
    `included` design exists to prevent."""
    deck = deckfetch.fetch(real_index, "64331")
    got = deckstats.profile(real_index, deck)
    assert got["size"] >= 40
    assert sum(got["cost_curve"].values()) + got["no_cost"] == got["size"]
    assert sum(v["copies"] for v in got["by_type"].values()) == got["size"]


@pytest.mark.integration
def test_every_corpus_deck_reconciles(real_index):
    """One deck could reconcile by luck. Every deck in the corpus is the
    real check on the arithmetic."""
    from mc_jarvis import deckfetch as df

    decks = list(df.corpus())
    if len(decks) < 200:
        pytest.skip("no corpus; run `uv run python tools/deck_corpus.py`")
    checked = 0
    for payload in decks[:400]:
        try:
            deck = df.normalise(real_index, payload, source="corpus")
        except df.DeckError:
            continue
        got = deckstats.profile(real_index, deck)
        assert sum(got["cost_curve"].values()) + got["no_cost"] == got["size"]
        assert got["deckbuilding_size"] >= got["size"]
        checked += 1
    assert checked > 300, checked


def test_linked_cards_are_named_but_not_counted(tmp_path):
    """They are set aside at setup, so they are in no curve - but a deck
    holding their enabler really does acquire them, and reporting nothing
    describes a game the player does not have."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", None, 0, 0, 0, 0, 1),
                  ("43021", "Specialized Training", "player_side_scheme",
                   None, 0, 0, 0, 0, 1),
                  ("43034", "Combat Specialist", "upgrade", 2,
                   1, 0, 0, 0, 1),
                  ("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3)],
                 out_of_deck=[("43034", "linked")])
    conn.execute("UPDATE cards SET text = 'Linked (Specialized Training).' "
                 "WHERE code = '43034'")
    conn.commit()
    got = deckstats.profile(conn, _deck(slots={"43021": 1, "a1": 3}))
    assert got["size"] == 4
    assert got["cost_curve"] == {2: 3}          # the upgrade is not in it
    assert got["arrives_later"] == [
        {"code": "43034", "name": "Combat Specialist",
         "via": "Specialized Training"}]
