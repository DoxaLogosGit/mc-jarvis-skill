"""Designer rulings the Rules Reference does not yet cover (Task 18).

The whole feature turns on one comparison — is this ruling older than the
Rules Reference the user holds. A ruling older than the rulebook says what
the rulebook already says, so it is not stored at all; getting the
comparison wrong in that direction silently drops a live ruling that
contradicts the rulebook. That is the exact failure this exists to
prevent, so the date handling gets more tests than the parsing does.
"""
import datetime as dt

import pytest

from mc_jarvis import index, rules_chunk, rulings

# Shaped from the real page, 2026-08-23: a <blockquote> holds the player's
# question, the paragraphs after it hold the designer's answer, and a
# <strong>-Author – Date</strong> closes each ruling.
PAGE = """
<h2>March, 2026</h2>
<blockquote class="wp-block-quote">
<p>Does Sam Wilson take excess damage from an attack with overkill?</p>
</blockquote>
<p>No, Sam Wilson would not take any excess damage from &#8220;overkill&#8221;,
though we will need to update the rules to reflect this.</p>
<p><strong>-Alex &#8211; March 6, 2026</strong></p>

<blockquote class="wp-block-quote">
<p>Can a &#8220;Response&#8221; be used after the enemy is defeated?</p>
</blockquote>
<p>Yes. The window is still open.</p>
<p><strong>-Alex &#8211; August 1, 2026</strong></p>
"""

V18 = dt.date(2026, 7, 22)


@pytest.fixture
def conn(tmp_path):
    c = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(c, [
        rules_chunk.Entry("Overkill", "Deal excess damage to the identity.",
                          31, "marvel-champions-rules-reference"),
        rules_chunk.Entry("Response", "A response resolves after.", 38,
                          "marvel-champions-rules-reference"),
    ])
    return c


# --- parsing ---------------------------------------------------------

def test_parse_reads_question_answer_author_and_date():
    got = rulings.parse(PAGE, source_url="https://example.invalid/r")
    assert len(got.rulings) == 2
    first = got.rulings[0]
    assert "excess damage" in first.question
    assert first.answer.startswith("No, Sam Wilson")
    assert first.author == "Alex"
    assert first.ruled_on == dt.date(2026, 3, 6)
    assert first.source_url == "https://example.invalid/r"


def test_parse_unescapes_entities_and_strips_markup():
    first = rulings.parse(PAGE, source_url="u").rulings[0]
    assert "&#8220;" not in first.answer
    assert "<p>" not in first.answer
    assert "“overkill”" in first.answer


def test_a_page_that_parses_to_nothing_is_a_named_failure():
    """The trap this feature must not fall into: the page fetches, the
    markup has changed, and zero rulings reads as "no rulings" rather than
    as "the parser is broken". Same shape as MirrorLookup."""
    got = rulings.parse("<html><body>redesigned</body></html>",
                        source_url="u")
    assert got.status == "unparsed"
    assert got.rulings == []
    assert not got.ok


def test_a_page_that_parses_is_ok():
    assert rulings.parse(PAGE, source_url="u").status == "ok"


# --- the date that decides everything --------------------------------

def test_a_ruling_after_the_rules_reference_is_active():
    assert rulings.classify(dt.date(2026, 8, 1), V18) == "active"


def test_a_ruling_before_the_rules_reference_is_superseded():
    assert rulings.classify(dt.date(2026, 3, 6), V18) == "superseded"


def test_a_ruling_dated_the_same_day_stays_active():
    """The Rules Reference's text is frozen before it publishes, so a
    ruling issued that day cannot have been incorporated. It is also the
    fail-safe direction: retaining a ruling is a mild annoyance, dropping
    a live one is the failure this feature exists to prevent."""
    assert rulings.classify(V18, V18) == "active"


def test_without_a_rules_reference_date_everything_is_active():
    """Over-reporting is survivable. Silently dropping a live ruling that
    contradicts the rulebook is not."""
    assert rulings.classify(dt.date(2020, 1, 1), None) == "active"


# --- where that date comes from --------------------------------------

def test_the_pdf_modification_date_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(rulings, "_pdf_moddate", lambda p: V18)
    assert rulings.published_on(tmp_path, rr_version="1.8",
                                manifest_docs=[]) == V18


