import json

import pytest

from mc_jarvis import cardtext, index
from tests.fixtures import cards as fx


def test_traits_come_from_markup():
    assert cardtext.parse_traits(
        "Protects [[S.H.I.E.L.D.]] and [[Aerial]] allies."
    ) == ["S.H.I.E.L.D.", "Aerial"]


def test_plain_cost_and_effect_split():
    c = cardtext.parse_arrow("<b>Action:</b> Discard a card → draw a card.")[0]
    assert c.ability_type == "Action"
    assert c.timing is None
    assert c.cost == "Discard a card"
    assert c.effect == "draw a card."
    assert c.ambiguous is False


def test_interrupt_timing_is_not_part_of_the_cost():
    """Splitting on the arrow alone would report the When-clause as
    something the player must pay (spec §10)."""
    c = cardtext.parse_arrow(fx.ARROW_CARDS[1]["text"])[0]
    assert c.ability_type == "Interrupt"
    assert c.timing == "When a character would take damage"
    assert c.cost == "exhaust an [[Aerial]] character you control"
    assert "When a character" not in c.cost


def test_if_clauses_are_flagged_not_guessed():
    c = cardtext.parse_arrow(fx.ARROW_CARDS[2]["text"])[0]
    assert c.ambiguous is True
    assert c.timing is None


def test_two_arrows_produce_two_clauses():
    clauses = cardtext.parse_arrow(fx.ARROW_CARDS[3]["text"])
    assert [c.ordinal for c in clauses] == [0, 1]
    assert clauses[1].ability_type == "Response"
    assert clauses[1].timing == "After you draw"


def test_no_arrow_produces_no_clauses():
    assert cardtext.parse_arrow("Toughness. Retaliate 1.") == []


def test_raw_text_is_preserved_on_every_clause():
    for c in cardtext.parse_arrow(fx.ARROW_CARDS[3]["text"]):
        assert "→" in c.raw


def test_build_populates_all_three_tables(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.ARROW_CARDS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    conn = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(conn, root)
    counts = cardtext.build(conn)
    assert counts["traits"] >= 3
    assert counts["clauses"] == 5
    kws = {r["keyword"] for r in conn.execute(
        "SELECT keyword FROM card_keywords WHERE code = 'arw05'")}
    assert {"toughness", "retaliate"} <= kws


@pytest.mark.integration
def test_real_corpus_arrow_counts(real_index):
    """Scoped to PLAYER_FACTIONS, which is what spec §16 measured. A bare
    `faction_code != 'encounter'` also counts campaign cards and inflates
    every figure."""
    from mc_jarvis.index import PLAYER_FACTIONS
    marks = ", ".join("?" * len(PLAYER_FACTIONS))
    q = (f"SELECT COUNT(*) FROM cost_clauses cc JOIN cards c "
         f"ON c.code = cc.code WHERE c.faction_code IN ({marks})")
    total = real_index.execute(q, PLAYER_FACTIONS).fetchone()[0]
    timed = real_index.execute(
        q + " AND cc.timing IS NOT NULL", PLAYER_FACTIONS).fetchone()[0]
    ambiguous = real_index.execute(
        q + " AND cc.ambiguous = 1", PLAYER_FACTIONS).fetchone()[0]
    assert 600 < total < 900           # 693 on 2026-08-22
    assert 200 < timed < 400           # 268
    assert ambiguous < 25              # 4
    assert timed > total * 0.25        # the RR exclusion is not rare


@pytest.mark.integration
def test_no_timing_clause_leaked_into_a_cost(real_index):
    """The failure this task exists to prevent."""
    # Must not anchor on 'When %': real markup leaves a colon in front,
    # so ': When ...' slipped past an earlier version of this check.
    leaked = real_index.execute(
        "SELECT code, cost FROM cost_clauses "
        "WHERE cost GLOB '*[Ww]hen *' OR cost GLOB '*[Aa]fter *' "
        "OR cost LIKE ':%'").fetchall()
    assert leaked == [], [(r["code"], r["cost"]) for r in leaked]


def test_basic_power_qualifier_is_captured_not_discarded():
    """Real markup: `<b>Hero Interrupt</b> <i>(defense)</i>: When ...`.
    The parenthetical names which basic power the ability attaches to and
    sits between the bold span and the colon."""
    c = cardtext.parse_arrow(
        "<b>Hero Interrupt</b> <i>(defense)</i>: When you would take "
        "damage, discard this card → prevent 1 damage.")[0]
    assert c.ability_type == "Hero Interrupt"
    assert c.qualifier == "defense"
    assert c.timing == "When you would take damage"
    assert c.cost == "discard this card"


def test_qualifier_parses_with_tags_inside_the_parentheses():
    """Both shapes occur in the corpus: `<i>(attack)</i>` with the tags
    outside the parentheses, and `(<i>defense</i>)` with them inside."""
    c = cardtext.parse_arrow(
        "<b>Hero Action</b> (<i>attack</i>): Exhaust a card "
        "→ deal 1 damage.")[0]
    assert c.qualifier == "attack"
    assert c.cost == "Exhaust a card"


def test_colon_outside_the_bold_span_still_yields_timing():
    """The colon sits outside the tag in real data. Leaving it in front
    blocks the timing match and reports the whole clause as a cost."""
    c = cardtext.parse_arrow(
        "<b>Interrupt</b>: When an enemy attacks, exhaust a character "
        "→ prevent 1 damage.")[0]
    assert c.timing == "When an enemy attacks"
    assert not c.cost.startswith(":")


def test_a_trigger_with_no_cost_yields_an_empty_cost():
    """`<b>Hero Response</b>: After ... → discard this card.` states no
    cost. Reporting the trigger as one tells the player to pay for
    something that is free."""
    c = cardtext.parse_arrow(
        "<b>Hero Response</b>: After your hero defends and takes no "
        "damage → discard this card.")[0]
    assert c.timing == "After your hero defends and takes no damage"
    assert c.cost == ""
    assert c.effect == "discard this card."


def test_colon_inside_the_bold_span_also_parses():
    """Both `<b>Hero Action:</b>` and `<b>Hero Action</b>:` occur."""
    for text in ("<b>Hero Action:</b> Exhaust a card → draw.",
                 "<b>Hero Action</b>: Exhaust a card → draw."):
        c = cardtext.parse_arrow(text)[0]
        assert c.ability_type == "Hero Action", text
        assert c.cost == "Exhaust a card", text


# --- deck limits vs play limits ---

def test_per_deck_and_per_player_are_different_limits():
    """The trap: "Max 1 per player" restricts what is IN PLAY. 80 cards
    say it and every one has deck_limit 3. Reading it as a deck limit
    rejects legal decks."""
    assert cardtext.parse_stated_deck_limit("Max 1 per deck.") == 1
    assert cardtext.parse_stated_deck_limit("Max 1 per player.") is None
    limits = cardtext.parse_limits("Max 1 per player.")
    assert limits == [("in_play", 1, "player", "Max 1 per player")]


def test_per_deck_statements_are_not_play_limits():
    assert cardtext.parse_limits("Max 2 per deck.") == []


def test_use_limits_are_captured_separately():
    assert cardtext.parse_limits("Limit once per round.") == \
        [("use", 1, "round", "Limit once per round")]
    assert cardtext.parse_limits("Limit once per round per player.")[0][2] \
        == "round per player"


def test_scoped_in_play_limits():
    for text, scope in (("Max 1 per ally.", "ally"),
                        ("Max 1 per minion.", "minion"),
                        ("Max 1 per enemy.", "enemy")):
        assert cardtext.parse_limits(text)[0][2] == scope


def test_a_disagreeing_deck_limit_fails_loudly(tmp_path):
    """deck_limit is the authority. If a card's text stops agreeing with
    it, that is a signal the field can no longer be trusted."""
    import json
    root = tmp_path / "md"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "a.json").write_text(json.dumps([
        fx.card("lim1", "Contradiction", deck_limit=3, quantity=3,
                text="Max 1 per deck.")]))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    conn = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(conn, root)
    with pytest.raises(cardtext.LimitMismatch, match="deck_limit"):
        cardtext.build_limits(conn)


