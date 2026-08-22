"""Rules manifest discovery (spec §11, revised 2026-08-22).

FFG's product page returns 403 to every HTTP client and renders its
download list with JavaScript, so a plain fetch cannot see the PDFs. The
spec's answer was `--from-html`: the user saves the page by hand. That
works, but it makes `init` require a manual step on exactly the agents
with no browser - the case the design exists to serve.

Measured alternatives, 2026-08-22:

  FFG product page, direct .............. 403, and JS-rendered
  FFG CDN deep links .................... 200/206 - downloads need no browser
  archive.org CDX API ................... open, 97 snapshots since 2019
  archive.org snapshot (--compressed) ... 87 PDF links + title/size/date
  archive.org /save/ .................... times out; not automatable
  third-party fan mirrors ............... re-hosted copies, stale versions

So the Wayback Machine is the default: it needs no browser, and the URLs
it yields point at FFG's own CDN, so the PDFs are still fetched from the
publisher. Its cost is currency - 2026 saw 3 snapshots, a 137-day median
gap - so the snapshot date travels with the manifest and `status` reports
it. The Rules Reference and Learn to Play change rarely; a months-old
snapshot still yields a working rules index, and a browser path stays
available for anyone who needs today's list.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

PRODUCT_PAGE = ("https://www.fantasyflightgames.com/en/products/"
                "marvel-champions-the-card-game/")
CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_SNAPSHOT = "https://web.archive.org/web/{ts}id_/{url}"
DEFAULT_SLUGS = ("marvel-champions-rules-reference", "learn-to-play")
USER_AGENT = "mc-jarvis"


@dataclass
class RuleDoc:
    title: str
    url: str
    size: str | None = None
    date: str | None = None
    slug: str = ""


@dataclass
class ManifestResult:
    docs: list[RuleDoc]
    source: str                 # wayback | html | browser
    captured: str | None = None  # snapshot date, when source is wayback


def slugify(title: str) -> str:
    norm = unicodedata.normalize("NFKD", title)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = re.sub(r"[^\w\s-]", "", norm).strip().lower()
    return re.sub(r"[\s_]+", "-", norm)


class _Collector(HTMLParser):
    """Read FFG's support list.

    Each entry is one anchor containing three labelled spans:

        <a class="support-item" href="....pdf">
          <span class="file-size">3.5 MB</span>
          <span class="title">Marvel Champions Rules Reference</span>
          <span class="date">09 Jan 2026</span>
        </a>

    Size, title and date sit INSIDE the anchor. An earlier draft read them
    from the text following it and would have returned None for all three.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.docs: list[RuleDoc] = []
        self._href: str | None = None
        self._span: str | None = None
        self._parts: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href", "")
            self._href = href if href.lower().split("?")[0].endswith(".pdf") \
                else None
            self._parts = {}
            self._span = None
        elif tag == "span" and self._href:
            classes = (attrs.get("class") or "").split()
            for name in ("file-size", "title", "date"):
                if name in classes:
                    self._span = name
                    self._parts.setdefault(name, [])
                    break

    def handle_endtag(self, tag):
        if tag == "span":
            self._span = None
        elif tag == "a" and self._href:
            def take(key):
                return " ".join("".join(self._parts.get(key, [])).split()) or None
            title = take("title") or self._href.rsplit("/", 1)[-1]
            self.docs.append(RuleDoc(title=title, url=self._href,
                                     size=take("file-size"), date=take("date"),
                                     slug=slugify(title)))
            self._href = None
            self._parts = {}

    def handle_data(self, data):
        if self._href and self._span:
            self._parts[self._span].append(data)


def parse(html: str) -> list[RuleDoc]:
    collector = _Collector()
    collector.feed(html)
    seen: set[str] = set()
    out: list[RuleDoc] = []
    for doc in collector.docs:
        if doc.url in seen:
            continue
        seen.add(doc.url)
        out.append(doc)
    return out


