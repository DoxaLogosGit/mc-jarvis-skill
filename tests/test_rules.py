import json

import pytest

from mc_jarvis import cardtext, index, rules, rules_chunk
from tests.fixtures import cards as fx

_ENTRIES = [
    rules_chunk.Entry("Toughness", "A tough status card absorbs the next "
                      "damage.", 41, "rules-reference"),
    rules_chunk.Entry("Retaliate", "After this character defends, deal "
                      "damage to the attacker.", 36, "rules-reference"),
    rules_chunk.Entry("Cost Arrow Icon ( →)", "A cost arrow icon "
                      "distinguishes a cost from an effect.", 14,
                      "rules-reference"),
    # An unresolved index line: a citation with no rules text. Neither
    # addressable nor searchable.
    rules_chunk.Entry("Card Anatomy", "Listed in the index at page 52.",
                      52, "rules-reference",
                      entry_addressable=False, searchable=False),
    # A page-chunked rulebook page: not addressable by entry name, but
    # searchable (spec §9). The fixture has to say which it is - the two
    # were one flag until 2026-08-22, and that is what broke search.
    rules_chunk.Entry("Setup", "Follow these steps in order.", 3,
                      "learn-to-play",
                      entry_addressable=False, searchable=True),
]


@pytest.fixture
def entries():
    return list(_ENTRIES)


@pytest.fixture
def conn(tmp_path, entries):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.ARROW_CARDS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    cardtext.build(c)
    rules_chunk.store(c, entries)
    rules.build_links(c)
    return c


def test_show_returns_body_and_page(conn):
    result = rules.show(conn, "Toughness")
    assert result["page"] == 41
    assert "absorbs" in result["body"]
    assert result["source_doc"] == "rules-reference"


def test_show_is_case_insensitive(conn):
    assert rules.show(conn, "toughness")["term"] == "Toughness"


def test_a_plain_name_finds_an_icon_bearing_entry(conn):
    """Entry terms carry their icon - "Cost Arrow Icon ( →)" - but a
    player types the plain name."""
    result = rules.show(conn, "Cost Arrow Icon")
    assert result["term"].startswith("Cost Arrow Icon")
    assert result["page"] == 14


def test_show_lists_cards_using_the_keyword(conn):
    codes = {c["code"] for c in rules.show(conn, "Toughness")["cards"]}
    assert "arw05" in codes


def test_show_of_an_unknown_term_suggests_a_search(conn):
    result = rules.show(conn, "Quantum Flux")
    assert result["term"] is None
    assert result["suggestions"] is not None


def test_a_pointer_entry_is_labelled_not_silently_empty(conn):
    """It carries a citation but no rules text, so the CLI must say so."""
    result = rules.show(conn, "Card Anatomy")
    assert result["entry_addressable"] is False
    assert result["body"]
    assert "(page pointer)" in rules._cite(result)


def test_an_addressable_entry_wins_over_a_pointer(tmp_path):
    conn = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(conn, [
        rules_chunk.Entry("Guard", "", 12, "rr", entry_addressable=False),
        rules_chunk.Entry("Guard", "Real text.", 12, "rr2"),
    ])
    assert rules.show(conn, "Guard")["body"] == "Real text."


def test_search_results_all_carry_a_citation(conn):
    hits = rules.search(conn, "damage")
    assert hits
    for h in hits:
        assert h["source_doc"] and h["page"] is not None


def test_pointers_do_not_appear_in_search(conn):
    """A citation with no rules text is not an answer. Page-chunked
    rulebook pages are a different thing and must still be found - see
    `test_page_chunked_content_is_searchable`."""
    assert all(h["searchable"] for h in rules.search(conn, "index"))
    assert not any(h["term"] == "Card Anatomy"
                   for h in rules.search(conn, "listed index page"))


def test_search_handles_punctuation_without_a_syntax_error(conn):
    for q in ["Sp//dr", 'a "quote"', "AND", "-"]:
        rules.search(conn, q)


def test_explain_expands_a_cards_keywords(conn):
    assert {k["term"] for k in rules.explain(conn, "arw05")} >= \
        {"Toughness", "Retaliate"}


def test_explain_of_a_keywordless_card_is_empty(conn):
    assert rules.explain(conn, "arw01") == []


