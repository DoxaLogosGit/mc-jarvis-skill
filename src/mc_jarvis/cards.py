"""Card queries (spec §5.1)."""
from __future__ import annotations

import re

from . import cardtext, index, paths
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


class Results(list):
    """Search hits, plus whether the limit cut them short.

    Truncation is a property of the result SET, not of any card in it, so
    it does not belong on the rows -- putting it there leaked a
    `truncated` key into every record of the JSON output. A list subclass
    keeps `len`, indexing and equality working for every existing caller.
    """

    truncated = False


def search(conn, query=None, *, owned=False, aspect=None, type=None, cost=None,
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

    # `--owned` was declared on five commands and read by none of them:
    # the flag parsed, and every result came back unfiltered. An empty
    # collection still filters nothing (see collection.filter_codes) --
    # not having said what you own is not the same as owning nothing.
    if owned:
        from .collection import owned_packs, owned_predicate
        if owned_packs(conn):
            where.append("cards." + owned_predicate())

    # One row more than asked for, so the caller can tell "exactly 20
    # matches" from "the first 20 of many". A search that silently stops
    # at the limit reads as an exhaustive answer: `--aspect justice`
    # showed 20 rows against 134 matching cards, with nothing to say so.
    sql = (f"SELECT {', '.join('cards.' + c for c in SUMMARY)} FROM cards "
           f"WHERE {' AND '.join(where)} ORDER BY cards.code LIMIT ?")
    params.append(limit + 1)
    rows = [dict(r) for r in conn.execute(sql, params)]
    out = Results(rows[:limit])
    out.truncated = len(rows) > limit
    return out


def _open():
    db = paths.db_path()
    if not db.exists():
        raise SystemExit("no index found - run `mc-jarvis init` first")
    try:
        return index.connect(db)
    except index.StaleIndex as exc:
        # Every read command funnels through here, so this is where a
        # stale index has to stop rather than be silently rebuilt out
        # from under the question being asked.
        raise SystemExit(f"mc-jarvis: {exc}")


def handle_search(args) -> int:
    conn = _open()
    try:
        hits = search(conn, args.query, owned=getattr(args, 'owned', False),
                      aspect=args.aspect, type=args.type,
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
    if getattr(hits, "truncated", False):
        print(f"\n(first {len(hits)}; more match - raise --limit or "
              f"narrow the search)")
    return 0


# The game's own abbreviations. A naive `k.upper()[:3]` produced ATT, HEA
# and HAN, none of which appears on a card.
STAT_LABELS = {
    "attack": "ATK", "thwart": "THW", "scheme": "SCH", "defense": "DEF",
    "recover": "REC", "health": "HP", "hand_size": "HAND",
}

FULL = SUMMARY + ("set_code", "back_link", "is_unique", "permanent",
                  "deck_limit", "quantity", "canonical_code", "is_reprint",
                  "attack", "thwart", "attack_cost", "thwart_cost",
                  "defense", "recover", "health",
                  "health_per_hero", "scheme", "stage",
                  "hand_size", "resource_physical", "resource_mental",
                  "resource_energy", "resource_wild", "flavor",
                  "base_threat", "base_threat_fixed", "escalation_threat",
                  "escalation_threat_fixed", "target_threat",
                  "target_threat_fixed", "boost", "boost_star",
                  "scheme_acceleration", "scheme_amplify", "scheme_crisis",
                  "scheme_hazard")

SCHEME_ICONS = ("acceleration", "amplify", "crisis", "hazard")


def _threat(value, fixed) -> str:
    # -1 is upstream's marker for a value printed as X.
    if value < 0:
        return "X"
    return f"{value}" + ("" if fixed else " per hero")


def scheme_line(c: dict) -> str | None:
    """A scheme's threat as printed: where it starts, what a main scheme
    adds each villain phase, and what completes it.

    Left out for a long time, and the gap was invisible from inside - an
    agent asked for The Hood's clock searched `card show --json` for
    threat, found nothing, and told the player the index lacked it."""
    bits = []
    if c.get("base_threat") is not None:
        bits.append("starts at " + _threat(c["base_threat"],
                                            c.get("base_threat_fixed")))
    if c.get("escalation_threat"):
        bits.append("+" + _threat(c["escalation_threat"],
                                  c.get("escalation_threat_fixed"))
                    + " each villain phase")
    if c.get("target_threat"):
        bits.append("completes at " + _threat(c["target_threat"],
                                               c.get("target_threat_fixed")))
    return "threat: " + ", ".join(bits) if bits else None


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


def show(conn, ident: str, *, owned: bool = False) -> dict:
    """One card, or the candidates when a name is ambiguous.

    Never guesses: 60 character names exist as both an identity face and
    an ally, so "Black Panther" is genuinely several cards (spec §8).
    """
    exact = _row(conn, ident)
    if exact:
        canon = _row(conn, exact["canonical_code"]) or exact
        return {"card": canon, "faces": _faces(conn, canon),
                "printings": printings(conn, canon["code"])}

    # An ambiguous name narrows usefully when the player owns only some
    # of the candidates: three Colossus cards become one.
    gate = ""
    if owned:
        from .collection import owned_packs, owned_predicate
        if owned_packs(conn):
            gate = f" AND {owned_predicate()}"
    matches = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(SUMMARY)} FROM cards "
        f"WHERE lower(name) = lower(?) AND code = canonical_code{gate} "
        f"ORDER BY code", (ident,))]

    if len(matches) == 1:
        card = _row(conn, matches[0]["code"])
        return {"card": card, "faces": _faces(conn, card),
                "printings": printings(conn, card["code"])}
    # Both sides of one main scheme share a name, so "Making Connections"
    # matched 24004a and 24004b and asked which - of a single card.
    if matches:
        card = _row(conn, matches[0]["code"])
        faces = _faces(conn, card)
        if {m["code"] for m in matches} <= {f["code"] for f in faces}:
            return {"card": card, "faces": faces,
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
    stats = [(STAT_LABELS[k], c.get(k)) for k in STAT_LABELS
             if c.get(k) is not None]
    if stats:
        line = "  " + "  ".join(f"{k} {v}" for k, v in stats)
        if c.get("health_per_hero"):
            line += "  (HP per hero)"
        print(line)
    # Consequential damage: what the ally pays out of its own hit points
    # each time it uses that power (RR p.13). Printed beneath the stat it
    # prices, and different on 56 allies, so it is shown beside each.
    costs = [(STAT_LABELS[k], c.get(f"{k}_cost")) for k in
             ("attack", "thwart") if c.get(f"{k}_cost") is not None]
    if costs:
        print("  consequential damage: "
              + "  ".join(f"{k} {v}" for k, v in costs))
    threat = scheme_line(c)
    if threat:
        print(f"  {threat}")
    icons = [i for i in SCHEME_ICONS if c.get(f"scheme_{i}")]
    if icons:
        print("  icons: " + ", ".join(
            f"{i} x{c[f'scheme_{i}']}" if c[f"scheme_{i}"] > 1 else i
            for i in icons))
    if c.get("boost") is not None or c.get("boost_star"):
        print(f"  boost {c.get('boost') or 0}"
              + (" + star" if c.get("boost_star") else ""))
    if c.get("traits"):
        print(f"  {c['traits']}")
    if c.get("text"):
        print(f"  {cardtext.render(c['text'])}")


def handle_show(args) -> int:
    conn = _open()
    result = show(conn, args.name, owned=getattr(args, 'owned', False))
    if getattr(args, "explain", False) and "card" in result:
        from . import rules
        result["keywords"] = rules.explain(conn, result["card"]["code"])
    if args.json:
        emit(result, as_json=True)
        return 0 if "card" in result else 1
    if "card" in result:
        for face in result["faces"]:
            _print_card(face)
        limits = [dict(r) for r in conn.execute(
            "SELECT kind, count, scope, phrase FROM play_limits "
            "WHERE code = ? ORDER BY kind, scope",
            (result["card"]["code"],))]
        card = result["card"]
        if card.get("deck_limit"):
            print(f"\n  Deck limit: {card['deck_limit']}"
                  + ("  (unique)" if card.get("is_unique") else ""))
        for lim in limits:
            label = "in play" if lim["kind"] == "in_play" else "use"
            print(f"  Limit ({label}): {lim['phrase']}")
        packs = result["printings"]
        if len(packs) > 1:
            print("\n  Printings: " + ", ".join(
                f"{p['pack_code']} x{p['quantity']}" for p in packs))
        for kw in result.get("keywords", []):
            print(f"\n  {kw['term']} (p.{kw['page']}) - {kw['body']}")
        return 0
    if not result["ambiguous"]:
        # With `--owned` the card may exist and simply not be yours, and
        # saying it does not exist would send the reader looking for a
        # typo that is not there.
        unfiltered = show(conn, args.name) if getattr(
            args, "owned", False) else {}
        if "card" in unfiltered or unfiltered.get("ambiguous"):
            print(f"no card named {args.name!r} in your collection "
                  f"(drop --owned to search every pack)")
        else:
            print(f"no card named {args.name!r}")
        return 1
    print(f"{args.name!r} matches several cards - pick one by code:")
    for c in result["ambiguous"]:
        print(f"  {c['code']:<8} {c['name']:<30} "
              f"{c['type_code']:<10} {c['faction_code']}")
    return 1


def identity(conn, name: str) -> dict:
    """All faces and forms of an identity, plus its signature set.

    "What are Angel's stats" has a different answer in Angel form and
    Archangel form, so every face is returned (spec §8).
    """
    row = conn.execute(
        "SELECT identity_key, name FROM identities "
        "WHERE lower(name) = lower(?)", (name,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT i.identity_key, i.name FROM identities i "
            "JOIN identity_faces f ON f.identity_key = i.identity_key "
            "JOIN cards c ON c.code = f.code "
            "WHERE lower(c.name) = lower(?) OR lower(c.code) = lower(?) "
            "LIMIT 1", (name, name)).fetchone()
    if row is None:
        return {"identity": None, "identity_key": None,
                "faces": [], "signature": [], "side_decks": []}

    key = row["identity_key"]
    faces = [_row(conn, r["code"]) for r in conn.execute(
        "SELECT code FROM identity_faces WHERE identity_key = ? "
        "ORDER BY code", (key,))]
    signature = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(SUMMARY)} FROM cards "
        f"WHERE set_code = ? AND type_code NOT IN ('hero', 'alter_ego') "
        f"AND code = canonical_code ORDER BY code", (key,))]
    from .threatremoval import side_decks
    sides = side_decks(conn, faces[0]["code"]) if faces else []
    return {"identity": row["name"], "identity_key": key,
            "faces": faces, "signature": signature, "side_decks": sides}


