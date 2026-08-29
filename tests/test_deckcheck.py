"""Deck legality (spec §10, §10.1, §10.2)."""
import pytest

from mc_jarvis import deckcheck, deckfetch, index


def _mkdb(tmp_path, cards, out_of_deck=()):
    """cards: (code, name, type_code, pack, deck_limit, quantity)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, pack_code, deck_limit, "
        "quantity, set_code, canonical_code, is_reprint, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[3], c[0]) for c in cards])
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


SIZE_CONFIG = {"deck_rules": {"minimum_size": 40, "rr_entry": "Deck"}}


# --- exclusion -------------------------------------------------------

def test_a_permanent_card_is_not_in_the_deck(tmp_path):
    """A permanent upgrade left in the count inflates deck size and skews
    every curve of a deck it was never part of."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("c1", "Wolverine's Claws", "upgrade", "core", 1, 1),
                  ("c2", "Aid", "ally", "core", 3, 3)],
                 out_of_deck=[("c1", "permanent")])
    deck = _deck(slots={"c1": 1, "c2": 3})
    assert deckcheck.included(conn, deck) == {"c2": 3}
    assert deckcheck.excluded(conn, deck) == {"c1": "permanent"}


def test_a_card_the_data_does_not_mark_is_excluded_by_config(tmp_path):
    """Rogue's Touched and Valkyrie's Death-Glow are structurally
    indistinguishable from an ordinary signature upgrade - deck_limit 1,
    quantity 1, permanent null, in the hero's own set. Only the config
    entry catches them, and the setup audit is what keeps that entry
    honest as new heroes ship."""
    conn = _mkdb(tmp_path,
                 [("h1", "Rogue", "hero", "rogue", None, 1),
                  ("38002", "Touched", "upgrade", "rogue", 1, 1),
                  ("c2", "Aid", "ally", "core", 3, 3)],
                 out_of_deck=[("38002", "config")])
    assert deckcheck.included(conn, _deck(slots={"38002": 1, "c2": 3})) == {
        "c2": 3}


def test_exclusion_happens_before_unique_matching(tmp_path):
    """Sp//dr, named in §10. Her set has `SP//dr Suit` as a hero face AND
    a permanent support of the same title, both in play at once. Unique
    matching would reject the deck - except the permanent card was never
    in it. Reversing the order makes her fail her own legality check."""
    conn = _mkdb(tmp_path,
                 [("h1", "SP//dr Suit", "hero", "spdr", None, 1),
                  ("s1", "SP//dr Suit", "support", "spdr", 1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("h1", "identity"), ("s1", "permanent")])
    deck = _deck(hero_code="h1", slots={"s1": 1, "a1": 3})
    assert deckcheck.included(conn, deck) == {"a1": 3}


def test_a_double_sided_card_is_one_card_not_two(tmp_path):
    """§10.1: 19 player-card code stems are genuine double-sided faces -
    Psi-Knife, Odin, the four Basic upgrades. `back_link` marks them, the
    same discriminator `assess.back_faces` already uses for encounter
    cards. Counting both faces inflates the deck by one each."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("41002a", "Psi-Knife", "upgrade", "psy", 1, 1),
                  ("41002b", "Psi-Knife", "upgrade", "psy", 1, 1)])
    conn.execute("UPDATE cards SET back_link = '41002b' WHERE code = '41002a'")
    conn.commit()
    assert deckcheck.included(
        conn, _deck(slots={"41002a": 1, "41002b": 1})) == {"41002a": 1}


def test_a_resource_variant_is_not_a_back_face(tmp_path):
    """The other side of the same rule, and why `back_link` rather than a
    code-suffix pattern: the Wakanda Forever! variants share a stem and
    are four separate cards."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("01043a", "Wakanda Forever!", "event", "core", 1, 1),
                  ("01043b", "Wakanda Forever!", "event", "core", 1, 1)])
    assert deckcheck.included(
        conn, _deck(slots={"01043a": 1, "01043b": 1})) == {"01043a": 1,
                                                           "01043b": 1}


# --- size and copies -------------------------------------------------

def test_deck_size_counts_included_cards_only(tmp_path):
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("p1", "Perm", "upgrade", "core", 1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("p1", "permanent")])
    finding = deckcheck.check_size(conn, _deck(slots={"p1": 1, "a1": 3}),
                                   SIZE_CONFIG)
    assert not finding.ok
    assert "3" in finding.detail


