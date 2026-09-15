"""Whether an erratum is already in the card text (errata.py)."""
import pytest

from mc_jarvis import errata


@pytest.mark.parametrize("gloss,text,status", [
    ("Changed “trigger” to “resolve”.", "After you trigger a card.",
     "not_applied"),
    ("Changed “trigger” to “resolve”.", "After you resolve a card.",
     "applied"),
    ("Changed “Interrupt” to “Forced Interrupt”.",
     "<b>Forced Interrupt</b>: When it would leave.", "applied"),
    ("Changed “Interrupt” to “Forced Interrupt”.",
     "<b>Interrupt</b>: When it would leave.", "not_applied"),
    ("Added “Max 1 per character.”", "Attach to a friend.", "not_applied"),
    ("Removed “(thwart)” label.",
     "<b>Alter-Ego Action</b>: Remove 2 threat.", "applied"),
    ("Changed cost arrow to “Then”.", "Pay 1 → heal 1.", "not_applied"),
    ("Specified who should resolve the ability.", "Anything.", "unverified"),
])
def test_the_stated_change_decides(gloss, text, status):
    """Whole-text comparison flagged cards differing by a plural; the
    gloss names the change, so only the change is tested."""
    assert errata.verdict(gloss, text) == status


@pytest.mark.integration
def test_every_erratum_is_parsed_and_every_card_one_is_matched(real_index):
    """The design once said marvelsdb applies errata, from four cards.
    Across all of them the data is mixed, so this pins that each one is
    found and judged rather than assumed."""
    from mc_jarvis import paths
    txt = (paths.data_dir() / "rules" / "txt" /
           "marvel-champions-rules-reference.txt").read_text()
    section = txt[txt.index("APPENDIX V: APPENDIX V:"):
                  txt.index("APPENDIX VI: GAME")]
    indexed = real_index.execute(
        "SELECT COUNT(*) FROM rules_entries WHERE term LIKE 'Errata:%'"
    ).fetchone()[0]
    assert indexed == section.count("Should read:")
    matched = {r[0] for r in real_index.execute(
        "SELECT entry_id FROM errata")}
    unmatched = [r[1] for r in real_index.execute(
        "SELECT id, term FROM rules_entries WHERE term LIKE 'Errata:%'")
        if r[0] not in matched and "(#" in r[1]]
    assert not unmatched, unmatched
    status = dict(real_index.execute(
        "SELECT code, status FROM errata WHERE code IN ('01026', '08009')"
    ).fetchall())
    assert status == {"01026": "applied", "08009": "not_applied"}