def test_a_manifest_date_for_a_different_edition_is_ignored(tmp_path,
                                                            monkeypatch):
    """After `take_current_rr` swaps in a newer edition, the manifest still
    describes the archived one. Comparing v1.8 rulings against v1.7's
    January date would mark live rulings superseded."""
    monkeypatch.setattr(rulings, "_pdf_moddate", lambda p: V18)
    docs = [{"slug": "marvel-champions-rules-reference",
             "url": ".../mc_rulesreference_v17-web.pdf",
             "date": "09 Jan 2026"}]
    assert rulings.published_on(tmp_path, rr_version="1.8",
                                manifest_docs=docs) == V18


def test_a_manifest_date_for_the_same_edition_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(rulings, "_pdf_moddate", lambda p: None)
    docs = [{"slug": "marvel-champions-rules-reference",
             "url": ".../mc_rulesreference_v18-web.pdf",
             "date": "22 Jul 2026"}]
    assert rulings.published_on(tmp_path, rr_version="1.8",
                                manifest_docs=docs) == V18


def test_when_sources_disagree_the_earliest_wins(tmp_path, monkeypatch):
    """Earlier means more rulings retained, which is the safe direction.
    A mirror that re-processes the PDF moves its modification date
    forward, and a later date is what drops a live ruling."""
    monkeypatch.setattr(rulings, "_pdf_moddate", lambda p: dt.date(2026, 9, 1))
    docs = [{"slug": "marvel-champions-rules-reference",
             "url": ".../mc_rulesreference_v18-web.pdf",
             "date": "22 Jul 2026"}]
    assert rulings.published_on(tmp_path, rr_version="1.8",
                                manifest_docs=docs) == V18


def test_no_source_at_all_yields_none(tmp_path, monkeypatch):
    monkeypatch.setattr(rulings, "_pdf_moddate", lambda p: None)
    assert rulings.published_on(tmp_path, rr_version="1.8",
                                manifest_docs=[]) is None


# --- storing and classifying -----------------------------------------

def test_a_superseded_ruling_is_not_stored_at_all(conn):
    """It says what the rulebook now says, and `rules show` already quotes
    the rulebook. Keeping it would add a second voice saying nothing new."""
    parsed = rulings.parse(PAGE, source_url="u")
    result = rulings.store(conn, parsed.rulings, published=V18,
                           source_name="Hall of Heroes")
    assert result == {"stored": 1, "superseded": 1}
    kept = [r["ruled_on"] for r in conn.execute("SELECT ruled_on FROM rulings")]
    assert kept == ["2026-08-01"]


def test_the_dropped_count_is_reported(conn):
    """`update` needs it to say when a release absorbs a batch - which is
    exactly when a player's understanding has to change."""
    parsed = rulings.parse(PAGE, source_url="u")
    assert rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                         source_name="x") == {"stored": 2, "superseded": 0}


def test_prune_drops_what_a_newer_rulebook_now_covers(conn):
    """Used when the source cannot be re-parsed. Leaving the corpus
    untouched would keep quoting rulings the rulebook has absorbed."""
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                  source_name="x")
    assert rulings.count(conn) == 2
    assert rulings.prune(conn, dt.date(2026, 9, 1)) == 2
    assert rulings.count(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM ruling_terms").fetchone()[0] == 0


def test_pruned_rulings_leave_the_search_index(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                  source_name="x")
    rulings.prune(conn, dt.date(2026, 9, 1))
    assert rulings.search(conn, "excess damage") == []


def test_only_quoted_terms_are_linked(conn):
    """Both rulings mention damage and abilities in passing. Only the term
    each one actually quotes becomes a link."""
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                  source_name="Hall of Heroes")
    linked = {r["term"] for r in conn.execute("SELECT term FROM ruling_terms")}
    assert linked == {"Overkill", "Response"}


def test_attribution_is_recorded_on_every_row(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                  source_name="Hall of Heroes")
    for r in conn.execute("SELECT author, source_name, source_url FROM rulings"):
        assert r["author"] and r["source_name"] and r["source_url"]


def test_store_is_idempotent(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    for _ in range(2):
        rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                      source_name="Hall of Heroes")
    assert conn.execute("SELECT COUNT(*) FROM rulings").fetchone()[0] == 2


def test_a_failed_parse_does_not_discard_a_good_corpus(conn, tmp_path,
                                                       monkeypatch, capsys):
    """A parser that breaks today against a cache that parsed yesterday is
    a broken parser, not an empty corpus. Deleting the rows makes the two
    indistinguishable, and `status` then reports `rulings: 0` for both."""
    from mc_jarvis import init as init_mod

    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                  source_name="Hall of Heroes")
    assert rulings.count(conn) == 2

    monkeypatch.setattr(rulings, "load", lambda root: rulings.RulingsLookup(
        "unparsed", detail="markup changed"))
    monkeypatch.setattr(rulings, "published_on",
                        lambda *a, **k: dt.date(2026, 1, 9))
    out = init_mod._rebuild_rulings(conn, tmp_path)
    assert out["rulings"] == 2
    assert "markup changed" in capsys.readouterr().err


