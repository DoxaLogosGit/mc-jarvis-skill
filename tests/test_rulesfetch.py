"""Fetching one hero's or product's rules document (rulesfetch.py)."""
import pytest

from mc_jarvis import manifest, pdf, rulesfetch


def _doc(slug):
    return manifest.RuleDoc(title=slug, url=f"https://x/{slug}.pdf", slug=slug)


def test_a_document_already_downloaded_is_not_fetched_again(tmp_path,
                                                            monkeypatch):
    (tmp_path / "rules" / "pdf").mkdir(parents=True)
    (tmp_path / "rules" / "pdf" / "a-rulesheet.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(pdf, "download",
                        lambda *a: pytest.fail("downloaded twice"))
    assert rulesfetch.fetch(None, tmp_path, _doc("a-rulesheet")) is False


def test_a_fetched_document_lands_in_the_data_directory(tmp_path,
                                                        monkeypatch):
    """The distribution rule: rulebooks live beside the index, never in
    the repository."""
    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        return dest

    monkeypatch.setattr(pdf, "download", fake_download)
    monkeypatch.setattr(pdf, "extract_pages", lambda p: ["one", "two"])
    assert rulesfetch.fetch(None, tmp_path, _doc("b-rulesheet")) is True
    assert (tmp_path / "rules" / "txt" / "b-rulesheet.txt").read_text() \
        == "one\ftwo"


@pytest.mark.parametrize("ref,slugs", [
    ("Doctor Strange", ["doctor-strange-rulesheet"]),
    ("09001a", ["doctor-strange-rulesheet"]),
    ("doctor-strange-rulesheet", ["doctor-strange-rulesheet"]),
])
def test_a_hero_or_slug_names_its_document(real_index, ref, slugs):
    docs = [_doc(s) for s in ("doctor-strange-rulesheet", "storm-rulesheet",
                              "mutant-genesis-rulebook")]
    got, _ = rulesfetch.candidates(real_index, docs, ref)
    assert [d.slug for d in got] == slugs


def test_a_campaign_box_hero_is_covered_by_the_box(real_index):
    """No sheet of its own: the box's rulebook sets it up."""
    docs = [_doc("mutant-genesis-rulebook")]
    got, label = rulesfetch.candidates(real_index, docs, "Colossus")
    assert [d.slug for d in got] == ["mutant-genesis-rulebook"]


def test_a_hero_newer_than_the_list_finds_nothing(real_index):
    got, label = rulesfetch.candidates(real_index, [_doc("storm-rulesheet")],
                                       "Daredevil")
    assert got == [] and label == "Daredevil"