def handle_identity(args) -> int:
    conn = _open()
    result = identity(conn, args.name)
    if args.json:
        emit(result, as_json=True)
        return 0 if result["identity"] else 1
    if not result["identity"]:
        print(f"no identity named {args.name!r}")
        return 1
    print(f"{result['identity']}  [{result['identity_key']}]")
    for f in result["faces"]:
        _print_card(f)
    print(f"\nSignature set ({len(result['signature'])} cards):")
    for c in result["signature"]:
        print(f"  {c['code']:<8} {c['name']:<32} {c['type_code']}")
    for sd in result["side_decks"]:
        n = sum(c["quantity"] or 1 for c in sd["cards"])
        print(f"\n{sd['name']} - outside the deck, set up by the hero's "
              f"rules ({n} card{'s' if n != 1 else ''}):")
        for c in sd["cards"]:
            qty = f"{c['quantity']}x " if (c["quantity"] or 1) > 1 else ""
            print(f"  {c['code']:<8} {qty}{c['name']:<32} {c['type_code']}")
    return 0


def encounter(conn, name: str) -> dict:
    """A villain's stages and an encounter set's contents.

    Villain hit points scale with the number of players at the table
    rather than living in separate rows, so the printed value is the base
    and there is deliberately no --difficulty flag.
    """
    # 18 set names are shared - Venom is a hero set and a villain set -
    # and an unordered match opened the hero's cards for `encounter venom`.
    # An exact code wins, then the opposition, then modulars, heroes last;
    # the rest are named so a wrong pick is visible.
    named = conn.execute(
        "SELECT code, name FROM sets WHERE lower(code) = lower(?) "
        "   OR lower(name) = lower(?) "
        "ORDER BY lower(code) = lower(?) DESC, "
        "  CASE card_set_type_code WHEN 'villain' THEN 0 WHEN 'leader' THEN 0 "
        "    WHEN 'main_scheme' THEN 1 WHEN 'hero' THEN 3 ELSE 2 END, code",
        (name, name, name)).fetchall()
    row = named[0] if named else None
    also = [r["code"] for r in named[1:]]
    if row is None:
        row = conn.execute(
            "SELECT s.code, s.name FROM sets s JOIN cards c "
            "  ON c.set_code = s.code "
            "WHERE lower(c.name) = lower(?) AND c.faction_code = 'encounter' "
            "ORDER BY c.code LIMIT 1", (name,)).fetchone()
    if row is None:
        return {"set_code": None, "set_name": None,
                "villain": [], "main_scheme": [], "contents": [],
                "also": []}

    contents = [dict(r) for r in conn.execute(
        f"SELECT {', '.join('cards.' + c for c in SUMMARY)}, "
        f"       cards.quantity, cards.health, cards.health_per_hero, "
        f"       cards.attack, cards.scheme, cards.stage, cards.defense, "
        f"       cards.thwart, cards.base_threat, cards.base_threat_fixed, "
        f"       cards.escalation_threat, cards.escalation_threat_fixed, "
        f"       cards.target_threat, cards.target_threat_fixed "
        f"FROM cards WHERE set_code = ? AND code = canonical_code "
        f"ORDER BY code", (row["code"],))]
    # A leader IS the opposition the players fight: the `leader`
    # cards carry stages, hit points per hero, ATK and SCH exactly as a
    # villain does. Filtering to `villain` alone printed a leader set's
    # contents with no stat line at all, for the one card in it that the
    # table is playing against.
    villain = [c for c in contents
               if c["type_code"] in ("villain", "leader")]
    # Only the side that carries numbers: a main scheme's A side is setup
    # text, and listing it would read as a stage with no threshold.
    schemes = [c for c in contents if c["type_code"] == "main_scheme"
               and scheme_line(c)]
    return {"set_code": row["code"], "set_name": row["name"],
            "villain": villain, "main_scheme": schemes,
            "contents": contents, "also": also}


