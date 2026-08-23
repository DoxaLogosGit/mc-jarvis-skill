"""Designer rulings and supersession (Task 18).

The whole feature turns on one comparison — is this ruling older than the
Rules Reference the user holds — and getting it wrong toward "superseded"
silently drops a live ruling that contradicts the rulebook. That is the
exact failure this exists to prevent, so the date handling gets more tests
than the parsing does.
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

CHANGELOG_PAGE = """Rules Reference Rules Reference
• • Page 5: Revised “Simultaneous
Timing Priority” chart.
• • Page 31: Revised definition of
“overkill.”
• • Page 37: Added definition of
“resolve.”
Version 1.8 Version 1.8
SUMMARY OF NOTABLE CHANGES
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


# --- the Rules Reference's own change log ----------------------------

def test_changelog_parses_page_and_quoted_term():
    entries = rulings.parse_changelog(CHANGELOG_PAGE, "1.8")
    by_term = {e["term"]: e for e in entries if e["term"]}
    assert "overkill" in {t.lower() for t in by_term}
    overkill = next(e for e in entries if (e["term"] or "").lower() == "overkill")
    assert overkill["page"] == "31"
    assert "Revised definition" in overkill["description"]


def test_changelog_rejoins_a_term_wrapped_across_lines():
    """The Rules Reference wraps its change log mid-quote: `Revised
    "Simultaneous / Timing Priority" chart.` Parsing line-by-line captures
    a half-term that matches nothing."""
    entries = rulings.parse_changelog(CHANGELOG_PAGE, "1.8")
    terms = {(e["term"] or "").lower() for e in entries}
    assert "simultaneous timing priority" in terms


# --- storing and classifying -----------------------------------------