def test_links_never_point_at_a_pointer_entry(conn):
    """`card show --explain` must not print a card's keyword with no
    rules text under it."""
    rows = conn.execute(
        "SELECT l.term FROM card_rules_links l JOIN rules_entries e "
        "ON e.term = l.term WHERE e.entry_addressable = 0").fetchall()
    assert rows == []


@pytest.mark.integration
def test_real_keyword_entries_resolve(real_index):
    for term in ("Overkill", "Retaliate", "Piercing", "Surge", "Guard"):
        result = rules.show(real_index, term)
        assert result["term"] is not None, term
        assert result["page"] is not None, term
        assert result["body"].strip(), term


@pytest.mark.integration
def test_real_cards_link_to_their_keywords(real_index):
    result = rules.show(real_index, "Overkill")
    assert len(result["cards"]) > 10


@pytest.mark.integration
def test_every_real_search_hit_can_be_cited(real_index):
    """Every hit needs a page. It does not need to be a glossary entry -
    a page-chunked rulebook page cites fine and must be findable. This
    asserted `entry_addressable` and passed only because Learn to Play
    was missing from the development index entirely."""
    for q in ("villain attack", "confused", "boost icon"):
        for hit in rules.search(real_index, q):
            assert hit["page"] is not None, (q, hit["term"])
            assert hit["searchable"], (q, hit["term"])


def test_plain_term_strips_printed_decoration():
    """The RR titles entries as printed - "Retaliate X",
    "Cost Arrow Icon ( →)" - while players ask for the bare word."""
    assert rules.plain_term("Retaliate X") == "retaliate"
    assert rules.plain_term("Cost Arrow Icon ( →)") == "cost arrow icon"
    assert rules.plain_term("Amplify Icon ([amplify])") == "amplify icon"
    assert rules.plain_term("Overkill") == "overkill"


def test_a_keyword_with_a_numeric_placeholder_is_found(tmp_path):
    conn = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(conn, [rules_chunk.Entry(
        "Retaliate X", "After this character is attacked, deal X damage.",
        38, "rr")])
    assert rules.show(conn, "Retaliate")["page"] == 38
    assert rules.show(conn, "retaliate x")["page"] == 38


def test_page_chunked_content_is_searchable(tmp_path):
    """spec §9: a rulebook without an alphabetical index is "searchable,
    just not addressable by entry". Filling the FTS table off
    `entry_addressable` instead of `searchable` silently cost Learn to
    Play all 24 of its pages - the rows were stored, and `MATCH` found
    none of them."""
    from mc_jarvis import index, rules, rules_chunk

    conn = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(conn, rules_chunk.chunk_pages(
        ["COVER", "The villain activates after every player turn."],
        source_doc="learn-to-play"))
    hits = rules.search(conn, "villain activates")
    assert [h["source_doc"] for h in hits] == ["learn-to-play"]
    assert hits[0]["entry_addressable"] is False
    assert hits[0]["searchable"] is True


def test_an_unresolved_pointer_stays_out_of_search(tmp_path):
    """The other half of the same distinction: a pointer carries a
    citation and no rules text, so it must not surface as a hit."""
    from mc_jarvis import index, rules, rules_chunk

    conn = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(conn, [rules_chunk.Entry(
        "Card Anatomy", "Listed in the index at page 52.", 52,
        "marvel-champions-rules-reference",
        entry_addressable=False, searchable=False)])
    assert rules.search(conn, "listed index page") == []


def test_a_rulebook_page_is_not_labelled_a_page_pointer():
    """Both are non-addressable, and labelling off `entry_addressable`
    alone called every Learn to Play page a "page pointer"."""
    page = rules._cite({"page": 6, "source_doc": "learn-to-play",
                        "entry_addressable": False, "searchable": True})
    pointer = rules._cite({"page": 52, "source_doc": "rr",
                           "entry_addressable": False, "searchable": False})
    entry = rules._cite({"page": 31, "source_doc": "rr",
                         "entry_addressable": True, "searchable": True})
    assert "page pointer" not in page and "rulebook" in page
    assert "page pointer" in pointer
    assert entry == "[rr p.31]"