def test_a_null_deck_limit_falls_back_to_quantity(tmp_path):
    """§10: `deck_limit` is null on 120 player cards. Null is not
    "unlimited" - without the fallback the validator has no cap at all and
    accepts arbitrary quantities of a signature card."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1),
                            ("s1", "Signature", "ally", "core", None, 2)])
    assert deckcheck.check_copies(conn, _deck(slots={"s1": 2})).ok
    bad = deckcheck.check_copies(conn, _deck(slots={"s1": 3}))
    assert not bad.ok
    assert "Signature" in bad.detail


def test_an_identity_override_can_lower_the_cap(tmp_path):
    """Warlock's `max_copies_non_signature: 1` binds BELOW `deck_limit`
    for every card outside his own set. Reading the column alone accepts
    a deck his own card forbids."""
    conn = _mkdb(tmp_path, [("h1", "Warlock", "hero", "warlock", None, 1),
                            ("a1", "Ally", "ally", "core", 3, 3)])
    override = {"max_copies_non_signature": 1, "set_code": "warlock"}
    assert deckcheck.check_copies(conn, _deck(slots={"a1": 3})).ok
    assert not deckcheck.check_copies(conn, _deck(slots={"a1": 3}),
                                      override).ok


def test_the_four_wakanda_forever_variants_are_four_slots(tmp_path):
    """§10.1: §10 calls 01043a-d a multi-part card whose faces should
    collapse. They are four RESOURCE VARIANTS - energy, mental, physical,
    wild - each separately deck-legal, with limits 1, 1, 1 and 2. Five
    copies, not one. Collapsing them undercounts a legal deck by four."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1)]
                 + [(f"01043{s}", "Wakanda Forever!", "event", "core", lim,
                     lim) for s, lim in
                    (("a", 1), ("b", 1), ("c", 1), ("d", 2))])
    deck = _deck(slots={"01043a": 1, "01043b": 1, "01043c": 1, "01043d": 2})
    assert sum(deckcheck.included(conn, deck).values()) == 5
    assert deckcheck.check_copies(conn, deck).ok


def test_a_deck_with_unknown_slots_says_so(tmp_path):
    """A deck whose size fails because three cards could not be resolved
    must not report "37 cards, needs 40" as if the player built it wrong."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1)])
    finding = deckcheck.check_size(conn, _deck(unknown={"99999": 3}),
                                   SIZE_CONFIG)
    assert "99999" in finding.detail


# --- campaign cards (§10.2) ------------------------------------------

def test_campaign_cards_are_noted_not_judged(tmp_path):
    """§10.2. Whether the player EARNED these lives in the campaign book,
    not the card data, and marvelcdb records slots rather than campaign
    progress. Passing silently would imply the tool checked something it
    cannot see; failing would reject a legal campaign deck."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1),
                            ("21190", "Lady Sif", "ally", "mts", 1, 1),
                            ("a1", "Ally", "ally", "core", 3, 3)])
    conn.execute("UPDATE cards SET faction_code = 'campaign' "
                 "WHERE code = '21190'")
    conn.commit()
    notes = deckcheck.notes(conn, _deck(slots={"21190": 1, "a1": 3}))
    assert len(notes) == 1
    assert notes[0].kind == "note"
    assert "Lady Sif" in notes[0].detail
    assert notes[0].ok


def test_a_deck_with_no_campaign_cards_gets_no_note(tmp_path):
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1),
                            ("a1", "Ally", "ally", "core", 3, 3)])
    assert deckcheck.notes(conn, _deck(slots={"a1": 3})) == []