def test_store_classifies_and_links_quoted_terms(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    n = rulings.store(conn, parsed.rulings, published=V18,
                      changelog=rulings.parse_changelog(CHANGELOG_PAGE, "1.8"),
                      source_name="Hall of Heroes")
    assert n == 2
    rows = {r["ruled_on"]: dict(r) for r in conn.execute("SELECT * FROM rulings")}
    assert rows["2026-03-06"]["status"] == "superseded"
    assert rows["2026-08-01"]["status"] == "active"


def test_a_superseded_ruling_matching_the_changelog_is_confirmed(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18,
                  changelog=rulings.parse_changelog(CHANGELOG_PAGE, "1.8"),
                  source_name="Hall of Heroes")
    row = conn.execute(
        "SELECT supersession FROM rulings WHERE ruled_on = '2026-03-06'"
    ).fetchone()
    # The change log names "overkill", and the ruling quotes it.
    assert row["supersession"] == "confirmed"


def test_ordinary_rules_vocabulary_does_not_confirm(conn):
    """`resolve` is a change-log term in v1.8 AND a word every second
    ruling uses. Matching change-log terms against free text "confirmed"
    12 of 31 real rulings that merely said something resolves."""
    parsed = rulings.parse(PAGE, source_url="u")
    changelog = [{"rr_version": "1.8", "page": "37",
                  "description": "Added definition of \u201cresolve.\u201d",
                  "term": "resolve"}]
    rulings.store(conn, parsed.rulings, published=V18, changelog=changelog,
                  source_name="Hall of Heroes")
    row = conn.execute(
        "SELECT supersession FROM rulings WHERE ruled_on = '2026-03-06'"
    ).fetchone()
    assert row["supersession"] == "presumed"


def test_supersession_without_a_changelog_match_is_presumed(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    row = conn.execute(
        "SELECT supersession FROM rulings WHERE ruled_on = '2026-03-06'"
    ).fetchone()
    assert row["supersession"] == "presumed"


def test_only_quoted_terms_are_linked(conn):
    """Both rulings mention damage and abilities in passing. Only the term
    each one actually quotes becomes a link."""
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    linked = {r["term"] for r in conn.execute("SELECT term FROM ruling_terms")}
    assert linked == {"Overkill", "Response"}


def test_attribution_is_recorded_on_every_row(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    for r in conn.execute("SELECT author, source_name, source_url FROM rulings"):
        assert r["author"] and r["source_name"] and r["source_url"]


def test_store_is_idempotent(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    for _ in range(2):
        rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                      source_name="Hall of Heroes")
    assert conn.execute("SELECT COUNT(*) FROM rulings").fetchone()[0] == 2


def test_a_failed_parse_does_not_discard_a_good_corpus(conn, tmp_path,
                                                       monkeypatch, capsys):
    """A parser that breaks today against a cache that parsed yesterday is
    a broken parser, not an empty corpus. Deleting the rows makes the two
    indistinguishable, and `status` then reports `rulings: 0` for both."""
    from mc_jarvis import init as init_mod

    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    assert rulings.counts(conn)["total"] == 2

    monkeypatch.setattr(rulings, "load", lambda root: rulings.RulingsLookup(
        "unparsed", detail="markup changed"))
    monkeypatch.setattr(rulings, "published_on", lambda *a, **k: V18)
    out = init_mod._rebuild_rulings(conn, tmp_path)
    assert out["rulings"] == 2
    assert "markup changed" in capsys.readouterr().err


def test_reclassify_moves_rulings_when_the_rulebook_moves_on(conn):
    """The corpus can outlive a parse failure, but its statuses still have
    to track the rulebook actually indexed."""
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    assert rulings.counts(conn) == {"total": 2, "active": 1, "superseded": 1}

    # A newer rulebook absorbs the remaining one.
    assert rulings.reclassify(conn, dt.date(2026, 9, 1))["active"] == 0
    # An older one puts them all back in force.
    assert rulings.reclassify(conn, dt.date(2026, 1, 9))["active"] == 2


# --- surfacing -------------------------------------------------------

def test_for_term_returns_only_active_rulings(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    assert rulings.for_term(conn, "Response")
    assert rulings.for_term(conn, "Overkill") == []


def test_for_term_can_include_superseded(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    got = rulings.for_term(conn, "Overkill", include_superseded=True)
    assert len(got) == 1
    assert got[0]["status"] == "superseded"


def test_search_finds_a_ruling_by_its_text(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    hits = rulings.search(conn, "excess damage", include_superseded=True)
    assert hits and "Sam Wilson" in hits[0]["answer"]


def test_counts_report_the_split(conn):
    parsed = rulings.parse(PAGE, source_url="u")
    rulings.store(conn, parsed.rulings, published=V18, changelog=[],
                  source_name="Hall of Heroes")
    assert rulings.counts(conn) == {"total": 2, "active": 1, "superseded": 1}


# --- the real corpus -------------------------------------------------

@pytest.mark.integration
def test_the_real_index_classifies_every_ruling(real_index):
    """Rulings are opt-in: an index built without network access to the
    curator has none, and that is not a failure."""
    rows = real_index.execute(
        "SELECT status, COUNT(*) n FROM rulings GROUP BY status").fetchall()
    if not rows:
        pytest.skip("no rulings indexed")
    assert {r["status"] for r in rows} <= {"active", "superseded"}
    unclassified = real_index.execute(
        "SELECT COUNT(*) FROM rulings WHERE status = 'superseded' "
        "AND supersession IS NULL").fetchone()[0]
    assert unclassified == 0


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
def test_the_real_corpus_reclassifies_with_the_edition_held():
    """The active branch is unexercised by today's data - every ruling
    predates v1.8 - so it is verified by re-classifying the real corpus
    against each edition rather than by a fixture.

    Measured 2026-08-23: 31 rulings, all issued between v1.7 and v1.8.
    """
    import datetime as _dt
    import tempfile
    from pathlib import Path as _Path

    from mc_jarvis import paths

    found = rulings.load(paths.data_dir())
    if found.status == "disabled":
        pytest.skip("no rulings cached")
    assert found.ok, found.detail

    with tempfile.TemporaryDirectory() as d:
        conn = index.connect(_Path(d) / "t.sqlite")
        for when, expect_active in (
                (_dt.date(2026, 1, 9), len(found.rulings)),   # v1.7
                (_dt.date(2026, 7, 22), 0),                   # v1.8
                (None, len(found.rulings))):                  # fail-safe
            rulings.store(conn, found.rulings, published=when, changelog=[],
                          source_name="Hall of Heroes")
            assert rulings.counts(conn)["active"] == expect_active, when


@pytest.mark.integration
def test_no_supersession_is_confirmed_by_ordinary_vocabulary(real_index):
    """The change log confirms 0 of 31 today, and that is the finding: page
    1 summarises NOTABLE changes, not every incorporation. Any rule that
    confirms more was measured and found unsound - `resolve` claimed 12,
    and change-log page numbers claimed 2 by coincidental page sharing."""
    rows = real_index.execute(
        "SELECT COUNT(*) FROM rulings WHERE supersession = 'confirmed'"
    ).fetchone()[0]
    total = real_index.execute("SELECT COUNT(*) FROM rulings").fetchone()[0]
    if total == 0:
        pytest.skip("no rulings indexed")
    assert rows == 0
