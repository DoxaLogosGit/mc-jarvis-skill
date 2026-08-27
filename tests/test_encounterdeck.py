"""Encounter-deck membership (assess spec §5.2, as corrected by §14.5-§14.8).

Set membership is the denominator of every average `assess` reports. Get it
wrong and all the numbers are wrong while looking entirely plausible, which
is the failure the spec opens with.

Two earlier passes concluded no signal existed. Both were wrong, and both
times the cause was searching a single spelling — so several tests below
exist specifically to pin a spelling variant that was once missed.
"""
import pytest

from mc_jarvis import encounterdeck as ed


def _card(**kw):
    base = {"code": "x", "name": "X", "type_code": "treachery", "traits": "",
            "text": "", "permanent": None, "boost": None, "quantity": 1,
            "set_code": "s"}
    base.update(kw)
    return base


# --- the type rule ---------------------------------------------------

def test_villains_and_main_schemes_are_never_in_the_deck():
    for t in ("villain", "main_scheme"):
        role, _ = ed.classify_card(_card(type_code=t))
        assert role == ed.STARTS_IN_PLAY, t


def test_player_side_types_in_encounter_sets_are_not_encounter_cards():
    """Every encounter-set `ally` is a rescued-captive type that enters
    play FOR the players via a side scheme. `upgrade`, `event`, `support`
    and `resource` in encounter sets are campaign rewards."""
    for t in ("ally", "upgrade", "event", "support", "resource",
              "player_side_scheme"):
        role, _ = ed.classify_card(_card(type_code=t))
        assert role == ed.NOT_ENCOUNTER, t


def test_an_ordinary_treachery_is_in_the_deck():
    role, returns = ed.classify_card(_card(type_code="treachery", boost=2))
    assert role == ed.DECK
    assert returns is True


# --- separate decks (§14.5) ------------------------------------------

def test_a_card_belonging_to_another_deck_is_not_in_the_encounter_deck():
    """The `infinity_gauntlet` modular is 7 cards and NONE is in the
    encounter deck: the Gauntlet attaches at setup and the six Stones are
    their own deck. Counting them adds 7 phantom cards."""
    role, returns = ed.classify_card(_card(
        type_code="environment", name="Power Stone",
        text="<b>Special:</b> You are stunned. Place this card in the "
             "[[infinity stone]] deck discard pile."))
    assert role == ed.OTHER_DECK
    assert returns is False


def test_referring_to_another_deck_is_not_belonging_to_it():
    """24 cards name a `[[X]] deck`; only 6 say they go into one.
    `Infinity Gauntlet` is a setup attachment that merely talks about the
    stone deck — a mention-match files it as a member and loses its real
    role."""
    role, _ = ed.classify_card(_card(
        type_code="attachment", name="Infinity Gauntlet", permanent=1,
        text="Permanent. Setup [star] <b>Forced Response</b>: ... put the "
             "top card of the [[infinity stone]] deck into play."))
    assert role == ed.SETUP_ATTACHMENT

    for text in ("Shuffle the [[infinity stone]] deck.",
                 "Reveal the top card of the [[infinity stone]] deck."):
        role, _ = ed.classify_card(_card(type_code="treachery", text=text))
        assert role == ed.DECK, text


# --- Setup, permanent, and cycling back (§14.6) -----------------------

def test_setup_and_permanent_never_returns():
    """`permanent` means "cannot be discarded from play", so a Setup card
    that is also permanent can never reach the discard pile."""
    role, returns = ed.classify_card(_card(
        type_code="attachment", name="Infinity Gauntlet", permanent=1,
        text="Permanent. Setup [star] <b>Forced Response</b>: ..."))
    assert role == ed.SETUP_ATTACHMENT
    assert returns is False