def test_a_campaign_card_still_obeys_its_deck_limit(tmp_path):
    """§10.2 measured that the copy rules are NOT different: `deck_limit`
    is right on every campaign card and none violates
    `deck_limit <= quantity`. Shawarma's limit of 3 binds normally."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1),
                            ("21183", "Shawarma", "resource", "mts", 3, 4)])
    conn.execute("UPDATE cards SET faction_code = 'campaign' "
                 "WHERE code = '21183'")
    conn.commit()
    assert deckcheck.check_copies(conn, _deck(slots={"21183": 3})).ok
    assert not deckcheck.check_copies(conn, _deck(slots={"21183": 4})).ok


def test_a_note_never_changes_the_verdict(tmp_path):
    """The whole point: `legal` is computed over rules, and a note is not
    a rule. A campaign deck that is otherwise fine must not fail."""
    assert deckcheck.verdict([
        deckcheck.Finding(rule="deck_size", ok=True, detail=""),
        deckcheck.Finding(rule="campaign", ok=True, detail="", kind="note"),
    ])


# --- aspects and uniqueness (Task 4) ---------------------------------

ASPECT_CONFIG = {
    "deck_rules": {
        "minimum_size": 40, "rr_entry": "Deck",
        "aspects": {"default_max": 1, "rr_entry": "Aspect",
                    "always_allowed": ["basic", "hero", "campaign"],
                    "declaration_trusted_above": 0.2,
                    "declaration_min_cards": 5},
    },
    "deckbuilding_overrides": [
        {"identity": "spider_woman", "aspects": 2, "equal_aspects": True}],
}


def _factions(conn, pairs):
    conn.executemany("UPDATE cards SET faction_code = ? WHERE code = ?",
                     [(f, c) for c, f in pairs])
    conn.commit()


def _identity(conn, key, code):
    conn.execute("INSERT INTO identity_faces (identity_key, code) "
                 "VALUES (?, ?)", (key, code))
    conn.commit()


def test_a_single_aspect_deck_passes(tmp_path):
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1),
                            ("j1", "J", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("j1", "justice")])
    assert deckcheck.check_aspects(conn, _deck(slots={"j1": 3}),
                                   ASPECT_CONFIG).ok


def test_an_off_aspect_card_fails(tmp_path):
    """The hero sits in its OWN set, as every hero does in the real data -
    74 hero sets, one per identity. A fixture that puts the hero and an
    ordinary card in one set makes every card look signature."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1),
                            ("a1", "A", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("a1", "aggression")])
    finding = deckcheck.check_aspects(conn, _deck(slots={"a1": 3}),
                                      ASPECT_CONFIG)
    assert not finding.ok
    assert "A" in finding.cards


def test_basic_cards_are_always_legal(tmp_path):
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1),
                            ("b1", "B", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("b1", "basic")])
    assert deckcheck.check_aspects(conn, _deck(slots={"b1": 3}),
                                   ASPECT_CONFIG).ok


def test_spider_womans_own_aspect_cards_are_not_off_aspect(tmp_path):
    """SHE IS THE ONLY HERO THIS HAPPENS TO. Of 685 player cards across 74
    hero sets, 681 are `faction: hero`; the other four are hers - Venom
    Blast (aggression), Inconspicuous (justice), Pheromones (leadership),
    Contaminant Immunity (protection), one per aspect by design.

    A Justice/Leadership Spider-Woman auto-includes the aggression and
    protection ones. Judging by faction alone fails her deck for holding
    cards she cannot remove. Signature is decided by SET MEMBERSHIP, not
    faction."""
    conn = _mkdb(tmp_path,
                 [("h1", "Spider-Woman", "hero", "sw", None, 1),
                  ("04035", "Venom Blast", "event", "sw", 1, 1),
                  ("04037", "Contaminant Immunity", "event", "sw", 1, 1),
                  ("j1", "J", "ally", "core", 3, 3),
                  ("l1", "L", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("04035", "aggression"),
                     ("04037", "protection"), ("j1", "justice"),
                     ("l1", "leadership")])
    _identity(conn, "spider_woman", "h1")
    deck = _deck(hero_code="h1", aspects=["justice", "leadership"],
                 slots={"04035": 1, "04037": 1, "j1": 3, "l1": 3})
    assert deckcheck.check_aspects(conn, deck, ASPECT_CONFIG).ok


def test_two_aspects_fail_unless_the_identity_allows_it(tmp_path):
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1)])
    _factions(conn, [("h1", "hero")])
    finding = deckcheck.check_aspects(
        conn, _deck(aspects=["justice", "leadership"]), ASPECT_CONFIG)
    assert not finding.ok
    assert "2 aspects" in finding.detail


