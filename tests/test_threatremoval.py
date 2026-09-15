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


# --- which form can use it --------------------------------------------

@pytest.mark.parametrize("text,form", [
    ("<b>Hero Action</b> <i>(thwart)</i>: Remove 3 threat from a scheme.",
     "hero"),
    ("<b>Alter-Ego Action</b>: Exhaust this support → remove 2 threat.",
     "alter_ego"),
    ("<b>Action</b> <i>(thwart)</i>: Remove 2 threat from a scheme.",
     "either"),
    ("<b>Hero Action</b>: Remove 1 threat.\n<b>Alter-Ego Action</b>: "
     "Remove 2 threat.", "either"),
    ("<b>Hero Action</b> <i>(attack)</i>: Deal 3 damage.\n<b>Alter-Ego "
     "Action</b>: Remove 2 threat from a scheme.", "alter_ego"),
    ("<b>Hero Action</b> <i>(attack)</i>: Deal 3 damage.", None),
])
def test_removal_is_labelled_with_the_form_that_can_use_it(text, form):
    """RR p.4: a trigger naming Hero or Alter-Ego works only in that form.
    Daredevil's deck removes threat from alter-ego, which a THW 1 stat
    line hid from the live test."""
    assert threatremoval.removal_form(text) == form


def test_a_trigger_on_removing_the_last_threat_is_not_removal():
    """Acute Tactility reacts to the last threat leaving a scheme and
    removes none itself; it was counted as removal."""
    assert not threatremoval.removes_threat(
        "<b>Interrupt</b>: When you remove the last threat here, discard "
        "this → draw a card.")
    assert not threatremoval.removes_threat(
        "<b>Response</b>: After a thwart removes all threat there, heal 1.")
    assert threatremoval.removes_threat(
        "<b>Hero Action</b> <i>(thwart)</i>: Remove 3 threat. If this "
        "removes the last threat there, draw 1 card.")


# --- side decks --------------------------------------------------------

def test_every_side_deck_belongs_to_a_hero_this_index_has(real_index):
    orphans = [r[0] for r in real_index.execute(
        "SELECT code FROM sets WHERE card_set_type_code = 'hero_special' "
        "AND parent_code NOT IN (SELECT DISTINCT set_code FROM cards "
        "  WHERE type_code = 'hero' AND set_code IS NOT NULL)")]
    assert not orphans, orphans
    assert real_index.execute(
        "SELECT COUNT(*) FROM sets WHERE card_set_type_code = 'hero_special'"
    ).fetchone()[0] >= 6


def test_daredevils_sense_deck_is_reported_outside_his_deck(real_index):
    """The live test: a Protection Daredevil deck read as weak at
    thwarting, with the Sense deck and his alter-ego removal unseen."""
    deck = deckfetch.normalise(real_index, {
        "id": 1233874, "name": "D", "hero_code": "60001a",
        "hero_name": "Daredevil", "meta": '{"aspect":"protection"}',
        "ignoreDeckLimitSlots": None,
        "slots": {"01079": 2, "01081": 1, "01088": 1, "01089": 1, "01090": 1,
                  "09020": 1, "10031": 1, "16016": 1, "16017": 3, "16024": 1,
                  "32014": 2, "40020": 1, "42017": 1, "48014": 1, "48015": 2,
                  "56046": 1, "60007": 1, "60008": 2, "60009": 2, "60010": 2,
                  "60011": 1, "60012": 1, "60013": 1, "60014": 1, "60015": 1,
                  "60016": 1, "60017": 1, "60018": 1, "60030": 1, "60038": 1,
                  "60048": 3, "60052": 3}}, source="test")
    p = threatremoval.profile(real_index, deck)
    assert p["by_form"]["alter_ego"] == 3        # Deposition x2, Foggy Nelson
    [sense] = p["side_decks"]
    assert sense["name"] == "Sense Deck"
    assert len(sense["cards"]) == 5
    assert sum(sense["removal"].values()) == 1   # Superior Taste only
    assert not any(c["code"] in {s["code"] for s in sense["cards"]}
                   for c in p["designated_thwart"]["cards"]
                   + p["non_thwart_removal"]["cards"])


def test_identity_lists_the_side_deck_and_accepts_a_code(real_index):
    from mc_jarvis import cards

    got = cards.identity(real_index, "60001a")
    assert got["identity"] == "Daredevil"
    assert [sd["name"] for sd in got["side_decks"]] == ["Sense Deck"]
    assert cards.identity(real_index, "Spider-Man")["side_decks"] == []
