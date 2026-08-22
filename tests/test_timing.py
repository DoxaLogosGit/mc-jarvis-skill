"""Trigger timing and priority.

The chart is parsed from the RR rather than transcribed, so most of these
tests are about the parse holding up and about a revision upstream being
reported instead of silently absorbed.
"""
import re

import pytest

from mc_jarvis import index, rules_chunk, timing

# Reproduced from the extracted Rules Reference: the chart sits at the end
# of the ABILITY body, after the bullet that governs quoted triggers.
ABILITY = """Simultaneous Timing Priority — Some abilities have
timing priority over other abilities. In order, the timing
priority of abilities with the same triggering condition is:
1. Constant abilities, delayed effects, and lasting effects.
2. Interrupts
a. Status card “Forced Interrupt” abilities.
b. “Forced Interrupt” abilities.
c. “Interrupt” abilities.
3. “Boost” and “When Revealed” abilities.
4. Responses
a. “Forced Response” abilities.
b. “Response” abilities.
5. Consequential damage."""

QUOTED_RULE = (
    "If quotation marks are used around a timing trigger and colon, "
    "the quoted text is not itself a timing trigger, but is instead "
    "referring to other abilities with that trigger.\n"
)

# Verbatim from the indexed RR, wrapped exactly as extracted. Step 6's
# See: list wraps onto a second line and step 10 has no See: at all -
# both are the whole point of the round-structure tests below.
ROUND_OVERVIEW = """The following is an overview of a game round, and the
glossary entries that cover each part of the game round.
1. Player phase begins. See: Player Phase
2. Each player takes a turn. See: Player Turn
3. Player phase ends. See: End of Player Phase
4. Villain phase begins. See: Villain Phase
5. Place threat on main scheme. See: Main Scheme
6. Villain and minions activate. See: Activation, Attack
(Enemy Activation), Scheme (Enemy Activation)
7. Deal encounter cards. See: Deal
8. Reveal and resolve encounter cards. See: Reveal
9. Pass the first player token. See: First Player
10. End the round. Proceed to step one of the next game
round."""


def _entry(term, body, page):
    return rules_chunk.Entry(term, body, page, "marvel-champions-rules-reference")


@pytest.fixture
def conn(tmp_path):
    c = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(c, [
        _entry("Ability", QUOTED_RULE + ABILITY, 4),
        _entry("Round Overview", ROUND_OVERVIEW, 4),
        _entry(
            "Forced",
            "For any given triggering condition, forced interrupts take "
            "priority and initiate before non-forced interrupts. If two or "
            "more forced abilities would initiate at the same moment, the "
            "first player determines the order in which the abilities "
            "initiate. Each forced ability must resolve as completely as "
            "possible before the next forced ability may initiate.", 20),
        _entry(
            "First Player",
            "The first player has the first opportunity to use an "
            "interrupt at each appropriate game moment.", 19),
        _entry(
            "Interrupt",
            "Interrupts that use the word “would” resolve before "
            "its triggering condition initiates.", 25),
        _entry(
            "Response",
            "If a single effect causes multiple triggering conditions to "
            "occur, responses to each of those triggering conditions can "
            "be resolved in any order.", 38),
        _entry(
            "Simultaneous Resolution",
            "If two or more effects with the same bold timing trigger "
            "would resolve simultaneously, the first player determines the "
            "order in which the effects resolve.", 40),
        _entry(
            "Status Cards",
            "Status card abilities have timing priority over all "
            "conflicting triggered abilities.", 41),
        _entry(
            "Resource Ability",
            "A resource ability is identified by the bold "
            "“Resource” timing trigger.", 37),
        _entry("Special", "A special ability has no timing trigger.", 40),
        _entry("Setup (Triggered Ability)",
               "Setup abilities resolve during setup.", 40),
        _entry(
            "When Defeated Abilities",
            "The “When Defeated” timing trigger is equivalent to "
            "the following trigger: “Forced Interrupt: When this card "
            "is defeated...”", 48),
        _entry(
            "When Completed Abilities",
            "The “When Completed” timing trigger is equivalent to "
            "the following trigger: “Forced Interrupt: When this "
            "scheme is completed...”", 48),
    ])
    timing.build(c)
    return c


# --- the chart -------------------------------------------------------