def test_an_equal_aspect_identity_needs_the_counts_to_match(tmp_path):
    """Spider-Woman's card requires an EQUAL number from each chosen
    aspect. An `aspects: 2` check alone passes a 3/1 split it forbids."""
    conn = _mkdb(tmp_path,
                 [("h1", "Spider-Woman", "hero", "sw", None, 1),
                  ("j1", "J", "ally", "core", 3, 3),
                  ("l1", "L", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("j1", "justice"), ("l1", "leadership")])
    _identity(conn, "spider_woman", "h1")
    deck = _deck(hero_code="h1", aspects=["justice", "leadership"],
                 slots={"j1": 3, "l1": 1})
    finding = deckcheck.check_aspects(conn, deck, ASPECT_CONFIG)
    assert not finding.ok
    assert "equal" in finding.detail


def test_her_signature_cards_do_not_skew_the_equal_count(tmp_path):
    """The second bug the same mistake produces: her justice and
    leadership signature cards counted into the balance turn a genuine
    3/3 into 4/4 - or mask a real imbalance, depending which aspects she
    chose."""
    conn = _mkdb(tmp_path,
                 [("h1", "Spider-Woman", "hero", "sw", None, 1),
                  ("04038", "Inconspicuous", "event", "sw", 1, 1),
                  ("j1", "J", "ally", "core", 3, 3),
                  ("l1", "L", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("04038", "justice"),
                     ("j1", "justice"), ("l1", "leadership")])
    _identity(conn, "spider_woman", "h1")
    deck = _deck(hero_code="h1", aspects=["justice", "leadership"],
                 slots={"04038": 1, "j1": 3, "l1": 3})
    assert deckcheck.check_aspects(conn, deck, ASPECT_CONFIG).ok


def test_a_deck_declaring_no_aspect_is_noted_not_failed(tmp_path):
    """marvelcdb keeps the aspect in `meta` and some decks carry none.
    That is a gap in what was recorded, not evidence the deck is illegal -
    failing here rejects a legal deck for its author's omission. Same
    reasoning as campaign cards (§10.2): report what cannot be checked."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1)])
    _factions(conn, [("h1", "hero")])
    finding = deckcheck.check_aspects(conn, _deck(aspects=[]), ASPECT_CONFIG)
    assert finding.ok
    assert finding.kind == "note"


def test_warlock_may_use_every_aspect(tmp_path):
    """His card requires an equal number from ALL FOUR aspects, and
    marvelcdb records at most two, so a Warlock deck's declared aspects
    are structurally incomplete. Judging purity against them rejected
    every published Warlock deck."""
    conn = _mkdb(tmp_path,
                 [("h1", "Adam Warlock", "hero", "warlock", None, 1),
                  ("a1", "A", "ally", "core", 1, 1),
                  ("p1", "P", "ally", "core", 1, 1)])
    _factions(conn, [("h1", "hero"), ("a1", "aggression"),
                     ("p1", "protection")])
    _identity(conn, "warlock", "h1")
    config = dict(ASPECT_CONFIG, deckbuilding_overrides=[
        {"identity": "warlock", "aspects": 4, "all_aspects": True}])
    deck = _deck(hero_code="h1", aspects=["justice", "leadership"],
                 slots={"a1": 1, "p1": 1})
    assert deckcheck.check_aspects(conn, deck, config).ok


def test_a_campaign_card_is_never_off_aspect(tmp_path):
    """§10.2: earned rather than chosen, so aspect purity does not apply."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1),
                            ("21190", "Lady Sif", "ally", "mts", 1, 1)])
    _factions(conn, [("h1", "hero"), ("21190", "campaign")])
    assert deckcheck.check_aspects(conn, _deck(slots={"21190": 1}),
                                   ASPECT_CONFIG).ok


def test_unique_matching_runs_only_over_included_cards(tmp_path):
    """The other half of the Sp//dr constraint: `check_unique` must read
    `included`, never `deck.slots`."""
    conn = _mkdb(tmp_path,
                 [("h1", "SP//dr Suit", "hero", "spdr", None, 1),
                  ("s1", "SP//dr Suit", "support", "spdr", 1, 1)],
                 out_of_deck=[("h1", "identity"), ("s1", "permanent")])
    assert deckcheck.check_unique(conn, _deck(hero_code="h1",
                                              slots={"s1": 1})).ok


def test_check_runs_every_rule_and_carries_the_notes(tmp_path):
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1),
                            ("j1", "J", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("j1", "justice")])
    findings = deckcheck.check(conn, _deck(slots={"j1": 3}), ASPECT_CONFIG)
    assert {f.rule for f in findings} == {"deck_size", "deck_limit",
                                          "aspects", "unique"}
    assert not deckcheck.verdict(findings)      # 3 cards, minimum 40


