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
    rules_chunk.Entry("Card Anatomy", "Listed in the index at page 52.",
                      52, "rules-reference", entry_addressable=False),
    rules_chunk.Entry("Setup", "Follow these steps in order.", 3,
                      "learn-to-play", entry_addressable=False),
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
    """A citation with no rules text is not an answer."""
    assert all(h["entry_addressable"] for h in rules.search(conn, "index"))


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
    for q in ("villain attack", "confused", "boost icon"):
        for hit in rules.search(real_index, q):
            assert hit["page"] is not None, (q, hit["term"])
            assert hit["entry_addressable"], (q, hit["term"])


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
