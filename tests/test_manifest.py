from pathlib import Path

import pytest

from mc_jarvis import manifest

FIXTURE = Path(__file__).parent / "fixtures" / "ffg_support.html"


@pytest.fixture
def docs():
    return manifest.parse(FIXTURE.read_text(encoding="utf-8"))


def test_only_pdf_links_are_collected(docs):
    assert len(docs) == 3
    assert all(d.url.endswith(".pdf") for d in docs)


def test_title_size_and_date_come_from_inside_the_anchor(docs):
    """They sit in labelled spans INSIDE the <a>. An earlier draft read
    them from the text following it and returned None for all three."""
    rr = next(d for d in docs if "Rules Reference" in d.title)
    assert rr.title == "Tester Rules Reference"
    assert rr.size == "3.5 MB"
    assert rr.date == "09 Jan 2026"


def test_every_document_carries_a_date(docs):
    """`diff` reports revisions off the date. Without it, `update` can
    never detect that FFG revised a rulebook."""
    assert all(d.date for d in docs), [d.title for d in docs if not d.date]


def test_slugs_are_stable_and_filesystem_safe(docs):
    assert docs[1].slug == "tester-rules-reference"
    assert all("/" not in d.slug and " " not in d.slug for d in docs)


def test_entities_in_titles_are_decoded(docs):
    assert "’" in docs[2].title or "'" in docs[2].title


def test_roundtrip_through_disk(tmp_path, docs):
    path = tmp_path / "manifest.json"
    result = manifest.ManifestResult(docs=docs, source="wayback",
                                     captured="2026-07-21")
    manifest.write(result, path)
    back = manifest.read(path)
    assert back.docs == docs
    assert back.source == "wayback"
    assert back.captured == "2026-07-21"


def test_reading_a_missing_manifest_is_not_an_error(tmp_path):
    result = manifest.read(tmp_path / "nope.json")
    assert result.docs == []
    assert result.source == "none"


def test_diff_reports_a_revised_document(docs):
    newer = [manifest.RuleDoc(**d.__dict__) for d in docs]
    newer[1].date = "01 Jan 2027"
    assert dict(manifest.diff(docs, newer))["tester-rules-reference"] \
        == "revised"


def test_diff_reports_an_added_document(docs):
    assert dict(manifest.diff(docs[:2], docs)).get(
        "testers-expansion-rulebook") == "added"


def test_diff_is_empty_when_nothing_changed(docs):
    assert manifest.diff(docs, docs) == []


@pytest.mark.integration
def test_wayback_yields_a_usable_manifest_without_a_browser():
    """The whole point: FFG's page is 403 and JS-rendered, but the
    archived capture carries the list and its hrefs are FFG's own CDN."""
    result = manifest.fetch_from_wayback()
    assert result.source == "wayback"
    assert result.captured
    assert len(result.docs) > 50
    assert all("fantasyflightgames.com" in d.url for d in result.docs)
    slugs = {d.slug for d in result.docs}
    assert set(manifest.DEFAULT_SLUGS) <= slugs, sorted(slugs)[:20]


@pytest.mark.integration
def test_archived_urls_still_resolve_on_ffgs_cdn():
    """Downloading needs no browser - only discovery did."""
    import urllib.request
    result = manifest.fetch_from_wayback()
    rr = next(d for d in result.docs
              if d.slug == "marvel-champions-rules-reference")
    req = urllib.request.Request(rr.url, headers={"Range": "bytes=0-64"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        assert resp.status in (200, 206)


# --- currency: the archive path can be behind on a FRESH install ---

def _wayback(captured):
    return manifest.ManifestResult(docs=[], source="wayback",
                                   captured=captured)


def test_a_recent_capture_raises_no_warning():
    import datetime as dt
    today = dt.date.today().isoformat()
    assert manifest.currency_warning(_wayback(today)) is None


def test_an_old_capture_warns_and_says_update_will_not_help():
    """The failure mode is not ordinary staleness: `update` re-reads the
    same capture, so it cannot cure this. The message must say so."""
    import datetime as dt
    old = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    warning = manifest.currency_warning(_wayback(old))
    assert warning
    assert "update" in warning and "cannot see them" in warning
    assert "--from-html" in warning


def test_a_browser_or_html_manifest_is_never_warned_about():
    """Those paths read the live page, so they are current by definition."""
    for source in ("html", "browser"):
        result = manifest.ManifestResult(docs=[], source=source)
        assert manifest.currency_warning(result) is None
        assert manifest.capture_age_days(result) is None


def test_capture_age_is_measured_in_days():
    import datetime as dt
    week = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    assert manifest.capture_age_days(_wayback(week)) == 7
