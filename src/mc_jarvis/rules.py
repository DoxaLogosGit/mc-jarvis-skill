"""Rules queries (spec §5.1, §9). Every answer carries a citation."""
from __future__ import annotations

import re
import sqlite3

from .cards import _fts_query, _open
from .cli import emit


_PLACEHOLDER_RE = re.compile(r"\s+X$", re.I)


def plain_term(term: str) -> str:
    """An entry term with its printed decoration removed.

    The Rules Reference titles entries as they appear on the page -
    "Retaliate X", "Cost Arrow Icon ( \u2192)" - while a player asks for
    "retaliate". Matching on this makes the difference invisible.
    """
    term = (term or "").split("(")[0]
    term = _PLACEHOLDER_RE.sub("", " ".join(term.split()))
    return term.strip().lower()


def register(conn) -> None:
    """Expose `plain_term` to SQL so the fallback can compare in-query."""
    conn.create_function("_plain_term", 1, plain_term)


def show(conn, term: str) -> dict:
    """One Rules Reference entry, with its page.

    Prefers an addressable entry: a pointer carries a citation but no
    rules text, so it must never win over an entry that has both.
    """
    register(conn)
    row = conn.execute(
        "SELECT id, term, body, page, source_doc, entry_addressable "
        "FROM rules_entries WHERE lower(term) = lower(?) "
        "ORDER BY entry_addressable DESC LIMIT 1", (term,)).fetchone()

    if row is None:
        # Entry terms carry printed decoration a player does not type:
        # an icon - "Cost Arrow Icon ( \u2192)", "Amplify Icon ([amplify])"
        # - or the RR's numeric placeholder, as in "Retaliate X". Compare
        # on the term with both stripped. Still an exact match, just
        # tolerant of what is printed on the page.
        row = conn.execute(
            "SELECT id, term, body, page, source_doc, entry_addressable "
            "FROM rules_entries WHERE _plain_term(term) = _plain_term(?) "
            "ORDER BY entry_addressable DESC LIMIT 1", (term,)).fetchone()

    if row is None:
        return {"term": None, "suggestions": search(conn, term, limit=5)}

    see_also = [r["target"] for r in conn.execute(
        "SELECT target FROM rules_see_also "
        "WHERE lower(term) = lower(?) AND source_doc = ?",
        (row["term"], row["source_doc"]))]

    cards = [dict(r) for r in conn.execute(
        "SELECT c.code, c.name, c.type_code FROM card_rules_links l "
        "JOIN cards c ON c.code = l.code "
        "WHERE lower(l.term) = lower(?) AND c.code = c.canonical_code "
        "ORDER BY c.code LIMIT 40", (row["term"],))]

    return {"term": row["term"], "body": row["body"], "page": row["page"],
            "source_doc": row["source_doc"],
            "entry_addressable": bool(row["entry_addressable"]),
            "see_also": see_also, "cards": cards}


def search(conn, text: str, *, limit: int = 10) -> list[dict]:
    expr = _fts_query(text)
    if not expr:
        return []
    rows = conn.execute(
        "SELECT e.term, e.body, e.page, e.source_doc, e.entry_addressable "
        "FROM rules_fts f JOIN rules_entries e ON e.id = f.rowid "
        "WHERE rules_fts MATCH ? ORDER BY rank LIMIT ?", (expr, limit))
    return [{**dict(r), "entry_addressable": bool(r["entry_addressable"])}
            for r in rows]


def build_links(conn: sqlite3.Connection) -> int:
    """Join keyword occurrences in card text to Rules Reference entries.

    One table serves both directions: `card show --explain` expands a
    card's keywords, and `rules show` lists the cards that use one.
    """
    conn.execute("DELETE FROM card_rules_links")
    conn.execute(
        "INSERT OR IGNORE INTO card_rules_links (code, term, source_doc) "
        "SELECT k.code, e.term, e.source_doc "
        "FROM card_keywords k JOIN rules_entries e "
        "  ON lower(e.term) = lower(k.keyword) "
        "WHERE e.entry_addressable = 1")
    conn.commit()
    return conn.execute(
        "SELECT COUNT(*) FROM card_rules_links").fetchone()[0]


def explain(conn, code: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT e.term, e.body, e.page, e.source_doc "
        "FROM card_rules_links l "
        "JOIN rules_entries e ON e.term = l.term "
        "  AND e.source_doc = l.source_doc "
        "WHERE l.code = ? ORDER BY e.term", (code,))]


def _cite(row: dict) -> str:
    page = f"p.{row['page']}" if row.get("page") else "no page"
    suffix = "" if row.get("entry_addressable", True) else "  (page pointer)"
    return f"[{row['source_doc']} {page}]{suffix}"


def handle_show(args) -> int:
    conn = _open()
    result = show(conn, args.term)
    if args.json:
        emit(result, as_json=True)
        return 0 if result["term"] else 1
    if not result["term"]:
        print(f"no rules entry named {args.term!r}")
        if result["suggestions"]:
            print("\nclosest full-text matches:")
            for s in result["suggestions"]:
                print(f"  {s['term']}  {_cite(s)}")
        return 1
    print(f"{result['term']}  {_cite(result)}\n")
    print(" ".join(result["body"].split()) if not result["entry_addressable"]
          else result["body"])
    if result["see_also"]:
        print(f"\nSee also: {', '.join(result['see_also'])}")
    if result["cards"]:
        print(f"\nCards using this keyword ({len(result['cards'])}):")
        for c in result["cards"][:20]:
            print(f"  {c['code']:<8} {c['name']}")
    return 0


def handle_search(args) -> int:
    conn = _open()
    hits = search(conn, args.text)
    if args.json:
        emit(hits, as_json=True)
        return 0 if hits else 1
    if not hits:
        print("no matches")
        return 1
    for h in hits:
        body = " ".join(h["body"].split())
        print(f"\n{h['term']}  {_cite(h)}")
        print(f"  {body[:300]}{'...' if len(body) > 300 else ''}")
    return 0