def test_chart_parses_into_ten_rows(conn):
    rows = timing.chart(conn)
    assert len(rows) == 10
    assert rows[0]["rung"] == 1
    assert rows[-1]["rung"] == 5


def test_chart_captures_lettered_sub_tiers(conn):
    subs = [(r["rung"], r["sub"]) for r in timing.chart(conn) if r["sub"]]
    assert subs == [(2, "a"), (2, "b"), (2, "c"), (4, "a"), (4, "b")]


def test_parsed_chart_matches_the_expected_chart(conn):
    """A revision upstream must be reported, not silently absorbed."""
    assert timing.verify_chart(conn) == []


def test_a_changed_chart_is_reported(conn):
    conn.execute("UPDATE rules_entries SET body = 'Rewritten.' "
                 "WHERE term = 'Ability'")
    conn.commit()
    timing.build(conn)
    assert timing.verify_chart(conn)


def test_status_card_forced_interrupts_outrank_ordinary_ones(conn):
    rows = {(r["rung"], r["sub"]): r["text"] for r in timing.chart(conn)}
    assert "Status card" in rows[(2, "a")]
    assert "Status card" not in rows[(2, "b")]


def test_the_orderable_chart_excludes_category_headers(conn):
    """Rungs 2 and 4 are bare headers over their lettered tiers. Including
    them makes `explain` say a Response resolves after "Responses"; the
    2026-08-21 draft instead dropped every un-lettered rung, which lost
    rungs 1 and 5 entirely. Eight rows is what both bugs fail."""
    rows = timing.orderable(conn)
    assert [(r["rung"], r["sub"]) for r in rows] == [
        (1, None), (2, "a"), (2, "b"), (2, "c"),
        (3, None), (4, "a"), (4, "b"), (5, None)]


# --- classification --------------------------------------------------

def test_plain_trigger_classifies(conn):
    t = timing.classify("Response")
    assert t.canonical == "Response"
    assert (t.rung, t.sub) == (4, "b")
    assert t.forced is False


def test_forced_response_outranks_response(conn):
    forced, plain = timing.classify("Forced Response"), timing.classify("Response")
    assert forced.forced is True
    assert (forced.rung, forced.sub) < (plain.rung, plain.sub)


def test_all_interrupts_precede_all_responses(conn):
    for i in ("Forced Interrupt", "Interrupt"):
        for r in ("Forced Response", "Response"):
            assert timing.classify(i).rung < timing.classify(r).rung


def test_when_revealed_is_its_own_rung_not_a_forced_interrupt(conn):
    """The chart puts it on rung 3 with Boost. The RR states the Forced
    Interrupt equivalence for When Defeated and When Completed only."""
    wr = timing.classify("When Revealed")
    assert wr.canonical == "When Revealed"
    assert wr.rung == 3
    assert wr.rung > timing.classify("Forced Interrupt").rung


def test_when_defeated_and_completed_are_forced_interrupts(conn):
    for alias in ("When Defeated", "When Completed"):
        c = timing.classify(alias)
        assert c.canonical == "Forced Interrupt", alias
        assert (c.rung, c.sub) == (2, "b"), alias
        assert c.forced is True, alias


def test_boost_is_a_trigger_not_flavour_text(conn):
    """Boost is bold on 430 cards; the chart makes it rung 3."""
    assert timing.classify("Boost").rung == 3


def test_form_qualifier_is_split_from_the_trigger(conn):
    t = timing.classify("Hero Action")
    assert t.qualifier == "Hero"
    assert t.canonical == "Action"
    assert t.rung is None      # actions are not on the chart


def test_qualifier_matches_case_insensitively(conn):
    """27131 Common Criminal and 25034 Leadership Training print
    "Alter-ego Action" with a lower-case second word."""
    t = timing.classify("Alter-ego Action")
    assert t.qualifier == "Alter-Ego"
    assert t.canonical == "Action"


def test_parenthetical_qualifier_is_handled(conn):
    t = timing.classify("When Revealed (Hero)")
    assert t.canonical == "When Revealed"
    assert t.qualifier == "Hero"