def test_a_permanent_does_not_count_toward_the_deck_minimum(tmp_path):
    """RR p.32, `Permanent`: the keyword exempts a card from the
    deck-size limits at both ends.

    The corpus proves it independently. Every hero's smallest published
    deck is exactly 40 + its permanent signature cards: Rogue and
    Valkyrie floor at 40, Wolverine and Vision at 41, Psylocke at 42 with
    two permanents, Spectrum at 43 with three.
    """
    conn = _mkdb(tmp_path,
                 [("h1", "Wolverine", "hero", "wolv", None, 1),
                  ("c1", "Wolverine's Claws", "upgrade", "wolv", 1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("c1", "permanent")])
    build = deckcheck.deckbuilding_cards(conn, _deck(slots={"c1": 1,
                                                            "a1": 3}))
    assert build == {"a1": 3}


def test_a_set_aside_card_without_the_keyword_does_count(tmp_path):
    """Touched and Death-Glow carry NO permanent keyword, so RR p.32 does
    not reach them: they are ordinary deck cards that an ability sets
    aside during setup. Excluding them told every Rogue and Valkyrie
    player their legal 40-card deck was one short."""
    conn = _mkdb(tmp_path,
                 [("h1", "Rogue", "hero", "rogue", None, 1),
                  ("38002", "Touched", "upgrade", "rogue", 1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("38002", "config")])
    deck = _deck(slots={"38002": 1, "a1": 3})
    assert deckcheck.deckbuilding_cards(conn, deck) == {"38002": 1, "a1": 3}
    # ... and it is still not something you can draw.
    assert deckcheck.included(conn, deck) == {"a1": 3}


# --- the regression corpus (Task 5) ----------------------------------

@pytest.mark.integration
def test_published_decks_are_overwhelmingly_legal(real_index):
    """§10's only stated mitigation for the highest-risk file here.

    A REGRESSION SIGNAL, not ground truth. marvelcdb is a community
    deck-builder, not a rules enforcer: it does not block an illegal deck
    from being published, and players can play whatever they like. So a
    nonzero rate is expected, and the rulebook wins whenever the two
    disagree (§10.2a). Never tune `legality.yaml` to lower this number.

    The first run rejected 14.1%, and every point of the drop to 4.5% was
    a real defect - see §10.3, which records all five and the
    card-by-card reading of what remains.

    DO NOT raise this threshold to make the test pass. The 6% is argued
    for, not observed: the residue was read category by category, and the
    strongest evidence is the distribution rather than the rate. Across
    1,478 decks with a declared aspect, 96.3% have ZERO off-aspect cards,
    1.6% have exactly one and 1.0% exactly two. A sharp mode at zero with
    a diffuse tail is the shape of human slips; a missing allowance would
    spike at one hero or one count.

    `problem` is not exposed on the public endpoint, so this is a
    statistical signal and not per-deck ground truth - which is precisely
    why the number has to be argued for.
    """
    from mc_jarvis import deckfetch

    decks = list(deckfetch.corpus())
    if len(decks) < 200:
        pytest.skip("no corpus; run `uv run python tools/deck_corpus.py`")

    checked = rejected = 0
    reasons: dict[str, int] = {}
    for payload in decks:
        try:
            deck = deckfetch.normalise(real_index, payload, source="corpus")
        except deckfetch.DeckError:
            continue          # a hero marvelsdb does not carry yet
        if deck.unknown:
            continue          # card data behind marvelcdb, not a rules bug
        checked += 1
        for finding in deckcheck.check(real_index, deck):
            if finding.kind == "rule" and not finding.ok:
                reasons[finding.rule] = reasons.get(finding.rule, 0) + 1
                rejected += 1
                break

    rate = rejected / checked
    assert rate <= 0.06, (
        f"{rejected}/{checked} = {rate:.1%} of published decks rejected, "
        f"by rule: {reasons}. Read them before touching this number - "
        f"§10.3 records what the last reading found.")


@pytest.mark.integration
def test_the_corpus_still_discriminates(real_index):
    """A rate near zero would mean the rules stopped firing, which reads
    identical to "everything is fine". The corpus must still reject the
    decks that are genuinely illegal - a Captain America deck holding the
    Captain America ally is in there, and so are six decks under 40
    cards."""
    from mc_jarvis import deckfetch

    decks = list(deckfetch.corpus())
    if len(decks) < 200:
        pytest.skip("no corpus; run `uv run python tools/deck_corpus.py`")

    rejected = 0
    for payload in decks:
        try:
            deck = deckfetch.normalise(real_index, payload, source="corpus")
        except deckfetch.DeckError:
            continue
        if deck.unknown:
            continue
        if not deckcheck.verdict(deckcheck.check(real_index, deck)):
            rejected += 1
    assert rejected >= 20, (
        f"only {rejected} rejections - the rules may have stopped firing "
        f"rather than the corpus having become cleaner")


def test_a_stale_aspect_declaration_is_noted_not_failed(tmp_path):
    """marvelcdb keeps the declared aspect in `meta`, SEPARATELY from the
    cards, so a player can rebuild a deck into another aspect and leave
    the declaration behind - or never set it at all.

    Judging purity against a stale declaration rejects a legal deck and
    names the wrong cards as the problem, which is worse than saying
    nothing. Measured: 15 of 1,478 decks match their declaration 10% or
    less, one Cable deck declaring protection while holding 12 leadership
    cards."""
    conn = _mkdb(tmp_path,
                 [("h1", "Cable", "hero", "cable", None, 1)]
                 + [(f"l{i}", f"L{i}", "ally", "core", 3, 3)
                    for i in range(6)])
    _factions(conn, [("h1", "hero")]
              + [(f"l{i}", "leadership") for i in range(6)])
    deck = _deck(hero_code="h1", aspects=["protection"],
                 slots={f"l{i}": 1 for i in range(6)})
    finding = deckcheck.check_aspects(conn, deck, ASPECT_CONFIG)
    assert finding.ok
    assert finding.kind == "note"
    assert "out of date" in finding.detail


def test_a_deck_that_is_mostly_on_aspect_still_fails_for_a_slip(tmp_path):
    """The other side of the cut, and the reason the threshold sits in a
    measured empty band. A deck with one off-aspect card is a
    deckbuilding slip and must still be reported - 96.3% of decks have
    zero, 1.6% have exactly one."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "ownset", None, 1)]
                 + [(f"j{i}", f"J{i}", "ally", "core", 3, 3)
                    for i in range(6)]
                 + [("a1", "Off", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("a1", "aggression")]
              + [(f"j{i}", "justice") for i in range(6)])
    deck = _deck(aspects=["justice"],
                 slots={**{f"j{i}": 1 for i in range(6)}, "a1": 1})
    finding = deckcheck.check_aspects(conn, deck, ASPECT_CONFIG)
    assert not finding.ok
    assert finding.cards == ["Off"]


def test_a_tiny_deck_declaration_is_taken_at_face_value(tmp_path):
    """Below a handful of aspect cards there is nothing to judge a
    declaration against, and calling it stale on two cards would be
    guessing."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1),
                            ("a1", "Off", "ally", "core", 3, 3)])
    _factions(conn, [("h1", "hero"), ("a1", "aggression")])
    finding = deckcheck.check_aspects(conn, _deck(aspects=["justice"],
                                                  slots={"a1": 2}),
                                      ASPECT_CONFIG)
    assert not finding.ok


