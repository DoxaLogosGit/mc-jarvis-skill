"""Threat removal capacity (assessment spec §9.2, item 1).

The section originally asked for "threat removal available per turn".
These tests pin the two reasons that number does not exist.
"""
import pytest

from mc_jarvis import deckfetch, index, threatremoval


def _mkdb(tmp_path, cards):
    """cards: (code, name, type, thwart, health, tcost, text)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, thwart, health, "
        "thwart_cost, text, faction_code, pack_code, set_code, "
        "canonical_code, is_reprint, deck_limit, quantity, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'justice', 'core', 'core', ?, 0, "
        "3, 3, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[0]) for c in cards])
    conn.commit()
    return conn


def _deck(slots, hero="h1"):
    return deckfetch.Deck(name="D", hero_code=hero, hero_name="H",
                          aspects=["justice"], slots=slots)


def test_a_compound_designator_still_designates_a_thwart():
    """`(attack/thwart)` is a thwart. A substring test on `(thwart)`
    misses six cards and miscounts Hit and Run (design §10.12)."""
    assert "thwart" in threatremoval.designations(
        "<b>Hero Action</b> <i>(attack/thwart)</i>: Deal 2 damage.")
    assert "thwart" in threatremoval.designations(
        "<i>(attack/defense/thwart)</i>")
    assert "thwart" not in threatremoval.designations("<i>(attack)</i>")


def test_the_ally_limit_caps_the_basic_thwart_ceiling(tmp_path):
    """Three allies in play is the cap (RR p.7), and 62% of 1,501
    published decks hold more than three. Counting the deck's allies
    instead of the fielded three overstates the ceiling 1.4x."""
    conn = _mkdb(tmp_path, [
        ("h1", "Hero", "hero", 2, 10, None, ""),
        ("a1", "A1", "ally", 3, 3, 1, ""), ("a2", "A2", "ally", 3, 3, 1, ""),
        ("a3", "A3", "ally", 2, 3, 1, ""), ("a4", "A4", "ally", 2, 3, 1, ""),
        ("a5", "A5", "ally", 1, 3, 1, "")])
    p = threatremoval.profile(
        conn, _deck({"a1": 1, "a2": 1, "a3": 1, "a4": 1, "a5": 1}))
    b = p["basic_thwart"]
    assert b["allies_in_deck"] == 5
    assert b["allies_fielded"] == 3
    # hero 2 + the three best allies (3+3+2), not all five (3+3+2+2+1).
    assert b["ceiling"] == 10


def test_designated_thwarts_do_not_compete_with_basic_thwarts(tmp_path):
    """RR p.44: resolving a `Hero Action (thwart)` does not exhaust the
    hero unless its text says so. These are additional instances, limited
    by resources rather than exhaustion, so they are reported apart from
    the exhaustion-limited ceiling rather than added into it."""
    conn = _mkdb(tmp_path, [
        ("h1", "Hero", "hero", 2, 10, None, ""),
        ("e1", "Event", "event", None, None, None,
         "<b>Hero Action</b> <i>(thwart)</i>: Remove 3 threat.")])
    p = threatremoval.profile(conn, _deck({"e1": 2}))
    assert p["designated_thwart"]["copies"] == 2
    assert p["basic_thwart"]["ceiling"] == 2      # unchanged by the event


def test_threat_removal_that_is_not_a_thwart_is_counted_apart(tmp_path):
    """It passes through Patrol, which forbids thwarting the main scheme
    and nothing else (design §10.12)."""
    conn = _mkdb(tmp_path, [
        ("h1", "Hero", "hero", 2, 10, None, ""),
        ("e1", "Bypass", "event", None, None, None,
         "<b>Hero Action</b>: Remove 2 threat from a scheme.")])
    p = threatremoval.profile(conn, _deck({"e1": 1}))
    assert p["non_thwart_removal"]["copies"] == 1
    assert p["designated_thwart"]["copies"] == 0


def test_an_exempt_ally_fields_in_addition_to_the_limit(tmp_path):
    """`Stinger`, the four New Recruits and the trickster_magic linked
    allies do not consume a slot, so a deck can field the limit *and*
    them. Counting them within the three understates the ceiling."""
    conn = _mkdb(tmp_path, [
        ("h1", "Hero", "hero", 2, 10, None, ""),
        ("a1", "A1", "ally", 3, 3, 1, ""), ("a2", "A2", "ally", 3, 3, 1, ""),
        ("a3", "A3", "ally", 3, 3, 1, ""), ("a4", "A4", "ally", 3, 3, 1, ""),
        ("x1", "Stinger", "ally", 2, 3, 1,
         "Stinger does not count against your ally limit.")])
    b = threatremoval.profile(
        conn, _deck({"a1": 1, "a2": 1, "a3": 1, "a4": 1, "x1": 1})
    )["basic_thwart"]
    assert [a["name"] for a in b["exempt_allies"]] == ["Stinger"]
    assert b["allies_fielded"] == 4          # three counted, plus Stinger
    assert b["ceiling"] == 2 + 3 + 3 + 3 + 2


def test_a_limit_raiser_is_named_and_never_applied(tmp_path):
    """All five raisers must be in play to do anything, and four of them
    also need a trait the deck may not have. Applying them to the ceiling
    would assert a board state the deck cannot promise."""
    conn = _mkdb(tmp_path, [
        ("h1", "Hero", "hero", 2, 10, None, ""),
        ("a1", "A1", "ally", 3, 3, 1, ""), ("a2", "A2", "ally", 3, 3, 1, ""),
        ("a3", "A3", "ally", 3, 3, 1, ""), ("a4", "A4", "ally", 3, 3, 1, ""),
        ("s1", "The Triskelion", "support", None, None, None,
         "Increase your ally limit by 1."),
        ("s2", "Utopia", "support", None, None, None,
         "If each of your allies has the [[X-MEN]] trait, increase your "
         "ally limit by 1.")])
    b = threatremoval.profile(
        conn, _deck({"a1": 1, "a2": 1, "a3": 1, "a4": 1, "s1": 1, "s2": 1})
    )["basic_thwart"]
    assert b["ceiling"] == 2 + 3 + 3 + 3      # still three allies
    named = {r["name"]: r["conditional"] for r in b["raises_limit"]}
    assert named == {"The Triskelion": False, "Utopia": True}
