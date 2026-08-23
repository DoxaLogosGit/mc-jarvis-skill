"""Designer rulings issued between Rules Reference versions (Task 18).

FFG designers answer rules questions between Rules Reference releases.
Those answers are authoritative, they post-date the rulebook, and some of
them say the rulebook is wrong. A citation to superseded text is still a
wrong answer, and worse than none because it reads as authoritative.

What keeps this small: **a new Rules Reference supersedes every ruling
published before it.** So the live set is bounded by one release cycle,
and it is relative to the edition the user actually holds. Superseded
rulings are kept and flagged rather than dropped, so `update` can report
the transition and a player can ask what happened to an old ruling.

Everything fetched here is third-party prose quoting a designer. It is
stored as DATA and shown as a quotation. Nothing inside a question or an
answer is ever treated as an instruction, however it is phrased.

The source is opt-in. An index built without it simply has no rulings,
which is not a failure - but a page that fetches and then parses to
nothing IS one, and says so rather than reading as "no rulings".
"""
from __future__ import annotations

import datetime as dt
import html as _html
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

TAG_RE = re.compile(r"<[^>]+>")
BLOCKQUOTE_RE = re.compile(r"<blockquote\b", re.I)
BLOCKQUOTE_END_RE = re.compile(r"</blockquote>", re.I)

MONTHS = ("January|February|March|April|May|June|July|August|September"
          "|October|November|December")
# `<strong>-Alex – July 9, 2026</strong>` closes each ruling. The dash is
# an en dash on the live page and a hyphen elsewhere, so admit both.
SIGNATURE_RE = re.compile(
    rf"<strong>\s*[-‐-―]\s*([A-Za-z .'-]{{2,40}}?)\s*"
    rf"[-‐-―]\s*((?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}})\s*</strong>",
    re.I)

# The Rules Reference wraps its change log mid-quote, so the text is
# joined before the entries are split out.
QUOTED_RE = re.compile(r"[“\"']([^”\"']{2,60})[”\"']")


@dataclass
class Ruling:
    question: str
    answer: str
    author: str | None
    ruled_on: dt.date
    source_url: str


@dataclass
class RulingsLookup:
    """Every failure has a name.

    An empty result and a broken parser must never look alike: the whole
    point of this feature is that a live ruling is not silently missing.
    """
    status: str            # ok | unparsed | unreachable | disabled
    rulings: list[Ruling] = field(default_factory=list)
    detail: str = ""
    source_url: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


# Publishing platforms emit these as entities or as characters depending
# on the editor and the export. Matching only one form makes the parser
# pass on a fixture and find nothing on the live page, or the reverse.
_ENTITIES = {
    "&#8211;": "\u2013", "&ndash;": "\u2013",
    "&#8212;": "\u2014", "&mdash;": "\u2014",
    "&#8220;": "\u201c", "&ldquo;": "\u201c",
    "&#8221;": "\u201d", "&rdquo;": "\u201d",
    "&#8216;": "\u2018", "&#8217;": "\u2019", "&rsquo;": "\u2019",
    "&nbsp;": " ",
}


def _normalise(page_html: str) -> str:
    """Punctuation entities only. A blanket `unescape` here would turn an
    escaped `&lt;p&gt;` inside a quoted question into a real tag."""
    for entity, char in _ENTITIES.items():
        page_html = page_html.replace(entity, char)
    return page_html


def _text(fragment: str) -> str:
    return " ".join(_html.unescape(TAG_RE.sub(" ", fragment)).split())


def _parse_date(value: str) -> dt.date | None:
    for fmt in ("%B %d %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value.replace(",", "").strip(),
                                        fmt).date()
        except ValueError:
            continue
    return None


# --- parsing the curator's page --------------------------------------