def test_setup_without_permanent_cycles_back_into_the_deck():
    """The three [[Setting]] environments start in play, are discarded when
    another is revealed, and rejoin the deck on reshuffle. Their own text
    proves it: a When Revealed ability and a boost value are both
    meaningless for a card that never enters the encounter deck."""
    role, returns = ed.classify_card(_card(
        type_code="environment", name="The Savage Land", permanent=None,
        boost=3,
        text="Setup. The villain gains retaliate 1. <b>Special</b>: ... "
             "<b>When Revealed</b>: Discard each other [[Setting]] "
             "environment in play."))
    assert role == ed.STARTS_IN_PLAY
    assert returns is True


def test_setup_with_neither_signal_stays_out():
    """The three `Chief ... Officer` environments FLIP rather than discard,
    which keeps them out permanently. Unverified whether anything else can
    discard them, so this asserts the conservative reading."""
    role, returns = ed.classify_card(_card(
        type_code="environment", name="Chief Medical Officer",
        text="Setup. If there are 4 or more secret counters here, flip "
             "this card. <b>Hero Action</b>: ..."))
    assert role == ed.STARTS_IN_PLAY
    assert returns is False


def test_the_bare_setup_spelling_is_matched():
    """FFG writes it both as a bold trigger and as a bare sentence opener.
    Matching only `<b>Setup</b>` misses `Setup. Attach to the villain.`
    entirely — which is how the signal was missed the first time."""
    for text in ("<b>Setup</b>: Attach to the villain. Permanent.",
                 "Setup. Attach to the villain. Permanent.",
                 "Permanent. Setup [star] <b>Forced Response</b>: ..."):
        role, _ = ed.classify_card(_card(
            type_code="attachment", permanent=1, text=text))
        assert role == ed.SETUP_ATTACHMENT, text


def test_permanent_alone_does_not_remove_a_card_from_the_deck():
    """The trap. Enchantress's `Trance of Envy` is permanent AND has a When
    Revealed ability, which only fires on a reveal FROM the encounter deck.
    It is drawn, then stays. Treating `permanent` as "not in the deck"
    removes cards that demonstrably are in it."""
    role, _ = ed.classify_card(_card(
        type_code="attachment", name="Trance of Envy", permanent=1,
        text="Permanent. Your identity gains the [[Enthralled]] trait. "
             "<b>When Revealed</b>: Discard a card you control."))
    assert role == ed.DECK


def test_boost_alone_does_not_remove_a_card_either():
    """`Armored Rhino Suit` has no boost and `Charge` has 2, which is
    tempting — but `The Sleeper` is set aside by its scenario and carries
    boost 1. Absence correlates; presence does not exclude."""
    role, _ = ed.classify_card(_card(
        type_code="attachment", name="Armored Rhino Suit",
        text="Attach to Rhino. <b>Forced Interrupt</b>: ..."))
    assert role == ed.DECK


# --- set-aside groups from card text (§14.7) -------------------------

def test_set_aside_groups_are_read_from_the_hyphenated_form():
    """FFG writes the adjective hyphenated. Searching `set aside` finds 5
    cards; `set-aside` finds 91. That one spelling is what made an earlier
    pass conclude the list was underivable."""
    rows = [
        _card(set_code="apocalypse", name="Heart of the Empire",
              type_code="main_scheme",
              text="The first player reveals a random set-aside "
                   "[[Prelate]] minion."),
        _card(set_code="m.o.d.o.k.", name="Upgrading Adaptoids",
              type_code="main_scheme",
              text="put 1 random set-aside [[Adaptoid]] environment into "
                   "play instead."),
    ]
    groups = ed.set_aside_groups(rows)
    assert groups[("Prelate", "minion")] == {"apocalypse"}
    assert groups[("Adaptoid", "environment")] == {"m.o.d.o.k."}


def test_a_named_card_is_read_as_a_group_of_one():
    rows = [_card(set_code="magneto_villain", name="Sabotage Master Mold",
                  type_code="side_scheme",
                  text="<b>When Defeated</b>: Reveal the set-aside Orbital "
                       "Decay side scheme.")]
    assert ("Orbital Decay", "side_scheme") in ed.set_aside_groups(rows)