def test_a_linked_card_is_not_in_the_deck_either(tmp_path):
    """RR p.27, `Linked (Card Title)` - the same exemption `Permanent`
    gets on p.32, in the same words: the card cannot be in a deck and does
    not count toward the size limits at either end.

    NO corpus deck lists one, so the published decks could never have
    taught this rule. marvelcdb is a community deck-builder, not a rules
    enforcer; the rulebook is the authority and the corpus is only a
    regression signal."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "ownset", None, 1),
                  ("49033", "Surge", "ally", "core", 1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("49033", "linked")])
    deck = _deck(slots={"49033": 1, "a1": 3})
    assert deckcheck.deckbuilding_cards(conn, deck) == {"a1": 3}
    assert deckcheck.included(conn, deck) == {"a1": 3}


# --- linked cards arrive during play (RR p.27) -----------------------

def _linked_db(tmp_path):
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "ownset", None, 1),
                  ("43021", "Specialized Training", "player_side_scheme",
                   "core", 1, 1),
                  ("43034", "Combat Specialist", "upgrade", "core", 1, 1),
                  ("43035", "Defense Specialist", "upgrade", "core", 1, 1),
                  ("53023", "Captain America", "upgrade", "core", 1, 1),
                  ("53034", "Captain America's Shield", "upgrade", "core",
                   1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("43034", "linked"), ("43035", "linked"),
                              ("53034", "linked")])
    conn.executemany("UPDATE cards SET text = ? WHERE code = ?", [
        ("Linked (Specialized Training). Your hero gets +1 ATK.", "43034"),
        ("Linked (Specialized Training). Your hero gets +1 DEF.", "43035"),
        ("Linked (Captain America upgrade). Restricted.", "53034"),
        ("<b>When Defeated</b>: choose 1 set-aside upgrade.", "43021"),
        ("<b>Hero Action</b>: find Captain America's Shield.", "53023")])
    conn.commit()
    return conn


def test_a_linked_card_arrives_when_its_enabler_is_in_the_deck(tmp_path):
    """RR p.27 keeps linked cards out of the deck, and the corpus agrees -
    0 of 1,501 published decks list one. But 215 list an ENABLER, so one
    deck in seven acquires linked cards during play and `deck stats` said
    nothing about them.

    Reporting only "not in the deck" describes a game the player does not
    have: a Specialized Training deck really does end up with a
    Specialist upgrade in play, and in the deck once it is discarded."""
    conn = _linked_db(tmp_path)
    arriving = deckcheck.arriving(conn, _deck(slots={"43021": 1, "a1": 3}))
    assert {a["name"] for a in arriving} == {"Combat Specialist",
                                             "Defense Specialist"}
    assert all(a["enabler"] == "Specialized Training" for a in arriving)


def test_an_enabler_that_is_an_upgrade_works_the_same_way(tmp_path):
    """`Linked (Captain America upgrade)` names a card plus its type, not
    a bare title. The Captain America upgrade finds the Shield and adds it
    to your hand."""
    conn = _linked_db(tmp_path)
    arriving = deckcheck.arriving(conn, _deck(slots={"53023": 1, "a1": 3}))
    assert [a["name"] for a in arriving] == ["Captain America's Shield"]


def test_no_enabler_means_nothing_arrives(tmp_path):
    conn = _linked_db(tmp_path)
    assert deckcheck.arriving(conn, _deck(slots={"a1": 3})) == []


def test_a_linked_card_still_does_not_count_toward_the_minimum(tmp_path):
    """RR p.27 is explicit and unchanged by any of the above: linked cards
    are exempt from the deck-size limits at both ends."""
    conn = _linked_db(tmp_path)
    deck = _deck(slots={"43021": 1, "43034": 1, "a1": 3})
    assert deckcheck.deckbuilding_cards(conn, deck) == {"43021": 1, "a1": 3}


def test_a_deck_over_the_maximum_fails(tmp_path):
    """Learn to Play p.22 gives BOTH bounds in one sentence - "a minimum
    of 40 cards and a maximum of 50". Only the 40 was implemented.

    The corpus shows the 50 is as real: 707 decks sit at exactly 40 and
    74 at exactly 50, a mode at each end, and only 4 of 1,501 exceed it.
    """
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "ownset", None, 1),
                            ("a1", "Ally", "ally", "core", 60, 60)])
    config = {"deck_rules": {"minimum_size": 40, "maximum_size": 50,
                             "rr_entry": "learn-to-play p.22: DECK"}}
    assert not deckcheck.check_size(conn, _deck(slots={"a1": 51}),
                                    config).ok
    assert deckcheck.check_size(conn, _deck(slots={"a1": 50}), config).ok
    assert deckcheck.check_size(conn, _deck(slots={"a1": 40}), config).ok


def test_a_permanent_does_not_push_a_deck_over_the_maximum(tmp_path):
    """The same rule exempts permanents at BOTH ends (RR p.32), so a
    50-card Psylocke deck plus her two permanent Psi-blades is legal."""
    conn = _mkdb(tmp_path,
                 [("h1", "Psylocke", "hero", "psy", None, 1),
                  ("a1", "Ally", "ally", "core", 60, 60),
                  ("p1", "Psi-Knife", "upgrade", "psy", 1, 1),
                  ("p2", "Psi-Katana", "upgrade", "psy", 1, 1)],
                 out_of_deck=[("p1", "permanent"), ("p2", "permanent")])
    config = {"deck_rules": {"minimum_size": 40, "maximum_size": 50,
                             "rr_entry": "learn-to-play p.22: DECK"}}
    deck = _deck(slots={"a1": 50, "p1": 1, "p2": 1})
    assert deckcheck.check_size(conn, deck, config).ok
