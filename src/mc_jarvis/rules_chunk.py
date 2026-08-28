"""Rules Reference parsing (spec §9).

Task 13 adds the index parse, glyph mapping and entry chunker. What is
here now is the version check, needed early because it is what lets a
mirrored copy of the Rules Reference be trusted: the document states its
own version, so a claim made by whatever page linked it does not have to
be taken on faith.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from . import paths

# The Rules Reference prints its own version on page 1, next to the
# summary of notable changes.
VERSION_RE = re.compile(r"V\s*e\s*R?\s*sion\s*(\d+\.\d+)", re.I)


def declared_version(pages: list[str]) -> str | None:
    """The version the document states about itself.

    This is what makes a mirrored copy safe to use: the file proves its
    own identity, so a claim made by whatever page linked it does not have
    to be taken on trust.
    """
    if not pages:
        return None
    m = VERSION_RE.search(pages[0])
    return m.group(1) if m else None


class VersionMismatch(RuntimeError):
    """A downloaded Rules Reference is not the version it was said to be."""


def verify_version(pages: list[str], expected: str | None) -> str | None:
    found = declared_version(pages)
    if expected and found and found != expected:
        raise VersionMismatch(
            f"downloaded Rules Reference declares version {found}, but was "
            f"listed as {expected}; refusing to index it")
    return found


GLYPHS_PATH = paths.bundled("glyphs.yaml")
PUA = re.compile(r"[\ue000-\uf8ff]")

# "Term ......... 14", and "Term ..... 26, 27" for entries spanning
# pages. Without the second form the line fails to parse and merges into
# the next one, costing two entries rather than one.
ENTRY_RE = re.compile(r"^(.*?)[\s.]*\.{2,}[\s.]*(\d{1,3}(?:\s*,\s*\d{1,3})*)$")
# Running headers and folios bleed into the two-column index text:
# "2 Ru l e s R e f eR e n c e Max, Maximum". Strip the furniture rather
# than let it corrupt the term.
FURNITURE_RE = re.compile(
    r"^\s*\d{0,3}\s*R\s*u\s*l?\s*e\s*s\s*R\s*e\s*f\s*e?R?\s*e\s*n\s*c\s*e\s*",
    re.I)
# "Term ..... See Other Term"
REDIRECT_RE = re.compile(r"^(.*?)\.*\s*See\s+(.+)$")
# "Amplify Icon ()" - the glyph sits between the parentheses
GLYPH_NAME_RE = re.compile(r"^(.*?)\s*\(([\ue000-\uf8ff])\s*\)$")
# The RR prints "See also :" with a space before the colon, and the list
# wraps to the end of the entry. Verified 2026-08-21: the tighter
# `See also:\s*(.+)$` matched nothing in the real document.
SEE_ALSO_RE = re.compile(r"^[ \t]*See\s+also\s*:\s*(.+)\Z", re.M | re.S)
# Must admit a leading curly quote and glyphs: requiring ^[A-Z] silently
# dropped 36 of 216 entries - every quoted term and every icon entry.
# A header that ends on a dangling conjunction has wrapped: "PLAY
# RESTRICTIONS AND" / "PERMISSIONS". Only those are rejoined - merging
# every adjacent pair swallows an entry whose header simply follows a
# section title, such as GLOSSARY immediately above ABILITY.
CONTINUES_RE = re.compile(r"\b(AND|OR|OF|THE|TO|IN|A)$")

# The character class must admit the private-use icon codepoints too:
# entry headers like "ACCELERATION ICON ( )" carry one, and leaving the
# range out silently loses every icon entry - 13 of them.
HEADER_RE = re.compile(
    r"^[\u201c\"']?[A-Z][A-Z0-9 ,\u2019'\u201c\u201d/&()\u2192.\u2013\u2014"
    r"\ue000-\uf8ff-]{2,60}$")


@dataclass
class IndexResult:
    entries: list[tuple[str, int]] = field(default_factory=list)
    redirects: list[tuple[str, str]] = field(default_factory=list)
    glyphs: dict[str, str] = field(default_factory=dict)


@dataclass
class Entry:
    term: str
    body: str
    page: int | None
    source_doc: str
    entry_addressable: bool = True
    # Two different properties, and conflating them cost Learn to Play its
    # entire full-text index: a page-chunked document is not addressable
    # by entry name but must still be searchable (spec §9), while an
    # unresolved index pointer is neither.
    searchable: bool = True
    see_also: list[str] = field(default_factory=list)


def parse_index(pages: list[str], *, scan_pages: int = 3) -> IndexResult:
    """The Rules Reference carries its own index on PDF pages 2-3.

    That index is authoritative: 216 entries with page numbers plus 46
    `See ...` redirects. The alternative - scanning the body for ALL-CAPS
    headers - yields 386 candidates over 71 pages, most of them diagram
    labels and worked examples. The index also names every icon, which is
    where `glyphs.yaml` comes from.
    """
    result = IndexResult()
    blob = "\n".join(pages[1:scan_pages])
    buf = ""
    for line in (l.rstrip() for l in blob.split("\n")):
        if not line.strip() or line.strip().upper().startswith("INDEX"):
            continue
        buf = f"{buf} {line}".strip() if buf else line.strip()

        m = ENTRY_RE.match(buf)
        if m:
            term = FURNITURE_RE.sub("", m.group(1)).strip().strip(".").strip()
            first_page = int(m.group(2).split(",")[0])
            if term:
                result.entries.append((term, first_page))
            buf = ""
            continue

        m = REDIRECT_RE.match(buf)
        if m and not buf.rstrip().endswith(","):
            result.redirects.append(
                (m.group(1).strip().strip(".").strip(), m.group(2).strip()))
            buf = ""

    for term, _ in result.entries + [(t, None) for t, _ in result.redirects]:
        m = GLYPH_NAME_RE.match(term)
        if m:
            result.glyphs[m.group(2)] = m.group(1).strip()

    return result


def _headers(pages: list[str], first: int = 3,
             last: int = 49) -> list[tuple[int, int, str]]:
    """Entry headers in document order.

    A long header wraps onto a second line, and that continuation looks
    like a header of its own: "PLAY RESTRICTIONS AND" / "PERMISSIONS".
    Left split, the first gets an empty body and the second claims text
    that is not its own, so adjacent header lines are rejoined.
    """
    out: list[tuple[int, int, str]] = []
    for pi in range(first, min(last, len(pages))):
        for li, line in enumerate(pages[pi].split("\n")):
            s = line.strip()
            if not HEADER_RE.match(s) or re.match(r"^RU ?L ?E ?S", s, re.I):
                continue
            if (out and out[-1][0] == pi and out[-1][1] == li - 1
                    and CONTINUES_RE.search(out[-1][2])):
                prev_page, prev_line, prev_text = out[-1]
                out[-1] = (prev_page, prev_line, f"{prev_text} {s}")
            else:
                out.append((pi, li, s))
    return out


def _body_between(pages: list[str], heads: list[tuple[int, int, str]],
                  i: int) -> str:
    """One entry's body: from its header to the next header.

    Partitioning the document makes overlap impossible. Locating each
    index term independently and reading until any header produced 106%
    coverage - entries running past their end into their neighbour while
    others came back empty.
    """
    pi, li, _ = heads[i]
    nxt = heads[i + 1] if i + 1 < len(heads) else (len(pages), 0, None)
    out: list[str] = []
    for page_no in range(pi, min(nxt[0], len(pages) - 1) + 1):
        lines = pages[page_no].split("\n")
        start = li + 1 if page_no == pi else 0
        stop = nxt[1] if page_no == nxt[0] else len(lines)
        out += lines[start:stop]
    return "\n".join(out).strip()


def match_key(term: str) -> str:
    """Normalise an index term or a body header to a comparable key.

    The two spellings differ invisibly until it costs an entry: the index
    writes "Delayed Effects" where the body writes "DELAYED EFFECT", and
    "Boost, Boost Icon ()" where the body writes "BOOST".
    """
    s = PUA.sub("", term).replace("\u2192", "")
    # Two-column index lines bleed the tail of the previous entry into
    # the next: "Activation) Unique Icon" is really "Unique Icon".
    s = re.sub(r"^[^()]*\)\s*", "", s)
    s = s.split(",")[0]                     # RR alphabetises before the comma
    s = re.sub(r"\(.*?\)", "", s)           # "(Card Title)", "(Trait)"
    s = re.sub(r"^the\s+", "", s.strip(), flags=re.I)
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return re.sub(r"s$", "", s)             # singular/plural


def chunk_entries(pages: list[str], index: IndexResult, *,
                  source_doc: str) -> list[Entry]:
    heads = _headers(pages)
    bodies: dict[str, tuple[str, str]] = {}
    for i, (_, _, header) in enumerate(heads):
        bodies.setdefault(match_key(header),
                          (header, _body_between(pages, heads, i)))

    # An index term and its body header can be worded differently, and
    # the header may be truncated where it wrapped: "In Play" is headed
    # "IN PLAY AND OUT OF PLAY", and "Play Restrictions and Permissions"
    # is headed "PLAY RESTRICTIONS AND". Fall back to a prefix match,
    # but only onto a header no exact match has already claimed - "In
    # Play" must not steal the body belonging to "In Player Order".
    claimed = {match_key(term) for term, _ in index.entries
               if match_key(term) in bodies}

    def resolve(term: str):
        key = match_key(term)
        if key in bodies:
            return bodies[key]
        candidates = [(k, v) for k, v in bodies.items()
                      if k not in claimed
                      and (k.startswith(key) or key.startswith(k))]
        if not candidates:
            return None
        # Prefer the longest shared prefix: "Play Restrictions and
        # Permissions" prefix-matches both "PLAY RESTRICTIONS AND" (its
        # header, wrapped) and a bare "PLAY". The longer one is right.
        candidates.sort(key=lambda kv: len(kv[0]), reverse=True)
        if len(candidates) > 1 and len(candidates[0][0]) == len(candidates[1][0]):
            return None          # genuinely ambiguous; do not guess
        return candidates[0][1]

    def recover_merged(term: str):
        """Two-column index lines can weld a stray fragment onto the front
        of a real entry: "Variable You, Your" is the p.49 entry
        "You, Your" with debris attached. Try the longest suffix that
        resolves, so the entry is recovered rather than lost."""
        words = term.split()
        for start in range(1, len(words)):
            suffix = " ".join(words[start:])
            found = resolve(suffix)
            if found and found[1]:
                return suffix, found
        return None, None

    entries = []
    for term, page in index.entries:
        found = resolve(term)
        if found is None or not found[1]:
            recovered, alt = recover_merged(term)
            if alt is not None:
                term, found = recovered, alt
        body = found[1] if found else ""

        if not body:
            # Never store an addressable entry with an empty body: a
            # blank reads as an answer. Keep the citation, say plainly
            # that the text was not extracted, and mark it non-
            # addressable so the CLI labels it and search skips it.
            entries.append(Entry(
                term=term,
                body=(f"Listed in the Rules Reference index at page "
                      f"{page}, outside the glossary text this index "
                      f"covers. Consult the rulebook at that page."),
                page=page, source_doc=source_doc,
                entry_addressable=False, searchable=False))
            continue

        see_also: list[str] = []
        m = SEE_ALSO_RE.search(body)
        if m:
            tail = " ".join(m.group(1).split())
            see_also = [s.strip() for s in tail.split(",") if s.strip()]
            body = body[:m.start()].strip()
        entries.append(Entry(term=term, body=body, page=page,
                             source_doc=source_doc, entry_addressable=True,
                             see_also=see_also))
    for term, target in index.redirects:
        entries.append(Entry(term=term, body=f"See {target}.", page=None,
                             source_doc=source_doc, entry_addressable=True,
                             see_also=[target]))
    return entries


def chunk_pages(pages: list[str], *, source_doc: str) -> list[Entry]:
    """Non-RR documents lack the alphabetical entry structure, so they
    are chunked by page with their leading heading. Searchable, not
    entry-addressable - and the CLI labels the difference (spec §9)."""
    out = []
    for n, text in enumerate(pages, start=1):
        body = text.strip()
        if not body:
            continue
        first = next((l.strip() for l in body.split("\n") if l.strip()), "")
        out.append(Entry(term=f"{source_doc} p.{n}: {first[:60]}",
                         body=body, page=n, source_doc=source_doc,
                         entry_addressable=False, searchable=True))
    return out


def extraction_report(pages: list[str], index: IndexResult) -> dict:
    """What the chunker captured, and what it did not.

    A rules index that silently drops entries is worse than one that
    fails: every downstream answer stays confidently wrong.
    """
    entries = chunk_entries(pages, index, source_doc="_audit")
    unresolved = [e.term for e in entries
                  if e.page is not None and not e.entry_addressable]
    glossary = re.sub(r"\s+", "", "".join(pages[3:49]))
    captured = re.sub(r"\s+", "", "".join(
        e.body for e in entries if e.page is not None))
    return {"index_entries": len(index.entries),
            "resolved": len(index.entries) - len(unresolved),
            "unresolved": unresolved,
            "coverage": round(len(captured) / max(len(glossary), 1), 3)}


def load_glyphs(path: Path | None = None) -> dict[str, str]:
    p = path or GLYPHS_PATH
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = {}
    for key, value in (raw.get("glyphs") or {}).items():
        if isinstance(key, str) and key.upper().startswith("U+"):
            out[chr(int(key[2:], 16))] = value
        else:
            out[key] = value
    return out


def apply_glyphs(text: str, mapping: dict[str, str]) -> tuple[str, set[str]]:
    """Map private-use codepoints to readable tokens. Unmapped codepoints
    are preserved verbatim and reported, never silently stripped."""
    unmapped = {c for c in PUA.findall(text) if c not in mapping}
    for glyph, token in mapping.items():
        text = text.replace(glyph, f"[{token}]")
    return text, unmapped


class EmptyEntry(RuntimeError):
    """An addressable entry has no body. A blank answer reads as an
    answer, so this fails the build rather than reaching a player."""


def store(conn: sqlite3.Connection, entries: list[Entry]) -> int:
    blank = [e.term for e in entries if e.entry_addressable and not e.body]
    if blank:
        raise EmptyEntry(
            f"{len(blank)} addressable rules entries have no body: "
            f"{blank[:5]}. Store them as non-addressable pointers instead, "
            f"so the citation survives without a blank posing as a ruling.")

    for doc in {e.source_doc for e in entries}:
        conn.execute("DELETE FROM rules_entries WHERE source_doc = ?", (doc,))
        conn.execute("DELETE FROM rules_see_also WHERE source_doc = ?", (doc,))

    conn.executemany(
        "INSERT OR REPLACE INTO rules_entries "
        "(term, body, page, source_doc, entry_addressable, searchable) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(e.term, e.body, e.page, e.source_doc, int(e.entry_addressable),
          int(e.searchable)) for e in entries])
    conn.executemany(
        "INSERT OR IGNORE INTO rules_see_also (term, target, source_doc) "
        "VALUES (?, ?, ?)",
        [(e.term, t, e.source_doc) for e in entries for t in e.see_also])

    conn.execute("INSERT INTO rules_fts(rules_fts) VALUES('delete-all')")
    # Redirects carry no page, and a search hit with no page would break
    # the citation guarantee. They stay reachable by name through
    # `rules show`, but out of the full-text index. Filtering on
    # `entry_addressable` instead of `searchable` here is what silently
    # cost Learn to Play all 24 of its pages: page-chunked content is not
    # addressable by name, which is not the same as not being searchable.
    conn.execute(
        "INSERT INTO rules_fts(rowid, term, body) "
        "SELECT id, term, body FROM rules_entries "
        "WHERE page IS NOT NULL AND searchable = 1")
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM rules_entries").fetchone()[0]