def test_the_nemesis_set_aside_area_is_not_a_card_group():
    """`set-aside area for your nemesis` is the nemesis area, not a group.
    One of two regex artefacts named in §14.7."""
    rows = [_card(set_code="standard_iii", name="Pursued by the Past",
                  text="Search the set-aside area for your nemesis side "
                       "scheme and reveal it.")]
    assert ed.set_aside_groups(rows) == {}


def test_a_group_named_by_a_villain_stage_is_read():
    """Bullseye (I) reads "When Revealed: Set aside Adamantium-Laced
    Spine"; Bullseye (II) finds and attaches it. Content mc-jarvis has
    never indexed, and the rule reaches it — which is the point of
    deriving the list from text rather than enumerating it."""
    rows = [_card(set_code="bullseye", name="Bullseye", type_code="villain",
                  text="<b>When Revealed</b>: Find the set-aside "
                       "Adamantium-Laced Spine attachment and attach it "
                       "to Bullseye.")]
    assert ("Adamantium-Laced Spine", "attachment") in ed.set_aside_groups(rows)


# --- the set-aside audit ---------------------------------------------

def _mkdb(tmp_path, sets, cards):
    """A minimal index. `cards` needs canonical_code, is_reprint and raw:
    all three are NOT NULL, and a fixture that omits them fails on the
    constraint rather than on the behaviour under test."""
    from mc_jarvis import index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO sets (code, name, card_set_type_code) VALUES (?, ?, ?)",
        sets)
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, set_code, text, traits, "
        "quantity, canonical_code, is_reprint, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[0]) for c in cards])
    conn.commit()
    return conn


def test_audit_is_clean_when_the_text_rule_covers_the_flagged_set(tmp_path):
    """A scenario whose Setup block sets something aside must have that
    something identified. Coverage is acknowledged, never inferred."""
    conn = _mkdb(
        tmp_path, [("apoc", "Apocalypse", "villain")],
        [("m1", "The Age of Apocalypse", "main_scheme", "apoc",
          "<b>Setup</b>: Set aside each [[Prelate]] minion.", "", 1),
         ("m2", "Heart of the Empire", "main_scheme", "apoc",
          "The first player reveals a random set-aside [[Prelate]] minion.",
          "", 1),
         ("p1", "Prelate Guard", "minion", "apoc", "Guard.", "Prelate.", 2)])
    assert ed.audit(conn, {"acknowledged": {}}) == []


def test_audit_names_a_flagged_set_that_nothing_covers(tmp_path):
    conn = _mkdb(
        tmp_path, [("myst", "Mystery", "villain")],
        [("m1", "A Scheme", "main_scheme", "myst",
          "<b>Setup</b>: Set the Whatsit attachment aside.", "", 1)])
    problems = ed.audit(conn, {"acknowledged": {}})
    assert problems and "myst" in problems[0]


def test_a_put_into_play_instruction_also_flags(tmp_path):
    """`put ... into play` removes cards from the deck just as an aside
    does. 26 villain sets say it, against 16 that say "set ... aside"."""
    conn = _mkdb(
        tmp_path, [("ult", "Ultron", "villain")],
        [("m1", "Ultron Assembled", "main_scheme", "ult",
          "<b>Setup</b>: Put the Ultron Drones environment into play.",
          "", 1)])
    assert ed.audit(conn, {"acknowledged": {}})


def test_an_acknowledged_set_passes_when_its_setup_is_unchanged(tmp_path):
    conn = _mkdb(
        tmp_path, [("myst", "Mystery", "villain")],
        [("m1", "A Scheme", "main_scheme", "myst",
          "<b>Setup</b>: Set the Whatsit attachment aside.", "", 1)])
    setup = ed.setup_blocks(conn)["myst"]
    config = {"acknowledged": {"myst": {
        "reason": "one attachment, named nowhere else",
        "setup_digest": ed.digest(setup)}}}
    assert ed.audit(conn, config) == []


