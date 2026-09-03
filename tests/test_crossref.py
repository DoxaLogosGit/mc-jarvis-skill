"""Deck against scenario (assessment spec §9.2).

Each test pins a pairing that an earlier version got wrong.
"""
import pytest

from mc_jarvis import crossref, deckfetch, index


def _mkdb(tmp_path, cards, keywords=()):
    """cards: (code, name, type, set_code, text, quantity, accel)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, set_code, text, quantity, "
        "scheme_acceleration, faction_code, pack_code, canonical_code, "
        "is_reprint, deck_limit, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'encounter', 'core', ?, 0, 3, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[0]) for c in cards])
    conn.executemany(
        "INSERT INTO card_keywords (code, keyword, printed) VALUES (?, ?, ?)",
        keywords)
    conn.commit()
    return conn


def _deck(slots):
    return deckfetch.Deck(name="D", hero_code="h1", hero_name="H",
                          aspects=["justice"], slots=slots)


def test_a_villain_stage_is_not_an_encounter_deck_row(tmp_path):
    """`assess.deck_cards` returns the encounter deck, which never holds
    the villain. Reading only that list reported zero villain retaliate
    for Zola, who prints Retaliate 1 on all three stages."""
    conn = _mkdb(
        tmp_path,
        [("v1", "Zola", "villain", "zola", "Retaliate 1.", 1, None)],
        keywords=[("v1", "retaliate", 1)])
    # The villain is absent from `cards` and supplied only via `sets`.
    out = crossref.pairings(conn, [], _deck({}), sets=["zola"])
    assert out["retaliate"]["scenario_sources"]["villain"] == 1


def test_a_granted_keyword_is_not_a_printed_one(tmp_path):
    """`Jennix` reads "each Inheritor minion gains guard" and prints no
    keyword. Counting the substring made four hand counts too high and one
    scenario table wrong by two thirds (design §10.14)."""
    conn = _mkdb(
        tmp_path,
        [("m1", "Jennix", "minion", "s1",
          "Each [[Inheritor]] minion gains guard.", 1, None)],
        keywords=[("m1", "guard", 0)])
    cards = [{"code": "m1", "name": "Jennix", "type_code": "minion",
              "quantity": 1, "text": "Each [[Inheritor]] minion gains guard."}]
    got = crossref.scenario_keyword(conn, cards, "guard")
    assert got["total"] == 0
    # But it is surfaced, because it arms every minion in the set.
    assert [c["name"] for c in got["global_grants"]] == ["Jennix"]


def test_an_unconditional_self_grant_is_a_reliable_source(tmp_path):
    """`Star-Lord` never prints ranged, yet his attacks always have it.
    Consuming `printed` for the deck side would report zero sources for a
    deck holding him (design §10.11)."""
    conn = _mkdb(tmp_path, [
        ("a1", "Star-Lord", "ally", None,
         "[star] Star-Lord's attacks gain ranged.", 1, None),
        ("a2", "Marvel Boy", "ally", None,
         "<b>Interrupt</b>: When Marvel Boy attacks, spend a resource "
         "→ this attack gains ranged.", 1, None)])
    got = crossref.deck_keyword(conn, {"a1": 1, "a2": 1}, "ranged")
    assert [e["name"] for e in got["always"]] == ["Star-Lord"]
    assert [e["name"] for e in got["per_use"]] == ["Marvel Boy"]


def test_damage_that_needs_an_attack_does_not_bypass_guard(tmp_path):
    """Guard forbids using any card you control to attack the villain, so
    a Forced Response that triggers off attacking is blocked with it."""
    conn = _mkdb(tmp_path, [
        ("c1", "Bellerophon", "upgrade", None,
         "<b>Action</b>: Exhaust this → deal 3 damage to the villain.",
         1, None),
        ("c2", "Hulk", "ally", None,
         "<b>Forced Response</b>: After Hulk attacks, deal 2 damage to an "
         "enemy.", 1, None)])
    got = crossref.bypasses(conn, {"c1": 1, "c2": 1})
    assert [e["name"] for e in got["guard"]] == ["Bellerophon"]
    assert [e["name"] for e in got["attack_contingent"]] == ["Hulk"]


def test_a_keyword_granted_in_a_list_is_still_granted(tmp_path):
    """`Marvel Boy` reads "this attack gains piercing and ranged", so the
    keyword does not follow `gains` directly. Requiring it to left six
    real grants classified as mentioning the keyword without giving it."""
    conn = _mkdb(tmp_path, [
        ("c1", "Marvel Boy", "ally", None,
         "<b>Interrupt</b>: When Marvel Boy attacks, spend a resource → "
         "this attack gains piercing and ranged.", 1, None),
        ("c2", "Sharpshooter", "upgrade", None,
         "<b>Hero Interrupt</b>: When you make a ranged attack, discard "
         "the top card of your deck.", 1, None)])
    got = crossref.deck_keyword(conn, {"c1": 1, "c2": 1}, "ranged")
    assert [e["name"] for e in got["per_use"]] == ["Marvel Boy"]
    # Sharpshooter pays off a ranged attack; it grants nothing.
    assert [e["name"] for e in got["mentions_only"]] == ["Sharpshooter"]