def parse(page_html: str, *, source_url: str) -> RulingsLookup:
    """Split the page into rulings.

    Shape, measured 2026-08-23: a `<blockquote>` holds the player's
    question, the paragraphs after it hold the designer's answer, and a
    `<strong>-Author - Date</strong>` closes each one. The signature is
    the anchor; everything between it and the previous signature belongs
    to this ruling.
    """
    page_html = _normalise(page_html)
    out: list[Ruling] = []
    previous_end = 0
    for match in SIGNATURE_RE.finditer(page_html):
        segment = page_html[previous_end:match.start()]
        previous_end = match.end()

        ruled_on = _parse_date(match.group(2))
        if ruled_on is None:
            continue

        # The question is the LAST blockquote in the segment: an answer
        # may quote earlier discussion, and the closest one is the
        # question this answer belongs to.
        starts = [m.start() for m in BLOCKQUOTE_RE.finditer(segment)]
        if starts:
            tail = segment[starts[-1]:]
            end = BLOCKQUOTE_END_RE.search(tail)
            question = _text(tail[:end.start()] if end else tail)
            answer = _text(tail[end.end():] if end else "")
        else:
            question, answer = "", _text(segment)

        if not answer:
            continue
        out.append(Ruling(question=question, answer=answer,
                          author=match.group(1).strip() or None,
                          ruled_on=ruled_on, source_url=source_url))

    if not out:
        return RulingsLookup(
            "unparsed", source_url=source_url,
            detail=f"no rulings found at {source_url}; the page markup has "
                   f"probably changed. Rulings are not indexed - the Rules "
                   f"Reference is unaffected.")
    return RulingsLookup("ok", rulings=out, source_url=source_url)


CACHE_NAME = "rulings.html"


def cache_path(data_root: Path) -> Path:
    return data_root / "rules" / CACHE_NAME