def test_an_unlisted_parenthetical_is_kept_verbatim(conn):
    """"When Revealed (Norman Osborn)" is a When Revealed. Requiring the
    parenthetical to be a known form drops it, and drops the mis-set
    "(Alter_Ego)" on 32070 with it."""
    for paren in ("Norman Osborn", "Alter_Ego"):
        t = timing.classify(f"When Revealed ({paren})")
        assert t.canonical == "When Revealed", paren
        assert t.qualifier == paren, paren


def test_a_parenthetical_on_a_non_trigger_is_still_rejected(conn):
    assert timing.classify("Nonsense (Hero)") is None


def test_forced_is_a_modifier_not_only_a_prefix(conn):
    """"Forced Action" is on 11 cards. It is an Action that is forced -
    not a trigger of its own, and not unclassifiable."""
    t = timing.classify("Forced Action")
    assert t.canonical == "Action"
    assert t.forced is True
    assert t.rung is None


def test_forced_interrupt_keeps_its_own_rung(conn):
    """The full prefix must be checked before "Forced " is stripped, or
    Forced Interrupt collapses onto Interrupt's rung 2c."""
    t = timing.classify("Forced Interrupt")
    assert t.canonical == "Forced Interrupt"
    assert (t.rung, t.sub) == (2, "b")


def test_a_quoted_trigger_is_a_reference_not_a_trigger(conn):
    """RR, ABILITY: a quoted timing trigger refers to other abilities with
    that trigger. Stripping the quotes makes "Boost" a rung-3 ability on a
    card that has no Boost ability."""
    t = timing.classify('"Boost"')
    assert t.quoted is True
    assert t.canonical == "Boost"
    plain = timing.classify("Boost")
    assert plain.quoted is False


def test_a_quoted_trigger_with_inner_punctuation_classifies(conn):
    t = timing.classify('"Hero Response."')
    assert t.quoted is True
    assert t.canonical == "Response"
    assert t.qualifier == "Hero"


def test_misprints_are_corrected_by_name(conn):
    for printed, canonical in (("Hero Reponse", "Response"),
                               ("When Reveled (Hero)", "When Revealed")):
        t = timing.classify(printed)
        assert t is not None, printed
        assert t.canonical == canonical, printed


def test_inner_markup_is_stripped_before_classifying(conn):
    """BOLD_RE captures whatever is inside <b>...</b>, italics included."""
    assert timing.classify("<i>Give to the Tony Stark player.</i>") is None


def test_bold_text_that_is_not_a_trigger_is_rejected(conn):
    for s in ("Contents", "Expert Mode Only.", "Elite", "TRAITS",
              "the players win the game", "Nonsense"):
        assert timing.classify(s) is None, s


def test_not_trigger_patterns_cover_their_real_variants(conn):
    for s in ("Give to the Tony Stark player.",
              "Give to Nebula player.",
              "Give to the Anna Marie player",
              "Give to the Clint Barton Player.",
              "Wrecker's Side Scheme.",
              "Proxima Midnight's Scheme."):
        assert timing.classify(s) is None, s


def test_no_trigger_matches_a_not_trigger_pattern(conn):
    """What makes a pattern a rule rather than a wildcard: no trigger this
    reference knows may match one. A release that adds a trigger the
    patterns would swallow fails here."""
    config = timing.load_config()
    known = (set(config["triggers"]) | set(config["outside_chart"])
             | set(config["aliases"]))
    for pattern in config["not_trigger_patterns"]:
        rx = re.compile(pattern)
        for name in sorted(known):
            for form in (name, f"Hero {name}", f"{name} (Hero)"):
                assert not rx.match(form), f"{pattern!r} swallows {form!r}"


def test_a_compound_prefix_yields_one_trigger_per_ability(conn):
    """59042 Hecate prints "When Revealed/Defeated" - one prefix, two
    abilities, on two different rungs. Returning one of them loses an
    ability; returning none makes it look unclassifiable."""
    got = timing.classify_all("When Revealed/Defeated")
    assert [(t.canonical, t.rung, t.sub) for t in got] == [
        ("When Revealed", 3, None), ("Forced Interrupt", 2, "b")]
    assert all(t.raw == "When Revealed/Defeated" for t in got)


def test_classify_all_returns_one_trigger_for_an_ordinary_prefix(conn):
    assert [t.canonical for t in timing.classify_all("Hero Response")] \
        == ["Response"]