def handle_encounter(args) -> int:
    conn = _open()
    result = encounter(conn, args.name)
    if args.json:
        emit(result, as_json=True)
        return 0 if result["set_code"] else 1
    if not result["set_code"]:
        print(f"no encounter set matching {args.name!r}")
        return 1
    print(f"{result['set_name']}  [{result['set_code']}]")
    if result["also"]:
        print(f"  (also named this: {', '.join(result['also'])} - "
              f"pass the code to see one)")
    if result["villain"]:
        kind = ("Leader stages" if all(v["type_code"] == "leader"
                                      for v in result["villain"])
                else "Villain stages")
        print(f"\n{kind}:")
        for v in result["villain"]:
            hp = f"HP {v['health']}"
            if v.get("health_per_hero"):
                hp += " per hero"
            stage = f"stage {v['stage']}" if v.get("stage") else ""
            print(f"  {v['name']:<24} {stage:<10} {hp:<16} "
                  f"ATK {v['attack']}  SCH {v['scheme']}")
    if result["main_scheme"]:
        print("\nMain scheme stages:")
        for s in result["main_scheme"]:
            stage = f"stage {s['stage']}" if s.get("stage") else ""
            print(f"  {s['name']:<24} {stage:<10} "
                  f"{scheme_line(s).removeprefix('threat: ')}")
    print(f"\nSet contents ({len(result['contents'])} cards):")
    for c in result["contents"]:
        print(f"  {c['quantity']}x {c['name']:<32} {c['type_code']}")
    return 0