def fetch(data_root: Path) -> RulingsLookup:
    """Fetch the curator's rulings page and cache it.

    Network work happens here so the index rebuild stays offline, exactly
    as the rulebook PDFs do. Failure is not fatal: rulings are additive
    and the Rules Reference answers on its own.
    """
    from . import manifest

    try:
        url = manifest.find_rulings_page()
    except Exception as exc:
        return RulingsLookup("unreachable",
                             detail=f"could not reach {manifest.MIRROR_NAME}: "
                                    f"{exc}")
    if url is None:
        return RulingsLookup(
            "unreachable", source_url=manifest.MIRROR_HOME,
            detail=f"no nav link labelled {manifest.MIRROR_NAV_LABEL!r} on "
                   f"{manifest.MIRROR_HOME}; the site may have been "
                   f"redesigned")
    try:
        body = manifest._get(url, timeout=45).decode("utf-8", errors="replace")
    except Exception as exc:
        return RulingsLookup("unreachable", source_url=url,
                             detail=f"could not fetch {url}: {exc}")

    found = parse(body, source_url=url)
    if found.ok:
        target = cache_path(data_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        (target.parent / "rulings-source.txt").write_text(url,
                                                          encoding="utf-8")
    return found


def load(data_root: Path) -> RulingsLookup:
    """Parse the cached page. Absent cache means rulings were never
    fetched, which is a supported state, not a failure."""
    path = cache_path(data_root)
    if not path.is_file():
        return RulingsLookup("disabled",
                             detail="no rulings cached; run `mc-jarvis "
                                    "update` with network access to add them")
    url_file = path.parent / "rulings-source.txt"
    url = url_file.read_text(encoding="utf-8").strip() if url_file.is_file() \
        else ""
    return parse(path.read_text(encoding="utf-8"), source_url=url)


# --- the date that decides everything --------------------------------

def _pdf_moddate(path: Path) -> dt.date | None:
    """When the Rules Reference PDF was finalised.

    `/ModDate` is the publication date; `/CreationDate` is when the layout
    file was made, months earlier.
    """
    try:
        from pypdf import PdfReader

        raw = (PdfReader(str(path)).metadata or {}).get("/ModDate")
    except Exception:
        return None
    m = re.search(r"(\d{4})(\d{2})(\d{2})", str(raw or ""))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def published_on(data_root: Path, *, rr_version: str | None,
                 manifest_docs) -> dt.date | None:
    """When the indexed Rules Reference was published.

    Two independent sources, and **the earliest wins**. An earlier date
    retains more rulings, which is the safe direction: over-reporting a
    ruling is a mild annoyance, and silently dropping a live one that
    contradicts the rulebook is the failure this feature exists to
    prevent.

    The manifest's date is only usable when the manifest describes the
    same edition that is indexed. After `init.take_current_rr` swaps in a
    newer Rules Reference the manifest still describes the archived one,
    and comparing v1.8 rulings against v1.7's January date would mark live
    rulings superseded.
    """
    from . import manifest as _manifest

    found: list[dt.date] = []

    pdf_date = _pdf_moddate(
        data_root / "rules" / "pdf" / "marvel-champions-rules-reference.pdf")
    if pdf_date:
        found.append(pdf_date)

    for doc in manifest_docs or []:
        get = doc.get if isinstance(doc, dict) else lambda k: getattr(doc, k, None)
        if get("slug") != "marvel-champions-rules-reference":
            continue
        listed = _manifest.rr_version_from_filename(get("url") or "")
        if rr_version and listed and listed != rr_version:
            continue                      # describes a different edition
        parsed = _parse_date(get("date") or "")
        if parsed:
            found.append(parsed)

    return min(found) if found else None


def classify(ruled_on: dt.date, published: dt.date | None) -> str:
    """`active` unless the Rules Reference is newer than the ruling.

    A ruling dated the same day as the Rules Reference stays active: the
    rulebook's text is frozen before it publishes, so a ruling issued that
    day cannot have been incorporated. With no publication date at all,
    everything is active and the caller warns.
    """
    if published is None:
        return "active"
    return "active" if ruled_on >= published else "superseded"


# --- storing ---------------------------------------------------------

def _quoted_terms(conn, ruling: Ruling) -> set[str]:
    """Rules Reference entries this ruling QUOTES.

    Not every entry it mentions. Measured 2026-08-23 on the real page:
    linking every term that merely appears gives 13.8 links per ruling and
    attaches 17 of 31 rulings to `Ability`. Quotation marks are how both
    the rulebook and the designers mark their subject.
    """
    text = f"{ruling.question}\n{ruling.answer}"
    candidates = {q.strip().lower() for q in QUOTED_RE.findall(text)}
    if not candidates:
        return set()
    rows = conn.execute(
        "SELECT term FROM rules_entries WHERE entry_addressable = 1")
    return {r["term"] for r in rows if r["term"].lower() in candidates}


def store(conn: sqlite3.Connection, items: list[Ruling], *,
          published: dt.date | None, source_name: str) -> dict:
    """Keep only the rulings the Rules Reference does not yet cover.

    A superseded ruling says the same thing the rulebook now says, and
    `rules show` already quotes the rulebook. Storing it would add a
    second voice saying nothing new, so it is dropped here rather than
    kept and filtered later.

    Returns what was stored and what was dropped, so `update` can report
    the moment a rulebook release absorbs a batch - which is exactly when
    a player's understanding needs to change.
    """
    conn.execute("DELETE FROM rulings")
    conn.execute("DELETE FROM ruling_terms")

    kept = dropped = 0
    for ruling in items:
        if classify(ruling.ruled_on, published) != "active":
            dropped += 1
            continue
        cur = conn.execute(
            "INSERT OR REPLACE INTO rulings "
            "(question, answer, author, ruled_on, source_name, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ruling.question, ruling.answer, ruling.author,
             ruling.ruled_on.isoformat(), source_name, ruling.source_url))
        conn.executemany(
            "INSERT OR IGNORE INTO ruling_terms (ruling_id, term) "
            "VALUES (?, ?)",
            [(cur.lastrowid, t) for t in sorted(_quoted_terms(conn, ruling))])
        kept += 1

    conn.execute("INSERT INTO rulings_fts(rulings_fts) VALUES('delete-all')")
    conn.execute("INSERT INTO rulings_fts(rowid, question, answer) "
                 "SELECT id, question, answer FROM rulings")
    conn.commit()
    return {"stored": kept, "superseded": dropped}