def test_a_reworded_setup_invalidates_its_acknowledgment(tmp_path):
    """The acknowledgment describes a specific sentence. If the scheme is
    reworded the reason may no longer hold, so it must be re-read rather
    than kept on file."""
    conn = _mkdb(
        tmp_path, [("myst", "Mystery", "villain")],
        [("m1", "A Scheme", "main_scheme", "myst",
          "<b>Setup</b>: Set the Whatsit attachment aside.", "", 1)])
    config = {"acknowledged": {"myst": {
        "reason": "one attachment", "setup_digest": "0" * 32}}}
    problems = ed.audit(conn, config)
    assert problems and "changed" in problems[0]


def test_a_set_with_no_setup_block_is_not_flagged(tmp_path):
    """Rhino's entire Setup is "Advance to stage 1B" - nothing removed,
    nothing to acknowledge."""
    conn = _mkdb(
        tmp_path, [("rhino", "Rhino", "villain")],
        [("m1", "The Break-In!", "main_scheme", "rhino",
          "<b>Contents</b>: Rhino and Standard sets. <b>Setup</b>: Advance "
          "to stage 1B.", "", 1)])
    assert ed.audit(conn, {"acknowledged": {}}) == []


# --- the scenario -> modular mapping (§14.1) -------------------------

def test_prescribed_modulars_are_read_from_the_contents_block():
    """§4.7 said this mapping was not in the data. It checked for a
    structured FIELD; FFG prints it in the scenario's own main scheme
    Contents block, and 49 of 56 villain sets have one."""
    got = ed.parse_contents(
        "<b>Contents</b>: Unus (I) and Unus (II). Unus, Infinites, and "
        "Standard sets. One modular set <i>(Dystopian Nightmare)</i>. "
        "<b>Setup</b>: Reveal the Gene Pool side scheme.")
    assert got["kind"] == "prescribed"
    assert got["names"] == ["Dystopian Nightmare"]


def test_two_named_modulars_are_split():
    got = ed.parse_contents(
        "<b>Contents</b>: ... Two modular sets <i>(Dark Riders and "
        "Infinites)</i>.")
    assert got["names"] == ["Dark Riders", "Infinites"]


def test_a_recommendation_is_not_a_prescription():
    """`(recommended: Bomb Scare)` and `(Dystopian Nightmare)` are
    different strings in FFG's own text. Flattening them states a
    constraint the box does not impose."""
    got = ed.parse_contents(
        "<b>Contents</b>: ... One modular encounter set "
        "<i>(recommended: Bomb Scare)</i>.")
    assert got["kind"] == "recommended"
    assert got["names"] == ["Bomb Scare"]


def test_markup_and_trailing_stops_are_stripped():
    """Five sets failed to resolve because the capture kept inner <i>
    tags; two more because the stop sat inside the parentheses."""
    got = ed.parse_contents(
        "<b>Contents</b>: ... Two modular sets (<i>Acolytes</i> and "
        "<i>Mystique</i>.).")
    assert got["names"] == ["Acolytes", "Mystique"]


def test_a_player_chosen_scenario_names_nothing():
    """Thunderbolts and the PvP scenarios let the player choose. There is
    no mapping to infer, and inventing one would be worse than none."""
    got = ed.parse_contents(
        "<b>Contents</b>: ... <b>Setup</b>: Choose 1 modular set, plus "
        "1[per_hero] additional modular sets, each with an [[Elite]] minion.")
    assert got["kind"] == "open"
    assert got["names"] == []


def test_a_random_scenario_is_marked_random():
    got = ed.parse_contents(
        "<b>Contents</b>: ... 1 random modular set from the collection.")
    assert got["kind"] == "random"


def test_no_contents_block_at_all():
    assert ed.parse_contents("<b>Setup</b>: Advance to stage 1B.")["kind"] \
        == "none"


def test_a_modular_clause_without_italics_still_parses():
    """`brotherhood_of_badoon` prints it in bare parentheses."""
    got = ed.parse_contents(
        "<b>Contents</b>: ... One modular encounter set (Band of Badoon).")
    assert got["kind"] == "prescribed"
    assert got["names"] == ["Band of Badoon"]


# --- the real corpus -------------------------------------------------

