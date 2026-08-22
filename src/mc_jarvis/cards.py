"""Card queries (spec §5.1)."""
from __future__ import annotations

import re

from . import index, paths
from .cli import emit

SUMMARY = ("code", "name", "subname", "type_code", "faction_code",
           "cost", "pack_code", "traits", "text")

_COST = re.compile(r"^(<=|>=|<|>|=)?\s*(\d+)$")


def _fts_query(raw: str) -> str:
    """Turn a human phrase into a safe FTS5 MATCH expression.

    Every token is double-quoted, so FTS5 operators and the punctuation in
    card names (Sp//dr, Alter-Ego) are literals rather than syntax. A
    player's words are not a query language.
    """
    tokens = re.findall(r"[\w'/-]+", raw)
    if not tokens:
        return ""
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def search(conn, query=None, *, aspect=None, type=None, cost=None,
           trait=None, text=None, limit=20) -> list[dict]:
    """Search cards, one row per card rather than per printing.

    351 rows in the corpus are reprints of another card (§8 correction in
    the plan). Returning every printing would show the same card three
    times, so results collapse on `canonical_code` and report the original
    printing.
    """
    where = ["cards.code = cards.canonical_code"]
    params: list[object] = []

    if query:
        expr = _fts_query(query)
        if expr:
            where.append(
                "cards.canonical_code IN ("
                "  SELECT m.canonical_code FROM cards_fts f "
                "  JOIN cards m ON m.rowid = f.rowid "
                "  WHERE cards_fts MATCH ?)")
            params.append(expr)

    if aspect:
        where.append("cards.faction_code = ?")
        params.append(aspect)
    if type:
        where.append("cards.type_code = ?")
        params.append(type)
    if trait:
        where.append("cards.traits LIKE ?")
        params.append(f"%{trait}%")
    if text:
        where.append("cards.text LIKE ?")
        params.append(f"%{text}%")
    if cost:
        m = _COST.match(str(cost).strip())
        if not m:
            raise ValueError(
                f"unparseable cost filter: {cost!r} (try 2, <=3, >1)")
        where.append(f"cards.cost {m.group(1) or '='} ?")
        params.append(int(m.group(2)))

    sql = (f"SELECT {', '.join('cards.' + c for c in SUMMARY)} FROM cards "
           f"WHERE {' AND '.join(where)} ORDER BY cards.code LIMIT ?")
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def _open():
    db = paths.db_path()
    if not db.exists():
        raise SystemExit("no index found - run `mc-jarvis init` first")
    return index.connect(db)


def handle_search(args) -> int:
    conn = _open()
    try:
        hits = search(conn, args.query, aspect=args.aspect, type=args.type,
                      cost=args.cost, trait=args.trait, text=args.text,
                      limit=args.limit)
    except ValueError as exc:
        print(f"mc-jarvis: {exc}")
        return 2
    if args.json:
        emit(hits, as_json=True)
        return 0
    if not hits:
        print("no matches")
        return 1
    for h in hits:
        cost = "-" if h["cost"] is None else h["cost"]
        print(f"{h['code']:<8} {h['name']:<34} "
              f"{h['faction_code']:<12} {h['type_code']:<10} {cost}")
    return 0
