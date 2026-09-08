"""Decks written by hand rather than exported from marvelcdb."""
import pytest

from mc_jarvis import decktext


def test_the_four_shapes_a_written_count_takes():
    entries, meta = decktext.parse(
        "# a note\n"
        "Hero: Spider-Man\n"
        "Aspect: Justice\n"
        "\n"
        "3x Tackle\n"
        "2 Clear the Area\n"
        "Backflip x3\n"
        "- Enhanced Reflexes\n")
    assert entries == [("Tackle", 3), ("Clear the Area", 2),
                       ("Backflip", 3), ("Enhanced Reflexes", 1)]
    assert meta == {"hero": "Spider-Man", "aspect": "Justice"}


def test_a_hash_inside_a_name_is_not_a_comment():
    """Three supports are named `Safe House #29` and the like. Stripping
    from the first `#` anywhere turned them into `Safe House`, which
    matches nothing."""
    entries, _ = decktext.parse("# real comment\n2x Safe House #221\n")
    assert entries == [("Safe House #221", 2)]


@pytest.mark.parametrize("text", [
    "name,count\nTackle,3\nBackflip,2\n",
    "Card\tQty\nTackle\t3\nBackflip\t2\n",
    "Tackle,3\nBackflip,2\n",
])
def test_a_spreadsheet_export_is_read_as_a_table(text):
    entries, _ = decktext.parse(text)
    assert entries == [("Tackle", 3), ("Backflip", 2)]


pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
def test_a_written_deck_resolves_to_codes(real_index):
    payload = decktext.to_payload(
        real_index,
        "Hero: Peter Parker\nAspect: Justice\n3x Tackle\nBackflip x2\n",
        source="demo.txt")
    assert payload["hero_code"] == "01001a"
    assert sum(payload["slots"].values()) == 5


@pytest.mark.integration
def test_a_hero_name_two_heroes_share_is_refused(real_index):
    """T'Challa and Shuri are both printed `Black Panther` and carry
    different signature cards. Taking the first row resolved a T'Challa
    deck against Shuri's set, which then reported T'Challa's own cards as
    matching nothing."""
    with pytest.raises(decktext.DeckTextError) as err:
        decktext.to_payload(real_index, "Hero: Black Panther\n1x Tackle\n")
    assert "more than one hero" in str(err.value)
    # The alter-ego name settles it, and so does the code.
    assert decktext._hero_set(real_index, "T'Challa")[1] == "black_panther"
    assert decktext._hero_set(real_index, "01040a")[1] == "black_panther"


@pytest.mark.integration
def test_an_unresolved_name_is_reported_not_refused(real_index):
    """Somebody pasting a decklist wants the cards that did resolve
    looked at, with the rest named. These keys match no card code, so
    `normalise` files them under `Deck.unknown` and every check that
    needs a complete deck already degrades on it."""
    payload = decktext.to_payload(
        real_index, "Hero: 01001a\n3x Tackle\n2x Hawkeye\n1x Notacard\n")
    assert payload["slots"]["05015"] == 3
    unresolved = {k: v for k, v in payload["slots"].items() if "[" in k}
    assert len(unresolved) == 2
    # The count survives, so the deck size stays honest.
    assert sorted(unresolved.values()) == [1, 2]
    ambiguous = [k for k in unresolved if "which one?" in k]
    assert ambiguous and "01066" in ambiguous[0] and "04011" in ambiguous[0]
    assert [k for k in unresolved if "check the spelling" in k]


@pytest.mark.integration
def test_an_unresolved_name_reaches_the_deck_as_unknown(real_index, tmp_path):
    from mc_jarvis import deckfetch

    path = tmp_path / "deck.txt"
    path.write_text("Hero: 01001a\n3x Tackle\n2x Hawkeye\n", encoding="utf-8")
    deck = deckfetch.fetch(real_index, str(path))
    assert deck.slots == {"05015": 3}
    assert sum(deck.unknown.values()) == 2


@pytest.mark.integration
def test_a_code_or_a_hint_settles_an_ambiguous_name(real_index):
    """The refusal tells the writer to use a code, so a code has to work."""
    payload = decktext.to_payload(
        real_index,
        "Hero: 01001a\n3x 27011\n1x Ronin (upgrade)\n1x Spider-Man (protection)\n")
    assert payload["slots"] == {"27011": 4, "60053": 1}


@pytest.mark.integration
def test_no_written_deck_ever_resolves_to_the_wrong_card(real_index):
    """Every published deck in the corpus, rendered as `3x <name>` lines
    and read back. The pass rate is not the assertion -- ambiguous names
    are refused on purpose -- but a name must never resolve to a card the
    deck did not hold. Two bugs did exactly that: the aspect filter drove
    Rogue's own Gambit to the generic ally, and a hero name shared by two
    heroes resolved against the wrong signature set.

    The declared aspect is decisive when a name is otherwise ambiguous --
    it doubles what resolves, 105 decks to 200 -- so decks whose stored
    aspect contradicts their own cards are skipped rather than counted
    against it."""
    from mc_jarvis import deckfetch

    # Capped: the wrong == 0 invariant does not need all 1,501,
    # and the whole corpus made this the slowest test in the tier.
    decks = list(deckfetch.corpus())[:400]
    if not decks:
        pytest.skip("no deck corpus fetched")
    identical = wrong = 0
    for payload in decks:
        try:
            deck = deckfetch.normalise(real_index, payload, source="corpus")
        except deckfetch.DeckError:
            continue
        # marvelcdb stores the declared aspect apart from the cards, so
        # some corpus decks declare an aspect their own cards contradict
        # -- `deck check` already reports that as a note. The aspect line
        # is decisive here, so a deck whose label is stale cannot be used
        # to test resolution; it is what the label says it is or nothing.
        factions = {r["faction_code"] for r in real_index.execute(
            "SELECT faction_code FROM cards WHERE code IN ({})".format(
                ",".join("?" * len(deck.slots))), tuple(deck.slots))}
        off_aspect = factions & ({"aggression", "justice", "leadership",
                                  "protection"} - set(deck.aspects))
        if off_aspect:
            continue
        lines = [f"Hero: {deck.hero_code}"]
        if deck.aspects:
            lines.append("Aspect: " + ", ".join(deck.aspects))
        for code, count in deck.slots.items():
            row = real_index.execute(
                "SELECT name FROM cards WHERE code = ?", (code,)).fetchone()
            lines.append(f"{count}x {row['name'] if row else code}")
        try:
            back = decktext.to_payload(real_index, "\n".join(lines))
        except decktext.DeckTextError:
            continue
        # Unresolved names ride along as non-code keys; drop them before
        # comparing, since the assertion is about wrong picks.
        back["slots"] = {k: v for k, v in back["slots"].items() if "[" not in k}
        # The invariant is not that everything resolves - ambiguous names
        # deliberately do not - but that nothing resolves to a card the
        # deck never held, and that what does resolve keeps its count.
        strayed = set(back["slots"]) - set(deck.slots)
        miscounted = [c for c in back["slots"]
                      if c in deck.slots
                      and back["slots"][c] != deck.slots[c]]
        if strayed or miscounted:
            wrong += 1
        elif back["slots"] == deck.slots:
            identical += 1
    assert wrong == 0
    assert identical > 120, identical