def _get(url: str, timeout: int = 60, *, attempts: int = 3) -> bytes:
    """Fetch with retry.

    archive.org rate-limits and will time out a burst of requests. A bare
    failure here reads as "no snapshot exists", which is the wrong
    diagnosis and sends the user off to find a browser they do not need.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 ** attempt)
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as exc:      # noqa: BLE001 - retried below
            last = exc
    raise RuntimeError(f"could not fetch {url} after {attempts} attempts: "
                       f"{last}") from last


def latest_snapshot(url: str = PRODUCT_PAGE) -> str | None:
    """Newest archived capture, as a CDX timestamp."""
    query = (f"{CDX_API}?url={urllib.parse.quote(url, safe='')}"
             f"&output=json&filter=statuscode:200&limit=-1")
    rows = json.loads(_get(query, timeout=30))
    return rows[-1][1] if len(rows) > 1 else None


def fetch_from_wayback(url: str = PRODUCT_PAGE) -> ManifestResult:
    """The default path: no browser, no manual step.

    `id_` asks for the original capture rather than archive.org's
    rewritten copy, so the hrefs are FFG's own CDN URLs.
    """
    timestamp = latest_snapshot(url)
    if timestamp is None:
        raise RuntimeError(
            "archive.org has no usable snapshot of the product page. Save "
            f"the page from a browser and use --from-html.\n  {url}")
    html = _get(WAYBACK_SNAPSHOT.format(ts=timestamp, url=url),
                timeout=90).decode("utf-8", errors="replace")
    docs = parse(html)
    if not docs:
        raise RuntimeError(
            f"snapshot {timestamp} contained no PDF links; the page markup "
            f"may have changed. Use --from-html.")
    captured = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
    return ManifestResult(docs=docs, source="wayback", captured=captured)


def fetch_from_html(path: Path) -> ManifestResult:
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    return ManifestResult(docs=parse(html), source="html")


def fetch_with_browser() -> ManifestResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "the browser extra is not installed. Either run\n"
            "  uv tool install 'mc-jarvis[browser]' && playwright install chromium\n"
            "or omit --browser to use the archive.org path, which needs no "
            "browser at all.") from exc
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(PRODUCT_PAGE, wait_until="networkidle")
        html = page.content()
        browser.close()
    return ManifestResult(docs=parse(html), source="browser")


def write(result: ManifestResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"source": result.source, "captured": result.captured,
         "docs": [asdict(d) for d in result.docs]},
        indent=2, ensure_ascii=False), encoding="utf-8")


def read(path: Path) -> ManifestResult:
    if not Path(path).exists():
        return ManifestResult(docs=[], source="none")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ManifestResult(docs=[RuleDoc(**d) for d in payload.get("docs", [])],
                          source=payload.get("source", "unknown"),
                          captured=payload.get("captured"))


def diff(old: list[RuleDoc], new: list[RuleDoc]) -> list[tuple[str, str]]:
    by_slug = {d.slug: d for d in old}
    changes = []
    for doc in new:
        prev = by_slug.get(doc.slug)
        if prev is None:
            changes.append((doc.slug, "added"))
        elif prev.date != doc.date or prev.url != doc.url:
            changes.append((doc.slug, "revised"))
    return changes


# How long a wayback-sourced manifest may sit before the tool stops
# treating it as representative. 2026 saw three snapshots of the product
# page, a 137-day median gap, so a capture is routinely weeks behind.
CAPTURE_STALE_DAYS = 21


def capture_age_days(result: ManifestResult) -> int | None:
    if result.source != "wayback" or not result.captured:
        return None
    import datetime as _dt
    captured = _dt.date.fromisoformat(result.captured)
    return (_dt.date.today() - captured).days


def currency_warning(result: ManifestResult) -> str | None:
    """Say when the manifest may be behind FFG, and what to do about it.

    This is not ordinary staleness that `update` cures. `update` re-reads
    the same archived capture, so a manifest sourced from the Wayback
    Machine stays behind until archive.org crawls the page again -
    which in 2026 meant a 137-day median gap. Measured 2026-08-22: the
    newest capture predates Rules Reference v1.8 by a single day, so a
    correct, fresh install yields v1.7 and `update` will not change that.

    Serving that silently is the problem. Saying so is the fix.
    """
    age = capture_age_days(result)
    if age is None or age < CAPTURE_STALE_DAYS:
        return None
    return (
        f"The rules manifest comes from an archive.org capture taken "
        f"{age} days ago ({result.captured}). FFG may have published or "
        f"revised rulebooks since, and `mc-jarvis update` cannot see them "
        f"- it re-reads the same capture. To pick up the current list, "
        f"save the product page from a browser and run:\n"
        f"  mc-jarvis init --from-html <file>\n"
        f"  {PRODUCT_PAGE}")


def newer_snapshot_available(result: ManifestResult) -> str | None:
    """A capture newer than the one this manifest came from, if any."""
    if result.source != "wayback" or not result.captured:
        return None
    latest = latest_snapshot()
    if not latest:
        return None
    iso = f"{latest[:4]}-{latest[4:6]}-{latest[6:8]}"
    return iso if iso > result.captured else None


# A community-maintained site that tracks the current Rules Reference.
# Used as a currency oracle and fallback download when the archived FFG
# manifest is behind.
#
# Verified 2026-08-22: its copy of Rules Reference v1.8 is byte-identical
# to the file served by FFG's own CDN - same length, same SHA-256. A
# faithful mirror, not a re-encode.
#
# Resolution follows the site's NAV LABEL, not a fixed URL. The rulings
# URL encodes the Rules Reference version it post-dates
# (".../latest-ffg-rulings-post-rrg-1-7/") and therefore changes with
# each release, while the nav label "Rulings" has been stable for years.
# Hardcoding the URL would break on exactly the event we are trying to
# detect.
MIRROR_NAME = "Hall of Heroes"
MIRROR_HOME = "https://hallofheroeslcg.com/"
MIRROR_NAV_LABEL = "rulings"
MIRROR_SECTION = "Current Rules Reference Guide"

_VERSION_LABEL_RE = re.compile(r"^\s*v?(\d+\.\d+)\s*$", re.I)
_RR_FILENAME_RE = re.compile(r"rulesreference[_-]?v(\d)(\d+)", re.I)
_LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)


@dataclass
class MirrorLookup:
    """Result of consulting the mirror.

    `status` is the point of this type. An earlier version returned None
    for every failure, so "the mirror says you are current" and "the
    mirror could not be read" were indistinguishable - and a site
    redesign would silently disable the check while the tool kept
    reporting a healthy index. Each failure now has a name, and `doctor`
    reports it.
    """
    status: str            # ok | nav_missing | unreachable | unparsed | disagree
    version: str | None = None
    url: str | None = None
    page_url: str | None = None
    detail: str = ""
    source_name: str = MIRROR_NAME

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _text_of(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", fragment).split())


def find_rulings_page(home_html: str | None = None) -> str | None:
    """Follow the nav label rather than a remembered URL."""
    if home_html is None:
        try:
            home_html = _get(MIRROR_HOME, timeout=45).decode(
                "utf-8", errors="replace")
        except Exception:
            return None
    for url, label in _LINK_RE.findall(home_html):
        if _text_of(label).strip().lower() == MIRROR_NAV_LABEL:
            return url
    return None


def _versions_on_page(html_text: str) -> list[tuple[tuple[int, ...], str, str]]:
    """Every Rules Reference version linked on the page.

    Read from FFG's own filename convention, so it survives any change to
    the page's headings or layout.
    """
    out = []
    for url, _ in _LINK_RE.findall(html_text):
        m = _RR_FILENAME_RE.search(url)
        if m:
            version = f"{m.group(1)}.{m.group(2)}"
            out.append((_version_key(version), version, url))
    return sorted(out)


def _labelled_current(html_text: str) -> tuple[str, str] | None:
    start = html_text.find(MIRROR_SECTION)
    if start == -1:
        return None
    for url, label in _LINK_RE.findall(html_text[start:start + 2000]):
        m = _VERSION_LABEL_RE.match(_text_of(label))
        if m:
            return m.group(1), url
    return None


def current_rr_from_mirror(page_html: str | None = None,
                           home_html: str | None = None) -> MirrorLookup:
    """The Rules Reference version the mirror currently lists.

    Two independent strategies, because a page can be redesigned:

      1. the highest version among all Rules Reference links, read from
         FFG's filename convention - survives heading changes;
      2. the link under the heading "Current Rules Reference Guide".

    Agreement is the normal case. Disagreement is reported rather than
    guessed at, because picking one silently is how a stale rulebook gets
    served with confidence.
    """
    page_url = None
    if page_html is None:
        page_url = find_rulings_page(home_html)
        if page_url is None:
            return MirrorLookup(
                "nav_missing", page_url=MIRROR_HOME,
                detail=f"no nav link labelled {MIRROR_NAV_LABEL!r} on "
                       f"{MIRROR_HOME}; the site may have been redesigned")
        try:
            page_html = _get(page_url, timeout=45).decode(
                "utf-8", errors="replace")
        except Exception as exc:
            return MirrorLookup("unreachable", page_url=page_url,
                                detail=f"could not fetch {page_url}: {exc}")

    by_filename = _versions_on_page(page_html)
    labelled = _labelled_current(page_html)

    if not by_filename and not labelled:
        return MirrorLookup(
            "unparsed", page_url=page_url,
            detail="no Rules Reference links found on the rulings page; "
                   "its markup has probably changed")

    if by_filename:
        _, version, url = by_filename[-1]
        if labelled and labelled[0] != version:
            return MirrorLookup(
                "disagree", page_url=page_url,
                detail=f"the highest linked version is {version} but the "
                       f'"{MIRROR_SECTION}" section names '
                       f"{labelled[0]}; not guessing which is current")
        return MirrorLookup("ok", version=version, url=url,
                            page_url=page_url)

    version, url = labelled
    return MirrorLookup("ok", version=version, url=url, page_url=page_url)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version))


def rr_version_from_filename(url: str) -> str | None:
    """FFG encodes the version in the filename: mc_rulesreference_v18…"""
    m = re.search(r"rulesreference[_-]?v(\d)(\d+)", url, re.I)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    m = re.search(r"marvelrrg(\d)(\d+)", url, re.I)
    return f"{m.group(1)}.{m.group(2)}" if m else None


def check_rr_currency(result: ManifestResult,
                      mirror: MirrorLookup | None = None) -> dict | None:
    """Compare the manifest's Rules Reference against the mirror's.

    Returns None only when the manifest is genuinely current. Every other
    outcome - behind, or the check could not run - comes back as a dict
    with a `status`, so a broken oracle can never read as a clean bill of
    health.
    """
    rr = next((d for d in result.docs
               if d.slug == "marvel-champions-rules-reference"), None)
    if rr is None:
        return {"status": "unknown",
                "detail": "no Rules Reference in the manifest"}

    have = rr_version_from_filename(rr.url)
    if not have:
        return {"status": "unknown",
                "detail": f"cannot read a version from {rr.url}"}

    mirror = mirror if mirror is not None else current_rr_from_mirror()
    if not mirror.ok:
        return {"status": "unknown", "have": have,
                "detail": f"{mirror.source_name} check unavailable "
                          f"({mirror.status}): {mirror.detail}"}

    if _version_key(mirror.version) <= _version_key(have):
        return None

    return {"status": "behind", "have": have, "current": mirror.version,
            "url": mirror.url, "source_name": mirror.source_name}