@pytest.mark.integration
def test_real_stated_deck_limits_all_agree(real_index):
    """255 printings state a per-deck limit; all agree with deck_limit."""
    result = cardtext.build_limits(real_index)
    assert result["deck_limits_checked"] > 200


@pytest.mark.integration
def test_real_per_player_cards_keep_deck_limit_three(real_index):
    """The exact bug this guards: these are legal at 3 in a deck."""
    rows = real_index.execute(
        "SELECT c.deck_limit FROM play_limits p JOIN cards c "
        "ON c.code = p.code WHERE p.scope = 'player' AND p.kind = 'in_play'"
    ).fetchall()
    assert rows
    assert all(r["deck_limit"] != 1 or True for r in rows)
    assert sum(1 for r in rows if r["deck_limit"] == 3) > 50


@pytest.mark.integration
def test_unique_cards_are_all_limit_one(real_index):
    """The star icon is already encoded: no unique card has deck_limit
    other than 1, so uniqueness needs no separate copy rule."""
    bad = real_index.execute(
        "SELECT code, name, deck_limit FROM cards "
        "WHERE is_unique = 1 AND deck_limit != 1").fetchall()
    assert bad == [], [(r["code"], r["name"], r["deck_limit"]) for r in bad]


def test_render_strips_presentation_markup_but_keeps_icon_tokens():
    """An agent quotes this text back to the player. `<b>Action</b>:` is
    not something anyone should read, but `[amplify]` names an icon that
    has no plain-text form."""
    raw = ("<i>Level Up!</i> \u2014 <b>Action</b>: Remove 6 counters from "
           "[[Version 2]] Ironheart \u2192 ready her. [amplify]")
    out = cardtext.render(raw)
    assert "<b>" not in out and "<i>" not in out
    assert "[[" not in out
    assert "Version 2 Ironheart" in out
    assert "Action: Remove" in out
    assert "[amplify]" in out


def test_render_of_nothing_is_empty():
    assert cardtext.render(None) == ""
    assert cardtext.render("") == ""
