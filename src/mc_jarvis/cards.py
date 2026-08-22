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


FULL = SUMMARY + ("set_code", "back_link", "is_unique", "permanent",
                  "deck_limit", "quantity", "canonical_code", "is_reprint",
                  "attack", "thwart", "defense", "recover", "health",
                  "hand_size", "resource_physical", "resource_mental",
                  "resource_energy", "resource_wild", "flavor")


def _row(conn, code) -> dict | None:
    r = conn.execute(
        f"SELECT {', '.join(FULL)} FROM cards WHERE code = ?",
        (code,)).fetchone()
    return dict(r) if r else None


def _faces(conn, card: dict) -> list[dict]:
    """A card and every face linked to it, in code order.

    `back_link` points hero -> alter-ego and is null on extra forms, so
    the walk follows it in both directions (spec §8).
    """
    seen: set[str] = set()
    queue = [card["code"]]
    out: list[dict] = []
    while queue:
        code = queue.pop()
        if code in seen:
            continue
        seen.add(code)
        row = _row(conn, code)
        if not row:
            continue
        out.append(row)
        if row.get("back_link"):
            queue.append(row["back_link"])
        for other in conn.execute(
                "SELECT code FROM cards WHERE back_link = ?", (code,)):
            queue.append(other["code"])
    return sorted(out, key=lambda r: r["code"])


def printings(conn, canonical_code: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT code, pack_code, quantity FROM cards "
        "WHERE canonical_code = ? ORDER BY code", (canonical_code,))]


def show(conn, ident: str) -> dict:
    """One card, or the candidates when a name is ambiguous.

    Never guesses: 60 character names exist as both an identity face and
    an ally, so "Black Panther" is genuinely several cards (spec §8).
    """
    exact = _row(conn, ident)
    if exact:
        canon = _row(conn, exact["canonical_code"]) or exact
        return {"card": canon, "faces": _faces(conn, canon),
                "printings": printings(conn, canon["code"])}

    matches = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(SUMMARY)} FROM cards "
        f"WHERE lower(name) = lower(?) AND code = canonical_code "
        f"ORDER BY code", (ident,))]

    if len(matches) == 1:
        card = _row(conn, matches[0]["code"])
        return {"card": card, "faces": _faces(conn, card),
                "printings": printings(conn, card["code"])}
    return {"ambiguous": matches}


def _print_card(c: dict) -> None:
    title = c["name"] + (f" - {c['subname']}" if c.get("subname") else "")
    print(f"\n{title}  [{c['code']}]")
    line = f"  {c['faction_code']} {c['type_code']}"
    if c.get("cost") is not None:
        line += f", cost {c['cost']}"
    if c.get("is_unique"):
        line += ", unique"
    if c.get("permanent"):
        line += ", permanent"
    print(line)
    stats = [(k, c.get(k)) for k in
             ("attack", "thwart", "defense", "recover", "health", "hand_size")
             if c.get(k) is not None]
    if stats:
        print("  " + "  ".join(f"{k.upper()[:3]} {v}" for k, v in stats))
    if c.get("traits"):
        print(f"  {c['traits']}")
    if c.get("text"):
        print(f"  {c['text']}")


def handle_show(args) -> int:
    conn = _open()
    result = show(conn, args.name)
    if getattr(args, "explain", False) and "card" in result:
        from . import rules
        result["keywords"] = rules.explain(conn, result["card"]["code"])
    if args.json:
        emit(result, as_json=True)
        return 0 if "card" in result else 1
    if "card" in result:
        for face in result["faces"]:
            _print_card(face)
        packs = result["printings"]
        if len(packs) > 1:
            print("\n  Printings: " + ", ".join(
                f"{p['pack_code']} x{p['quantity']}" for p in packs))
        for kw in result.get("keywords", []):
            print(f"\n  {kw['term']} (p.{kw['page']}) - {kw['body']}")
        return 0
    if not result["ambiguous"]:
        print(f"no card named {args.name!r}")
        return 1
    print(f"{args.name!r} matches several cards - pick one by code:")
    for c in result["ambiguous"]:
        print(f"  {c['code']:<8} {c['name']:<30} "
              f"{c['type_code']:<10} {c['faction_code']}")
    return 1
