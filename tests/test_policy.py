"""The distribution rule, checked rather than stated.

The README says this repository ships code and configuration only. That
was true because people were careful, which is not a mechanism. These
tests are the mechanism.
"""
import pytest

from mc_jarvis import policy


def test_a_phrase_from_the_corpus_is_found(tmp_path):
    """The check is direct: a repository phrase that appears verbatim in
    the rulebook or the card data IS shipped text. No length heuristic can
    make that call - a 40-character quotation is still a quotation, and a
    120-character explanation in your own words is not."""
    from mc_jarvis import index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.execute(
        "INSERT INTO rules_entries (term, body, page, source_doc) "
        "VALUES ('Guard', 'While a minion with guard is engaged with a "
        "player, that player cannot attack the villain.', 1, 'rr')")
    conn.commit()

    (tmp_path / "note.md").write_text(
        "The rule: while a minion with guard is engaged with a player, "
        "that player cannot attack the villain.\n", encoding="utf-8")
    grams = policy.corpus_grams(conn)
    assert policy._grams(policy._words(
        "while a minion with guard is engaged with a player")) & grams


def test_our_own_writing_about_the_same_rule_is_not_flagged(tmp_path):
    from mc_jarvis import index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.execute(
        "INSERT INTO rules_entries (term, body, page, source_doc) "
        "VALUES ('Guard', 'While a minion with guard is engaged with a "
        "player, that player cannot attack the villain.', 1, 'rr')")
    conn.commit()
    ours = ("A guarding minion has to be dealt with before the villain "
            "can be hit at all, which is why it changes the maths.")
    assert not (policy._grams(policy._words(ours))
                & policy.corpus_grams(conn))


def test_text_this_project_generates_is_not_its_own_violation(tmp_path):
    """`rules_chunk` writes a body for index lines that resolve to no
    section, and stores it in `rules_entries` - so the generator matched
    itself. The first run of this check reported it, which is exactly the
    false positive a corpus-based rule can produce: our own text, fed
    back in."""
    from mc_jarvis import index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.execute(
        "INSERT INTO rules_entries (term, body, page, source_doc) VALUES "
        "('Widget', 'Listed in the Rules Reference index at page 12, but "
        "no section of that name was found in the document.', 12, 'rr')")
    conn.commit()
    assert policy.corpus_grams(conn) == set()


@pytest.mark.integration
def test_the_shipped_surface_carries_no_card_or_rules_text(real_index):
    """The gate. Code, configuration, the skill and the README are what
    this repository distributes; none of it may contain FFG's wording.

    When this fails: rewrite the line in your own words, or store the
    `rr_entry` it lives in and read the wording from `rules_entries` at
    print time. `config/timing.yaml`'s `tie_breaks` is the worked example
    - it once held seven close paraphrases of RR rules.
    """
    findings = policy.scan(real_index)
    assert findings == [], "\n" + policy.report(findings)


@pytest.mark.integration
def test_the_window_is_at_the_bottom_of_its_measured_band(real_index):
    """`WINDOW` drops matches shorter than itself, which is the shape of
    filter that has hidden several findings in this project. It is allowed
    only while what sits below it is measured rather than assumed.

    At 6 words the hits are ordinary game vocabulary that any description
    of a card shares with the card - "from the top of the deck", "in play
    under a player's control". Those are not quotations, and a check that
    flagged them would be turned off. At 7 the surface is clean.

    An earlier value of 8 let three real quotations through, which is why
    this asserts the band rather than the number.
    """
    assert policy.scan(real_index) == []
    below = policy.scan(real_index, window=policy.WINDOW - 1)
    assert below, ("nothing sits below the cutoff, so it is not measured - "
                   "re-derive it rather than trusting this constant")


@pytest.mark.integration
def test_the_functional_identification_exemption_stays_small(real_index):
    """The LICENCE lets the software name part of a document in order to
    parse it. That carve-out is real - the timing chart is found by its
    own heading - and it is also the obvious place for a quotation to
    hide. One marker today; a jump means someone reached for it instead
    of rewriting a line."""
    marks = policy.locators()
    assert len(marks) <= 3, marks
    assert len(marks) >= 1, ("the exemption is unused - if that is real, "
                             "delete the mechanism rather than keeping a "
                             "door nobody watches")
    for mark in marks:
        assert mark["file"].startswith("src/"), mark


@pytest.mark.integration
def test_a_quotation_added_to_the_shipped_surface_is_caught(real_index,
                                                            tmp_path):
    """The check must fail when it should. A gate nobody has seen fail is
    a gate nobody knows works."""
    body = real_index.execute(
        "SELECT body FROM rules_entries WHERE lower(term) = 'forced' "
        "LIMIT 1").fetchone()["body"]
    sentence = " ".join(body.split())[:180]

    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "x.yaml").write_text(f"note: {sentence}\n",
                                            encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)

    assert policy.scan(real_index, root) != []


def test_a_document_cannot_excuse_itself(tmp_path):
    """The exemption is for code that parses a document. Prose claiming it
    would let a quotation in a design note be waved through by writing
    four words beside it - and the README explaining the marker tripped
    its own scan, which is how this was found."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "notes.md").write_text(
        "Mark such a line `# policy: locator` with a reason.\n",
        encoding="utf-8")
    (root / "src" / "p.py").write_text(
        "# policy: locator - anchors a parse\nX = 1\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)

    files = {m["file"] for m in policy.locators(root, scope=("",))}
    assert files == {"src/p.py"}


def test_only_a_comment_can_claim_the_exemption(tmp_path):
    """Without this, the module's own `LOCATOR_MARK = "policy: locator"`
    claimed it, and so did every test string that mentions it. A marker
    that a string literal can trip is a marker an attacker - or a hurried
    contributor - can trip."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "p.py").write_text(
        'MARK = "policy: locator"\n'
        '# policy: locator - a real one\n', encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)

    found = policy.locators(root, scope=("",))
    assert [m["line"] for m in found] == [2]


def test_an_empty_corpus_refuses_rather_than_reporting_clean(tmp_path):
    """CI runs this against a card-only index, so the degraded case is a
    real one, not hypothetical. A check with nothing to compare against
    must not print "clean" - that is the exact failure this whole module
    exists to catch, turned on itself."""
    db = tmp_path / "empty.sqlite"
    assert policy.main(["--db", str(db)]) == 2


def test_coverage_names_a_source_it_does_not_have(tmp_path):
    """`corpus_grams` degrades silently when a table is empty: it just
    contributes nothing. `coverage` is what makes the degradation
    visible, so a partial run cannot read as a complete one."""
    from mc_jarvis import index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.execute(
        "INSERT INTO cards (code, name, text, canonical_code, is_reprint, "
        "raw) VALUES ('c1', 'C', 'Some text.', 'c1', 0, '{}')")
    conn.commit()
    got = policy.coverage(conn)
    assert got["cards"] == 1
    assert got["rules_entries"] == 0
