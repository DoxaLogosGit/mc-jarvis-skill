"""What an ally costs to use (spec §10.6, §10.7).

Every case here is a card that broke an earlier version of this module.
"""
import pytest

from mc_jarvis import allycost, index


def _mkdb(tmp_path, allies):
    """allies: (code, name, thw, tcost, atk, acost, hp, text, hazard)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, thwart, thwart_cost, "
        "attack, attack_cost, health, text, scheme_hazard, faction_code, "
        "pack_code, set_code, canonical_code, is_reprint, raw) "
        "VALUES (?, ?, 'ally', ?, ?, ?, ?, ?, ?, ?, 'basic', 'core', "
        "'core', ?, 0, '{}')",
        [(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[0])
         for a in allies])
    conn.commit()
    return conn


def test_the_ally_resolves_its_power_before_taking_the_damage():
    """Dum Dum Dugan has 5 hit points and pays 3 to thwart, so he thwarts
    twice: the second thwart resolves, then the damage defeats him. A
    floor would say once and lose half his contribution."""
    assert allycost.uses(5, 3) == 2
    assert allycost.uses(2, 1) == 2
    assert allycost.uses(3, 2) == 2


def test_a_null_cost_is_not_a_cost_of_one():
    """11 player-legal allies have no `*_cost` upstream. Defaulting to
    the common value would price Cloak and every Deadpool ally wrong with
    nothing downstream able to detect it."""
    assert allycost.uses(3, None) is None
    assert allycost.uses(None, 1) is None


def test_a_printed_zero_is_a_value_and_not_a_gap():
    """Spider-Ham stores a real 0 on both stats. Treating it as missing
    would suppress a bound that genuinely has no limit; treating it as 1
    would invent one. It also must not divide by zero."""
    assert allycost.uses(3, 0) == float("inf")


def test_the_enemy_pronoun_is_not_the_ally():
    """Iron Fist's ability deals 1 damage to the enemy he attacks. An
    earlier pronoun group included `it` and made him look self-damaging."""
    assert "self-damage" not in allycost.markers(
        "Iron Fist", "When Iron Fist attacks an enemy, remove 1 mystic "
                     "counter from him -> stun that enemy and deal 1 damage "
                     "to it.")


def test_an_ally_is_named_by_its_first_word_in_its_own_text():
    """`Bob, Agent of Hydra` is called `Bob` on his own card."""
    assert "self-damage" in allycost.markers(
        "Bob, Agent of Hydra", "deal 1 damage to Bob")


def test_a_cost_paid_in_resources_is_still_a_cost(tmp_path):
    """Blade is why `cost-unknown` never means `nothing to read`. He has
    no consequential damage icons because his price is a resource on every
    use -- and his text contains none of the words the other markers look
    for, so without `per-use-cost` he would look free."""
    marks = allycost.markers(
        "Blade", "<b>Forced Response</b>: After Blade thwarts or attacks, "
                 "choose to either spend a [physical] resource from your "
                 "hand or discard Blade.")
    assert "per-use-cost" in marks


def test_leaving_play_is_not_the_same_as_paying_to_act():
    """Goliath discards himself at end of phase and Angela if her search
    finds no minion. Neither is a per-use cost, and hit points never
    governed how long either stays."""
    assert allycost.markers(
        "Goliath", "<b>Action</b>: Goliath gets +4 ATK until the end of the "
                   "phase. At the end of the phase, discard Goliath.") == \
        frozenset({"self-discard"})


def test_the_two_bounds_are_reported_separately(tmp_path):
    """Dum Dum Dugan pays 3 to thwart and 2 to attack, so he thwarts twice
    and attacks three times. One lifetime number would have to pick one."""
    conn = _mkdb(tmp_path, [
        ("a1", "Dum Dum Dugan", 3, 3, 3, 2, 5, "", None)])
    row = allycost.ally_rows(conn, ["a1"])[0]
    assert row["thwarting"] == {"uses": 2, "total": 6}
    assert row["attacking"] == {"uses": 3, "total": 9}


def test_an_unpriced_ally_reports_no_bound_rather_than_a_guess(tmp_path):
    conn = _mkdb(tmp_path, [("a1", "Cloak", 2, None, 1, None, 2, "", None)])
    row = allycost.ally_rows(conn, ["a1"])[0]
    assert row["thwarting"]["uses"] is None
    assert allycost.UNKNOWN in row["markers"]


def test_an_encounter_icon_is_a_cost_the_output_never_nets_off(tmp_path):
    """Venom (basic) has the pool's highest thwart bound and a hazard
    icon: every round he stays in play costs an extra encounter card."""
    conn = _mkdb(tmp_path, [("a1", "Venom", 2, 1, 3, 2, 6, "", 1)])
    row = allycost.ally_rows(conn, ["a1"])[0]
    assert row["thwarting"]["total"] == 12
    assert row["icons"] == {"hazard": 1}


def test_the_two_ceilings_are_alternatives_and_are_never_added(tmp_path):
    """An ally spends one pool of hit points across thwarting, attacking
    and blocking. A combined total would double-spend every hit point.

    These are lifetime totals and carry no ally limit: the cap of three
    applies to allies in play, and `threatremoval` is where it belongs."""
    conn = _mkdb(tmp_path, [("a1", "A", 2, 1, 2, 1, 4, "", None)])
    t = allycost.totals(allycost.ally_rows(conn, ["a1"]))
    assert t["thwart_lifetime"] == 8
    assert t["attack_lifetime"] == 8
    assert "total_lifetime" not in t