@pytest.mark.integration
def test_the_real_corpus_classifies_to_measured_counts(real_index):
    """Measured 2026-08-26. Each of these is a decision recorded in the
    spec, not a number the implementation happened to produce."""
    from mc_jarvis import encounterdeck

    encounterdeck.build(real_index)

    def n(sql):
        return real_index.execute(sql).fetchone()[0]

    # The six Infinity Stones, and only those, claim membership of another
    # deck. 24 cards MENTION one; matching mentions gave 15 and mis-filed
    # `Infinity Gauntlet` as a stone rather than a setup attachment.
    assert n("SELECT COUNT(*) FROM encounter_role WHERE role='other_deck'") == 6

    # Power Stone, Infinity Gauntlet, Flight, Super Strength, Telepathy.
    assert n("SELECT COUNT(*) FROM encounter_role "
             "WHERE role='setup_attachment'") == 5

    # The three [[Setting]] environments: start in play, get discarded when
    # another is revealed, rejoin the deck on reshuffle.
    assert n("SELECT COUNT(*) FROM encounter_role "
             "WHERE returns_to_deck=1 AND role<>'deck'") == 3


@pytest.mark.integration
def test_every_card_has_exactly_one_role(real_index):
    """The denominator of every assess average. A card missing a role
    silently leaves the deck; a duplicated one silently doubles."""
    from mc_jarvis import encounterdeck

    encounterdeck.build(real_index)
    cards = real_index.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    roles = real_index.execute(
        "SELECT COUNT(*) FROM encounter_role").fetchone()[0]
    assert roles == cards

    orphans = real_index.execute(
        "SELECT COUNT(*) FROM encounter_role e "
        "LEFT JOIN cards c ON c.code = e.code WHERE c.code IS NULL"
    ).fetchone()[0]
    assert orphans == 0


@pytest.mark.integration
def test_the_set_aside_groups_reach_the_known_scenarios(real_index):
    """Derived from card text, and it must find the groups the main scheme
    Setup blocks name independently — two unrelated places in the data."""
    from mc_jarvis import encounterdeck

    rows = [dict(r) for r in real_index.execute(
        "SELECT code, name, type_code, traits, text, set_code FROM cards")]
    groups = encounterdeck.set_aside_groups(rows)
    for want in (("Prelate", "minion"), ("Adaptoid", "environment"),
                 ("Captive", "ally"), ("Thunderbolt", "minion"),
                 ("Orbital Decay", "side_scheme")):
        assert want in groups, want


@pytest.mark.integration
def test_the_shipped_config_leaves_no_scenario_unaccounted(real_index):
    """A scenario whose Setup removes cards, covered by neither the text
    rules nor an acknowledgment, would have its deck silently mis-counted.
    Measured 2026-08-26: 33 of 56 villain sets are flagged, 20 are covered
    by the two text rules, and 13 are acknowledged by hand."""
    from mc_jarvis import encounterdeck

    assert encounterdeck.audit(real_index) == []


@pytest.mark.integration
def test_every_acknowledgment_still_matches_its_setup_block(real_index):
    """The reasons describe specific sentences. A reworded scheme must
    force a re-read rather than keep a stale reason on file - which is
    what the digest is for, so this asserts it actually fires."""
    from mc_jarvis import encounterdeck

    config = encounterdeck.load_config()
    blocks = encounterdeck.setup_blocks(real_index)
    for code, entry in (config.get("acknowledged") or {}).items():
        assert code in blocks, f"{code} no longer has a Setup block"
        assert entry["setup_digest"] == encounterdeck.digest(blocks[code]), code
        assert entry.get("reason"), code
        assert "affects_deck" in entry, code


@pytest.mark.integration
def test_a_tampered_acknowledgment_is_caught(real_index):
    """Guards the guard: if the digest check could not fail, the audit
    above would pass vacuously."""
    from mc_jarvis import encounterdeck

    config = encounterdeck.load_config()
    tampered = {"acknowledged": {
        k: dict(v, setup_digest="0" * 32)
        for k, v in (config.get("acknowledged") or {}).items()}}
    assert encounterdeck.audit(real_index, tampered)