def test_classify_all_is_empty_for_a_non_trigger(conn):
    assert timing.classify_all("Contents") == []


def test_known_non_triggers_are_distinguished_from_gaps(conn):
    """The build records an unclassifiable prefix so the gate can name it,
    and skips a decided non-trigger. Conflating the two hides new
    triggers."""
    assert timing.is_known_non_trigger("Contents")
    assert timing.is_known_non_trigger("Give to the Tony Stark player.")
    assert not timing.is_known_non_trigger("Some New Trigger")


# --- citations -------------------------------------------------------

def test_citations_verify_against_the_indexed_rules(conn):
    assert timing.verify_citations(conn) == []


def test_a_reworded_rules_entry_fails_loudly(conn):
    conn.execute("UPDATE rules_entries SET body = 'Rewritten.' "
                 "WHERE term = 'Forced'")
    conn.commit()
    broken = timing.verify_citations(conn)
    assert any("Forced" in b for b in broken)


def test_pages_come_from_the_index_not_the_config(conn):
    """The 2026-08-21 config hard-coded Ability p.5 and First Player p.20;
    the indexed RR says 4 and 19. Reading the page keeps `timing` and
    `rules show` from disagreeing."""
    assert "rr_page" not in timing.load_config()["chart_source"]
    assert timing.page(conn, "Ability") == 4
    assert timing.page(conn, "First Player") == 19


def test_a_missing_page_is_named_not_printed_as_none(conn):
    conn.execute("UPDATE rules_entries SET page = NULL WHERE term = 'Forced'")
    conn.commit()
    assert timing.page(conn, "Forced") is None
    assert timing.cite(conn, "Forced") == "[RR Forced, page not indexed]"


# --- explain ---------------------------------------------------------

def test_explain_reports_what_beats_what(conn):
    result = timing.explain(conn, "Response")
    assert result["rung"] == 4
    befores = [b["text"] for b in result["resolves_after"]]
    assert any("Forced Response" in b for b in befores)


def test_explain_includes_the_unlettered_rungs(conn):
    """Rung 1 outranks every trigger and rung 5 follows every one. Filtering
    on a lettered sub-tier hid both."""
    result = timing.explain(conn, "Interrupt")
    assert any("Constant abilities" in r["text"] for r in result["resolves_after"])
    assert any("Consequential damage" in r["text"]
               for r in result["resolves_before"])


def test_explain_does_not_report_a_category_header(conn):
    result = timing.explain(conn, "Response")
    texts = [r["text"] for r in
             result["resolves_after"] + result["resolves_before"]]
    assert "Responses" not in texts
    assert "Interrupts" not in texts


def test_explain_accepts_an_alias(conn):
    assert timing.explain(conn, "When Defeated")["canonical"] \
        == "Forced Interrupt"


def test_explain_of_an_off_chart_trigger_orders_nothing(conn):
    result = timing.explain(conn, "Action")
    assert result["rung"] is None
    assert result["resolves_before"] == []
    assert result["resolves_after"] == []


def test_an_off_chart_trigger_cites_its_own_entry(conn):
    """An Action is not on the chart, so citing ABILITY sends a player to a
    list their trigger is absent from."""
    assert timing.explain(conn, "Hero Action")["governing_entry"] == "Forced"
    assert timing.explain(conn, "Response")["governing_entry"] == "Ability"


def test_forced_action_reports_itself_as_forced(conn):
    assert timing.explain(conn, "Forced Action")["forced"] is True


def test_unknown_trigger_is_reported_not_guessed(conn):
    assert timing.explain(conn, "Bamf")["canonical"] is None


# --- the game round --------------------------------------------------

def test_round_structure_has_ten_steps(conn):
    steps = timing.round_structure(conn)
    assert len(steps) == 10
    assert steps[0]["step"] == 1
    assert steps[-1]["step"] == 10


def test_the_final_step_has_no_see_clause(conn):
    """Step 10 names no glossary entry. A regex that requires See: drops
    it, and `all(s["see"])` fails on a correct parse."""
    steps = timing.round_structure(conn)
    assert steps[-1]["see"] == []
    assert steps[-1]["description"].startswith("End the round.")
    assert sum(1 for s in steps if s["see"]) == 9


