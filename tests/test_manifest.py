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


# --- currency check against the community mirror ---
#
# The question these answer: what happens when the mirror changes shape?
# Every failure must be nameable. Returning "no result" for both "you are
# current" and "the check broke" is how a stale rulebook gets served with
# confidence.

ROOT_HTML = """
<nav><a href="/cards/">Cards</a><a href="/blog-feed/">Blog</a>
<a href="https://mirror.invalid/latest-ffg-rulings-post-rrg-1-7/">Rulings</a>
<a href="/community-resources/">Resources</a></nav>
"""

PAGE_HTML = """
<h2>Current Rules Reference Guide</h2>
<p><a href="https://mirror.invalid/uploads/2026/07/mc_rulesreference_v18.pdf">1.8</a></p>
<h2>Prior Rules Reference Guides</h2>
<p><a href="https://mirror.invalid/uploads/2020/04/mc_rulesreference_v11.pdf">1.1</a></p>
<p><a href="https://mirror.invalid/uploads/2021/04/mc_rulesreference_v14.pdf">1.4</a></p>
"""


def test_the_rulings_page_is_found_by_nav_label_not_a_fixed_url():
    """The rulings URL encodes the RR version it post-dates, so it
    changes with each release; the nav label does not."""
    url = manifest.find_rulings_page(ROOT_HTML)
    assert url.endswith("/latest-ffg-rulings-post-rrg-1-7/")


def test_a_changed_rulings_url_is_followed_automatically():
    moved = ROOT_HTML.replace("post-rrg-1-7", "post-rrg-1-9")
    assert "post-rrg-1-9" in manifest.find_rulings_page(moved)


def test_current_version_is_read_from_the_page():
    look = manifest.current_rr_from_mirror(page_html=PAGE_HTML)
    assert look.ok and look.version == "1.8"


def test_a_renamed_heading_does_not_break_the_check():
    """Strategy 1 reads FFG's filename convention, so it survives any
    change to the page's headings."""
    renamed = PAGE_HTML.replace("Current Rules Reference Guide",
                                "The Newest Rulebook")
    look = manifest.current_rr_from_mirror(page_html=renamed)
    assert look.ok and look.version == "1.8"


def test_a_missing_nav_link_is_named_not_swallowed():
    stripped = ROOT_HTML.replace(">Rulings<", ">Judgements<")
    look = manifest.current_rr_from_mirror(home_html=stripped)
    assert look.status == "nav_missing"
    assert "redesigned" in look.detail


def test_an_unrecognisable_page_is_named_not_swallowed():
    look = manifest.current_rr_from_mirror(page_html="<p>coming soon</p>")
    assert look.status == "unparsed"
    assert "markup" in look.detail


def test_disagreeing_strategies_refuse_to_guess():
    """If the labelled section names an older version than the highest
    one linked on the page, picking either silently is how a stale
    rulebook gets served with confidence."""
    conflicting = """
<h2>Current Rules Reference Guide</h2>
<p><a href="https://mirror.invalid/uploads/2021/04/mc_rulesreference_v14.pdf">1.4</a></p>
<h2>Prior Rules Reference Guides</h2>
<p><a href="https://mirror.invalid/uploads/2026/07/mc_rulesreference_v18.pdf">1.8</a></p>
"""
    look = manifest.current_rr_from_mirror(page_html=conflicting)
    assert look.status == "disagree"
    assert "not guessing" in look.detail


def test_version_is_recoverable_from_ffgs_filename():
    f = manifest.rr_version_from_filename
    assert f(".../mc_rulesreference_v17-web.pdf") == "1.7"
    assert f(".../mc_rulesreference_v18_compressed.pdf") == "1.8"
    assert f(".../marvelrrg10.pdf") == "1.0"
    assert f(".../learn_to_play.pdf") is None


def _manifest_with(rr_url):
    return manifest.ManifestResult(
        docs=[manifest.RuleDoc(title="Marvel Champions Rules Reference",
                               url=rr_url,
                               slug="marvel-champions-rules-reference")],
        source="wayback", captured="2026-07-21")


def test_a_behind_manifest_reports_a_usable_alternative():
    mirror = manifest.current_rr_from_mirror(page_html=PAGE_HTML)
    result = manifest.check_rr_currency(
        _manifest_with(".../mc_rulesreference_v17-web.pdf"), mirror)
    assert result["status"] == "behind"
    assert (result["have"], result["current"]) == ("1.7", "1.8")
    assert result["url"].endswith(".pdf")


def test_a_current_manifest_reports_nothing():
    mirror = manifest.current_rr_from_mirror(page_html=PAGE_HTML)
    assert manifest.check_rr_currency(
        _manifest_with(".../mc_rulesreference_v18_compressed.pdf"),
        mirror) is None


def test_a_broken_oracle_never_reads_as_a_clean_bill_of_health():
    """The whole point. A site redesign must not look like "you are up
    to date"."""
    broken = manifest.current_rr_from_mirror(page_html="<p>hello</p>")
    result = manifest.check_rr_currency(
        _manifest_with(".../mc_rulesreference_v17-web.pdf"), broken)
    assert result is not None
    assert result["status"] == "unknown"
    assert "unparsed" in result["detail"]


def test_a_newer_manifest_than_the_mirror_reports_nothing():
    """The mirror is a sanity check, not an authority."""
    mirror = manifest.current_rr_from_mirror(page_html=PAGE_HTML)
    assert manifest.check_rr_currency(
        _manifest_with(".../mc_rulesreference_v19.pdf"), mirror) is None


@pytest.mark.integration
def test_the_real_site_resolves_through_its_nav():
    look = manifest.current_rr_from_mirror()
    assert look.status in ("ok", "unreachable"), look.detail
    if look.ok:
        assert look.version and look.url.endswith(".pdf")