def prune(conn, published: dt.date | None) -> int:
    """Drop stored rulings the indexed Rules Reference now covers.

    Used when the source cannot be re-parsed but the rulebook may have
    moved on. Discarding the whole corpus because today's parse failed
    would make a transient breakage look identical to "never fetched",
    while leaving it untouched would keep quoting rulings the rulebook has
    since absorbed.
    """
    stale = [r["id"] for r in conn.execute("SELECT id, ruled_on FROM rulings")
             if (_parse_date(r["ruled_on"]) is not None
                 and classify(_parse_date(r["ruled_on"]), published)
                 != "active")]
    if stale:
        marks = ",".join("?" * len(stale))
        conn.execute(f"DELETE FROM ruling_terms WHERE ruling_id IN ({marks})",
                     stale)
        conn.execute(f"DELETE FROM rulings WHERE id IN ({marks})", stale)
        conn.execute("INSERT INTO rulings_fts(rulings_fts) VALUES('delete-all')")
        conn.execute("INSERT INTO rulings_fts(rowid, question, answer) "
                     "SELECT id, question, answer FROM rulings")
    conn.commit()
    return len(stale)


# --- reading ---------------------------------------------------------

_FIELDS = ("id", "question", "answer", "author", "ruled_on",
           "source_name", "source_url")
# Qualified: `rulings_fts` exposes `question` and `answer` too, so an
# unqualified list is ambiguous the moment the search joins them.
_COLUMNS = ", ".join(f"r.{f}" for f in _FIELDS)


def for_term(conn, term: str) -> list[dict]:
    """Rulings on this Rules Reference entry. Everything stored is in
    force - the rulebook already covers the rest."""
    return [dict(r) for r in conn.execute(
        f"SELECT {_COLUMNS} FROM rulings r "
        f"JOIN ruling_terms t ON t.ruling_id = r.id "
        f"WHERE lower(t.term) = lower(?) "
        f"ORDER BY r.ruled_on DESC", (term,))]


def search(conn, text: str, *, limit: int = 10) -> list[dict]:
    from .cards import _fts_query

    expr = _fts_query(text)
    if not expr:
        return []
    return [dict(r) for r in conn.execute(
        f"SELECT {_COLUMNS} FROM rulings_fts f "
        f"JOIN rulings r ON r.id = f.rowid "
        f"WHERE rulings_fts MATCH ? ORDER BY rank LIMIT ?", (expr, limit))]


def count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM rulings").fetchone()[0]


def latest(conn, limit: int = 25) -> list[dict]:
    return [dict(r) for r in conn.execute(
        f"SELECT {_COLUMNS} FROM rulings r ORDER BY r.ruled_on DESC LIMIT ?",
        (limit,))]


# --- cli -------------------------------------------------------------

def handle(args) -> int:
    from .cards import _open
    from .cli import emit

    conn = _open()
    text = getattr(args, "text", None)
    hits = search(conn, text) if text else latest(conn)
    total = count(conn)

    if getattr(args, "json", False):
        emit({"count": total, "rulings": hits}, as_json=True)
        return 0 if hits else 1

    if total == 0:
        # Empty is the normal state for a while after each Rules Reference
        # release: the new edition absorbed the outstanding rulings, and
        # absorbed ones are not kept.
        print("No designer rulings outstanding — the Rules Reference you "
              "hold covers everything ruled on so far.\n"
              "(If you have never run `mc-jarvis update` with network "
              "access, none have been fetched either; `mc-jarvis status` "
              "shows which.)")
        return 1
    if not hits:
        print(f"No match among the {total} ruling(s) the Rules Reference "
              f"does not yet cover.")
        return 1

    for r in hits:
        print(f"\n{r['ruled_on']} — {r['author'] or 'FFG'}, via "
              f"{r['source_name']}")
        if r["question"]:
            print(f"  Q: {r['question'][:400]}")
        print(f"  A: {r['answer'][:600]}")
    print(f"\n{total} ruling(s) not yet covered by the Rules Reference.")
    return 0
