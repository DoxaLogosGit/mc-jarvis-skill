"""Deck import (spec §10, corrected by §10.1).

The API shapes asserted here were measured on 2026-08-27 across 124
published decks from five `by_date` days. Three of them differ from what
§10 records, and each difference is named where it bites.
"""
import pytest

from mc_jarvis import deckfetch, index


def _mkdb(tmp_path, cards):
    """cards: (code, name, type_code, pack_code, duplicate_of)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, pack_code, duplicate_of, "
        "canonical_code, is_reprint, raw) VALUES (?, ?, ?, ?, ?, ?, ?, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[4] or c[0], int(bool(c[4])))
         for c in cards])
    conn.commit()
    return conn


def test_meta_parses_from_a_json_string():
    """Measured: `meta` is a JSON string on all 124 sampled decks. §10 warns
    it is an already-decoded object on other endpoints, so both must work."""
    assert deckfetch.parse_meta('{"aspect":"justice"}') == {
        "aspect": "justice"}
    assert deckfetch.parse_meta({"aspect": "justice"}) == {
        "aspect": "justice"}


def test_meta_that_is_absent_or_junk_is_empty_not_fatal():
    """The corpus is thousands of user-authored decks; one malformed field
    must not end the run."""
    for raw in (None, "", "   ", "not json", "[1,2]", 7):
        assert deckfetch.parse_meta(raw) == {}, raw


def test_format_is_read_from_meta_and_absent_means_current():
    """§10 puts `format` at the top level; measured, it is inside `meta`
    and absent on 118 of 124 decks. Reading absence as "unknown" would
    exclude 95% of the regression corpus."""
    assert deckfetch.parse_meta('{"aspect":"justice"}').get("format") is None


def test_both_aspects_are_carried(tmp_path):
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "Spider-Man",
        "meta": '{"aspect":"justice","aspect2":"leadership"}', "slots": {}},
        source="test")
    assert deck.aspects == ["justice", "leadership"]
    assert deck.deck_format == "current"


def test_a_declared_legacy_format_is_carried(tmp_path):
    """5 of 124 sampled decks are `legacy`. The corpus filters on this."""
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": '{"aspect":"justice","format":"legacy"}', "slots": {}},
        source="test")
    assert deck.deck_format == "legacy"


def test_a_reprinted_slot_resolves_to_its_canonical_card(tmp_path):
    """§10.1: 337 player cards are reprints. A deck names whichever
    printing its builder owned, so two decks holding the same card can
    name different codes."""
    conn = _mkdb(tmp_path, [
        ("01001a", "Spider-Man", "hero", "core", None),
        ("27047", "Dum Dum Dugan", "ally", "sm", None),
        ("50021", "Dum Dum Dugan", "ally", "aos", "27047")])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": '{"aspect":"justice"}', "slots": {"50021": 1}},
        source="test")
    assert deck.slots == {"27047": 1}


def test_two_printings_of_one_card_are_added_not_listed_twice(tmp_path):
    conn = _mkdb(tmp_path, [
        ("01001a", "Spider-Man", "hero", "core", None),
        ("27047", "Dum Dum Dugan", "ally", "sm", None),
        ("50021", "Dum Dum Dugan", "ally", "aos", "27047")])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": "{}", "slots": {"27047": 1, "50021": 1}}, source="test")
    assert deck.slots == {"27047": 2}


def test_a_slot_the_index_does_not_carry_is_reported_not_dropped(tmp_path):
    """§10.1: coverage is bounded by marvelcdb, exactly as it is for
    scenarios. Dropping the slot yields a deck that fails a size check for
    a reason the player cannot see."""
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": "{}", "slots": {"99999": 3}}, source="test")
    assert deck.slots == {}
    assert deck.unknown == {"99999": 3}


def test_an_unknown_hero_is_an_error_not_a_silent_deck(tmp_path):
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    with pytest.raises(deckfetch.DeckError, match="99999a"):
        deckfetch.normalise(conn, {
            "id": 1, "name": "D", "hero_code": "99999a", "hero_name": "?",
            "meta": "{}", "slots": {}}, source="test")


def test_ignore_deck_limit_slots_survives_being_null(tmp_path):
    """Present on every observed deck and null on all 124 of them."""
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": "{}", "slots": {}, "ignoreDeckLimitSlots": None},
        source="test")
    assert deck.ignore_limit == {}


@pytest.mark.parametrize("ref,want", [
    ("64331", "64331"),
    ("https://marvelcdb.com/decklist/view/64331/nova-justice", "64331"),
    ("https://marvelcdb.com/decklist/view/64331", "64331"),
])
def test_a_deck_id_is_recognised_in_any_of_its_forms(ref, want):
    assert deckfetch.deck_id(ref) == want


def test_a_local_file_is_not_mistaken_for_an_id(tmp_path):
    path = tmp_path / "deck.json"
    path.write_text("{}", encoding="utf-8")
    assert deckfetch.deck_id(str(path)) is None


# --- gates against the live API --------------------------------------

@pytest.mark.integration
def test_the_live_api_still_has_the_shape_this_module_assumes(real_index):
    """Every assumption in this module, re-checked against the live site.

    If this fails, read the payload before changing the parser: a field
    that moved is a finding, not a bug to route around. §10 recorded
    `format` at the top level and it is in `meta`, which is exactly the
    kind of drift this catches.
    """
    decks = deckfetch.fetch_by_date("2026-08-01")
    assert len(decks) > 5, len(decks)

    required = {"id", "name", "hero_code", "hero_name", "slots", "meta",
                "ignoreDeckLimitSlots"}
    for deck in decks:
        assert required <= set(deck), sorted(required - set(deck))
        # A top-level `format` is what §10 claimed; it lives in `meta`.
        assert "format" not in deck

    metas = [deckfetch.parse_meta(d["meta"]) for d in decks]
    assert all("aspect" in m for m in metas)
    assert all(m.get("format") in (None, "legacy", "current") for m in metas)


@pytest.mark.integration
def test_real_decks_normalise_without_a_flood_of_unknown_slots(real_index):
    """An unknown slot means marvelsdb is behind marvelcdb. A few are
    expected after a new release; a flood means the card data is stale."""
    parsed = []
    for payload in deckfetch.fetch_by_date("2026-08-01"):
        try:
            parsed.append(deckfetch.normalise(real_index, payload,
                                              source="gate"))
        except deckfetch.DeckError:
            continue
    assert parsed, "no deck from that day resolved at all"
    missing = sum(len(d.unknown) for d in parsed)
    assert missing <= len(parsed), (
        f"{missing} unknown slots across {len(parsed)} decks - the card "
        f"data is probably stale; run `mc-jarvis update`")


@pytest.mark.integration
def test_a_real_deck_fetches_by_id(real_index):
    deck = deckfetch.fetch(real_index, "64331")
    assert deck.hero_name
    assert sum(deck.slots.values()) >= 40


def test_a_non_json_response_is_a_clear_error_not_a_traceback(monkeypatch):
    """marvelcdb answers an unknown deck id with a NON-JSON body rather
    than a 404, so `json.loads` raises where an `OSError` handler never
    sees it. `mc-jarvis deck check 99999999` printed a traceback."""
    monkeypatch.setattr(deckfetch, "_get", deckfetch._get)
    import urllib.request

    class _Fake:
        def read(self):
            return b"<html>not a deck</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Fake())
    with pytest.raises(deckfetch.DeckError, match="does not exist"):
        deckfetch._get("https://marvelcdb.com/api/public/decklist/99999999")


def test_an_unreachable_host_is_a_clear_error_too(monkeypatch):
    import urllib.request

    def _boom(*a, **k):
        raise OSError("Name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(deckfetch.DeckError, match="cannot reach marvelcdb"):
        deckfetch._get("https://marvelcdb.com/api/public/decklist/1")