def test_a_wrapped_see_list_is_not_truncated(conn):
    """Step 6's See: list wraps onto a second line. Parsing line-by-line
    captures "Activation, Attack" and silently drops the rest."""
    step6 = timing.round_structure(conn)[5]
    assert step6["see"] == ["Activation", "Attack (Enemy Activation)",
                            "Scheme (Enemy Activation)"]


# --- the real corpus -------------------------------------------------

@pytest.mark.integration
def test_real_corpus_triggers_are_classified(real_index):
    """Every bold prefix on a card either classifies or is on the
    not_triggers list. A new release adding a trigger fails here."""
    rows = real_index.execute(
        "SELECT DISTINCT raw_prefix FROM timing_triggers "
        "WHERE canonical IS NULL").fetchall()
    assert [r["raw_prefix"] for r in rows] == []


@pytest.mark.integration
def test_real_chart_and_citations_verify(real_index):
    assert timing.verify_chart(real_index) == []
    assert timing.verify_citations(real_index) == []


@pytest.mark.integration
def test_real_round_structure(real_index):
    steps = timing.round_structure(real_index)
    assert len(steps) == 10
    assert sum(1 for s in steps if s["see"]) == 9
    assert len(steps[5]["see"]) == 3


@pytest.mark.integration
def test_real_quoted_triggers_are_marked_as_references(real_index):
    """15 rows across 13 cards quote a trigger; none has that ability.

    An exact count, not `> 0`: a regression that caught only one quote
    form would leave `> 0` green, and so would a release adding a
    sixteenth."""
    n = real_index.execute(
        "SELECT COUNT(*) FROM timing_triggers WHERE quoted = 1").fetchone()[0]
    assert n == 15
    cards = real_index.execute(
        "SELECT COUNT(DISTINCT code) FROM timing_triggers "
        "WHERE quoted = 1").fetchone()[0]
    assert cards == 13


@pytest.mark.integration
def test_the_prefix_cutoff_sits_in_measured_empty_space(real_index):
    """`max_prefix_chars` drops bold spans without classifying them, which
    is exactly the shape of filter that hid the blank rules entries. It is
    allowed only while nothing lives near it: the longest span that
    classifies is 29 characters and the shortest that does not is 41."""
    from mc_jarvis.cardtext import BOLD_RE
    longest_ok, shortest_prose = 0, 10_000
    for row in real_index.execute(
            "SELECT text FROM cards WHERE text IS NOT NULL"):
        for raw in BOLD_RE.findall(row["text"] or ""):
            prefix = timing._norm(timing.TAG_RE.sub("", raw))
            # Compound keys are exempt from the cutoff by design, so they
            # say nothing about where it may sit.
            if (not prefix or timing.is_known_non_trigger(prefix)
                    or prefix in timing.load_config()["compounds"]):
                continue
            if timing.classify_all(prefix):
                longest_ok = max(longest_ok, len(prefix))
            else:
                shortest_prose = min(shortest_prose, len(prefix))
    assert longest_ok == 29
    assert shortest_prose == 41
    assert longest_ok < timing.load_config()["max_prefix_chars"] < shortest_prose


@pytest.mark.integration
def test_malformed_markup_still_yields_its_triggers(real_index):
    """21147 Hela's Crown prints `<b>Forced Response<b>:`, so the bold span
    runs on and swallows the card's Boost trigger too. Both are recovered."""
    rows = real_index.execute(
        "SELECT canonical FROM timing_triggers WHERE code = '21147' "
        "ORDER BY ordinal").fetchall()
    assert [r["canonical"] for r in rows] == ["Forced Response", "Boost"]


@pytest.mark.integration
def test_no_not_trigger_pattern_swallows_a_real_prefix(real_index):
    """The config-key check cannot speak for a prefix FFG prints later.
    This one checks the patterns against every prefix that classifies in
    the corpus as it actually stands."""
    config = timing.load_config()
    patterns = [re.compile(p) for p in config["not_trigger_patterns"]]
    for row in real_index.execute(
            "SELECT DISTINCT raw_prefix FROM timing_triggers "
            "WHERE canonical IS NOT NULL"):
        for rx in patterns:
            assert not rx.match(row["raw_prefix"]), \
                f"{rx.pattern!r} swallows {row['raw_prefix']!r}"
