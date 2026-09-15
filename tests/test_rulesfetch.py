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


def test_a_refresh_never_replaces_a_newer_list_with_an_older_one(
        tmp_path, monkeypatch):
    path = tmp_path / "rules" / "manifest.json"
    manifest.write(manifest.ManifestResult(
        docs=[_doc("new-rulebook")], source="html", captured="2026-09-01"),
        path)
    monkeypatch.setattr(manifest, "fetch_from_wayback",
                        lambda: manifest.ManifestResult(
                            docs=[], source="wayback", captured="2026-07-21"))
    kept, added = rulesfetch.refresh(tmp_path)
    assert kept.captured == "2026-09-01" and added == []
    assert manifest.read(path).docs[0].slug == "new-rulebook"


def test_a_refresh_reports_what_it_added(tmp_path, monkeypatch):
    path = tmp_path / "rules" / "manifest.json"
    manifest.write(manifest.ManifestResult(
        docs=[_doc("old-rulesheet")], source="wayback",
        captured="2026-07-21"), path)
    monkeypatch.setattr(manifest, "fetch_from_wayback",
                        lambda: manifest.ManifestResult(
                            docs=[_doc("old-rulesheet"),
                                  _doc("fear-no-evil-rulebook")],
                            source="wayback", captured="2026-09-10"))
    _, added = rulesfetch.refresh(tmp_path)
    assert added == ["fear-no-evil-rulebook"]


def test_a_saved_page_refreshes_the_list(tmp_path):
    """The route for a document posted since archive.org last looked."""
    path = tmp_path / "rules" / "manifest.json"
    manifest.write(manifest.ManifestResult(
        docs=[_doc("old-rulesheet")], source="wayback",
        captured="2026-09-10"), path)
    page = tmp_path / "ffg.html"
    page.write_text('<a class="support-item" href="https://x/n.pdf">'
                    '<span class="title">Newest Rulebook</span></a>')
    kept, added = rulesfetch.refresh(tmp_path, page)
    assert kept.source == "html"
    assert added == ["newest-rulebook"]


def test_a_saved_page_that_is_not_ffgs_is_refused(tmp_path):
    manifest.write(manifest.ManifestResult(
        docs=[_doc("old-rulesheet")], source="wayback",
        captured="2026-09-10"), tmp_path / "rules" / "manifest.json")
    page = tmp_path / "other.html"
    page.write_text("<html>nothing here</html>")
    with pytest.raises(RuntimeError, match="lists no rules PDFs"):
        rulesfetch.refresh(tmp_path, page)
    assert manifest.read(
        tmp_path / "rules" / "manifest.json").docs[0].slug == "old-rulesheet"


def test_an_archive_capture_does_not_replace_a_saved_page(tmp_path,
                                                          monkeypatch):
    page = tmp_path / "ffg.html"
    page.write_text('<a class="support-item" href="https://x/n.pdf">'
                    '<span class="title">Newest Rulebook</span></a>')
    rulesfetch.refresh(tmp_path, page)
    monkeypatch.setattr(manifest, "fetch_from_wayback",
                        lambda: manifest.ManifestResult(
                            docs=[], source="wayback", captured="2026-09-10"))
    kept, _ = rulesfetch.refresh(tmp_path)
    assert [d.slug for d in kept.docs] == ["newest-rulebook"]
