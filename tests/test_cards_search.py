import json

import pytest

from mc_jarvis import cards, index
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    pack = fx.PACK + fx.REPRINTS + [
        fx.card("tst10", "Web Shooter", type_code="upgrade",
                faction_code="hero", text="Exhaust to web an enemy.",
                traits="Tech.", cost=1),
        fx.card("tst11", "Aerial Strike", type_code="event",
                faction_code="aggression", text="Deal 3 damage.",
                traits="Attack.", cost=2),
    ]
    (root / "pack" / "tst.json").write_text(json.dumps(pack))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    return c


def test_full_text_matches_card_text(conn):
    assert "Web Shooter" in {h["name"] for h in cards.search(conn, "web")}


def test_filters_compose_with_the_query(conn):
    assert cards.search(conn, "damage", aspect="aggression")
    assert cards.search(conn, "damage", aspect="protection") == []


def test_filter_only_search_needs_no_query(conn):
    assert [h["code"] for h in cards.search(conn, None, type="upgrade")] \
        == ["tst10"]


def test_cost_filter_accepts_comparisons(conn):
    assert {h["code"] for h in cards.search(conn, None, cost="<=1")} == \
        {"rp001", "tst10"}
    assert {h["code"] for h in cards.search(conn, None, cost="2")} >= {"tst11"}


def test_bad_cost_filter_is_rejected_clearly(conn):
    with pytest.raises(ValueError, match="unparseable"):
        cards.search(conn, None, cost="cheap")


def test_limit_is_honoured(conn):
    assert len(cards.search(conn, None, limit=2)) == 2


def test_fts_special_characters_do_not_raise(conn):
    """A user query is not FTS5 syntax; `Sp//dr` and quotes must not
    become a syntax error."""
    for q in ["Sp//dr", 'a "quoted" thing', "AND", "foo*bar", "-"]:
        cards.search(conn, q)


def test_reprints_collapse_to_one_row(conn):
    """rp002 reprints rp001. One card, one result - not two."""
    hits = cards.search(conn, "Field Medic")
    assert [h["code"] for h in hits] == ["rp001"]


@pytest.mark.integration
def test_real_corpus_structural_query(real_index):
    hits = cards.search(real_index, None, aspect="justice", type="ally",
                        cost="<=2", limit=100)
    assert len(hits) > 5
    assert all(h["faction_code"] == "justice" for h in hits)


@pytest.mark.integration
def test_real_search_returns_no_duplicate_cards(real_index):
    for q in ("First Aid", "Energy", "Genius"):
        hits = cards.search(real_index, q, limit=50)
        codes = [h["code"] for h in hits]
        assert len(codes) == len(set(codes)), q
        exact = [h for h in hits if h["name"] == q]
        assert len(exact) <= 1, (q, exact)


def test_a_truncated_search_says_so(conn):
    """`--aspect justice` showed 20 rows against 134 matching cards and
    said nothing, so the result read as exhaustive. The limit must be
    visible or the answer is wrong by omission."""
    hits = cards.search(conn, limit=2)
    assert len(hits) == 2
    assert hits.truncated is True


def test_an_exhaustive_search_does_not_claim_more(conn):
    """Over-fetching by one distinguishes "exactly the limit" from "the
    first N of many"; without it a result of exactly the limit would
    always claim there was more."""
    everything = cards.search(conn, limit=500)
    assert not everything.truncated
    exact = cards.search(conn, limit=len(everything))
    assert len(exact) == len(everything)
    assert exact.truncated is False