# --- surfacing -------------------------------------------------------

def test_search_finds_a_ruling_by_its_text(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=dt.date(2026, 1, 9),
                  source_name="Hall of Heroes")
    hits = rulings.search(conn, "excess damage")
    assert hits and "Sam Wilson" in hits[0]["answer"]


# --- the real corpus -------------------------------------------------

@pytest.mark.integration
def test_the_real_index_stores_only_outstanding_rulings(real_index):
    """Rulings are opt-in: an index built without network access to the
    curator has none, and neither has one whose rulebook covers every
    ruling issued so far. Both are correct states."""
    from mc_jarvis import paths

    published = rulings.published_on(
        paths.data_dir(),
        rr_version=(real_index.execute(
            "SELECT value FROM build_meta WHERE key = 'rr_version'"
        ).fetchone() or {"value": None})["value"],
        manifest_docs=[])
    if published is None:
        pytest.skip("no Rules Reference publication date")
    for row in real_index.execute("SELECT ruled_on FROM rulings"):
        assert row["ruled_on"] >= published.isoformat(), row["ruled_on"]


@pytest.mark.integration
def test_no_real_ruling_predates_the_page_it_came_from(real_index):
    """Every ruling on the curator's post-1.7 page postdates 1.7. A row
    older than that means the parser matched something that is not a
    ruling - the page keeps legacy sections for history."""
    rows = real_index.execute("SELECT MIN(ruled_on) m FROM rulings").fetchone()
    if rows["m"] is None:
        pytest.skip("no rulings indexed")
    assert rows["m"] >= "2026-01-09"


@pytest.mark.integration
def test_a_ruling_in_force_reaches_rules_show(conn):
    """The point of the feature: the rulebook entry keeps its citation and
    the outstanding ruling sits beside it."""
    from mc_jarvis import rules

    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18,
                  source_name="Hall of Heroes")
    shown = rules.show(conn, "Response")
    assert shown["page"] == 38                     # citation intact
    assert len(shown["rulings"]) == 1
    assert shown["rulings"][0]["source_name"] == "Hall of Heroes"

    # Overkill's ruling predates the rulebook, so it was never stored.
    assert rules.show(conn, "Overkill")["rulings"] == []


@pytest.mark.integration
def test_the_real_corpus_reclassifies_with_the_edition_held():
    """The active branch is unexercised by today's data - every ruling
    predates v1.8 - so it is verified by re-classifying the real corpus
    against each edition rather than by a fixture.

    Deliberately free of a fixed count. On 2026-08-23 the page held 31
    rulings, all issued between 1.7 and 1.8, so 1.8 retained none. Two days
    later 8 more had been published and 1.8 retained those. A gate that
    hard-codes either number fails on the feature succeeding.
    """
    import datetime as _dt
    import tempfile
    from pathlib import Path as _Path

    from mc_jarvis import paths

    found = rulings.load(paths.data_dir())
    if found.status == "disabled":
        pytest.skip("no rulings cached")
    assert found.ok, found.detail

    total = len(found.rulings)

    def kept(when):
        rulings.store(conn, found.rulings, published=when,
                      source_name="Hall of Heroes")
        return rulings.count(conn)

    with tempfile.TemporaryDirectory() as d:
        conn = index.connect(_Path(d) / "t.sqlite")

        # The curator's page collects rulings issued after 1.7, so an index
        # holding 1.7 retains every one of them.
        assert kept(_dt.date(2026, 1, 9)) == total

        # A rulebook newer than every ruling retains none.
        assert kept(_dt.date(2099, 1, 1)) == 0

        # No determinable publication date is the fail-safe: retain
        # everything. Over-reporting is survivable; dropping a live ruling
        # that contradicts the rulebook is the failure this prevents.
        assert kept(None) == total

        # 1.8 sits between the two, and the count is NOT asserted as a
        # constant. It was 0 when this was written on 2026-08-23 and 8 two
        # days later, because rulings kept being issued - which is the
        # feature working, not drifting. What must hold is the ordering:
        # an older rulebook never retains fewer than a newer one.
        at_18 = kept(_dt.date(2026, 7, 22))
        assert 0 <= at_18 <= total
        assert at_18 <= kept(_dt.date(2026, 1, 9))