@pytest.mark.integration
def test_every_page_chunked_row_in_the_real_index_is_searchable(real_index):
    """Guards the regression at the level it actually happened: whatever
    rulebooks the index holds, none of their page-chunked rows may be
    stored-but-unfindable."""
    rows = real_index.execute(
        "SELECT source_doc, COUNT(*) n FROM rules_entries "
        "WHERE entry_addressable = 0 AND searchable = 1 "
        "GROUP BY source_doc").fetchall()
    for r in rows:
        found = real_index.execute(
            "SELECT COUNT(*) FROM rules_fts f "
            "JOIN rules_entries e ON e.id = f.rowid "
            "WHERE rules_fts MATCH 'the OR a OR of' "
            "  AND e.source_doc = ?", (r["source_doc"],)).fetchone()[0]
        assert found > 0, f"{r['source_doc']}: {r['n']} rows, 0 searchable"


@pytest.mark.integration
def test_the_appendices_are_reachable(real_index):
    """`_headers` stopped at page 49 and the appendices start there, so 22
    pages of the Rules Reference were invisible to every rules command -
    which is how this project came to claim the RR states no deck size.

    All six, by name, from a document already on disk.
    """
    terms = {r["term"] for r in real_index.execute(
        "SELECT term FROM rules_entries WHERE term LIKE 'Appendix%'")}
    assert terms == {
        "Appendix I: Deck Customization", "Appendix II: Setup",
        "Appendix III: Card Anatomy", "Appendix IV: FAQ",
        "Appendix V: Errata", "Appendix VI: Game Environments (Beta)"}


@pytest.mark.integration
def test_the_deck_size_rule_is_now_findable(real_index):
    """The specific claim that was wrong: the Rules Reference does state
    both bounds, in Appendix I."""
    row = real_index.execute(
        "SELECT body, page FROM rules_entries "
        "WHERE term = 'Appendix I: Deck Customization'").fetchone()
    flat = " ".join(row["body"].split())
    assert "minimum of 40 cards" in flat
    assert "maximum of 50 cards" in flat
    assert row["page"] == 49


@pytest.mark.integration
def test_the_faq_is_indexed_question_by_question(real_index):
    """102 Q&A pairs, against the 8 designer rulings tracked separately.
    They are clarifications of what this edition already says - part of
    the rules, versioned with the document - which is why they live here
    and not in `rulings`.
    """
    rows = real_index.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT page) pages FROM rules_entries "
        "WHERE term LIKE 'FAQ:%'").fetchone()
    assert rows["n"] > 90, rows["n"]
    # Spread across the FAQ's real pages, not all filed under its first.
    assert rows["pages"] >= 8, rows["pages"]


@pytest.mark.integration
def test_a_faq_answer_is_searchable_and_cites_a_real_page(real_index):
    hit = real_index.execute(
        "SELECT term, page FROM rules_entries "
        "WHERE term LIKE 'FAQ:%Webbed Up%' LIMIT 1").fetchone()
    assert hit is not None
    assert 56 <= hit["page"] <= 64, dict(hit)


@pytest.mark.integration
def test_errata_is_indexed_per_card(real_index):
    """48 official card corrections. marvelsdb already applies them to
    card text - checked against Warning, Sanctuary, Aragorn and Armor Up
    - so these are provenance rather than a correction the tool must
    make itself."""
    n = real_index.execute(
        "SELECT COUNT(*) FROM rules_entries WHERE term LIKE 'Errata:%'"
    ).fetchone()[0]
    assert n > 40, n
    loki = real_index.execute(
        "SELECT body FROM rules_entries WHERE term LIKE 'Errata: Loki%'"
    ).fetchone()
    assert loki and "Forced Interrupt" in loki["body"]


def test_a_truncated_rules_search_says_so(conn):
    """`rules search damage` returned 10 entries against 113 that match
    and said nothing about the other 103. A rules answer is the one place
    this tool must not look exhaustive when it is not."""
    hits = rules.search(conn, "the", limit=1)
    if len(hits) == 1:
        assert hits.truncated in (True, False)
    wide = rules.search(conn, "the", limit=500)
    narrow = rules.search(conn, "the", limit=max(1, len(wide) - 1))
    if len(wide) > 1:
        assert narrow.truncated is True
    assert wide.truncated is False
