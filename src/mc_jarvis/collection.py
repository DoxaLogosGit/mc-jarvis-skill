"""Pack ownership (spec §10, corrected by §10.1).

One predicate, shared. Every command that filters by ownership uses
`owned_predicate()` rather than writing its own `WHERE`, because the
filter is subtler than it looks and a second copy would get it wrong.
"""
from __future__ import annotations

# Commands where `--owned` changes the answer. `cli._leaf` used to put the
# flag on all 14 leaves and dispatch rejected it globally (§10.1); these
# are the ones that return cards. Offering it elsewhere implies a filter
# that never happens, which is worse than not offering it.
OWNED_COMMANDS = frozenset({
    "card search", "card show", "identity", "encounter", "rules show",
})


class UnknownPack(RuntimeError):
    """A pack code that is not in the index."""


def owned_packs(conn) -> list[str]:
    return [r["pack_code"] for r in conn.execute(
        "SELECT pack_code FROM owned_packs ORDER BY pack_code")]


def available_packs(conn) -> list[tuple[str, str]]:
    return [(r["code"], r["name"]) for r in conn.execute(
        "SELECT code, name FROM packs ORDER BY code")]


def set_packs(conn, packs) -> dict:
    """Replace the collection.

    Validated BEFORE the delete. Clearing first and validating after would
    leave a player owning nothing after a one-character typo, which is the
    worst outcome available here: every later search quietly returns less
    and nothing says why.
    """
    wanted = sorted(dict.fromkeys(packs))
    known = {code for code, _ in available_packs(conn)}
    missing = [p for p in wanted if p not in known]
    if missing:
        raise UnknownPack(
            f"not pack codes in this index: {', '.join(missing)}. Run "
            f"`mc-jarvis collection show --available` for the list; a typo "
            f"here would silently narrow every later search.")
    conn.execute("DELETE FROM owned_packs")
    conn.executemany("INSERT INTO owned_packs (pack_code) VALUES (?)",
                     [(p,) for p in wanted])
    conn.commit()
    return {"owned": len(wanted)}


def owned_predicate() -> str:
    """A `WHERE` fragment selecting cards the player can field.

    Over the CANONICAL GROUP, not the pack. §10 gives this as
    `pack_code IN (owned)`, which is wrong for any reprinted card: 337
    player cards have more than one printing, and owning Agents of
    S.H.I.E.L.D. lets you play Dum Dum Dugan whether or not you own
    Sinister Motives.
    """
    return ("canonical_code IN (SELECT canonical_code FROM cards "
            " WHERE pack_code IN (SELECT pack_code FROM owned_packs))")


def filter_codes(conn, codes) -> list[str]:
    """`codes` narrowed to what the player owns.

    An EMPTY collection filters nothing: the player has not said what they
    own, which is not the same as owning nothing. Returning nothing there
    looks exactly like a broken index.
    """
    codes = list(codes)
    if not codes or not owned_packs(conn):
        return codes
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT code FROM cards WHERE code IN ({marks}) "
        f"AND {owned_predicate()}", codes)
    return [r["code"] for r in rows]


def clear(conn) -> list[str]:
    """Forget the collection. Owning nothing and having said nothing are
    different states - with no collection recorded, every card is offered
    again - and `set` could only ever replace one list with another."""
    had = owned_packs(conn)
    conn.execute("DELETE FROM owned_packs")
    conn.commit()
    return had


def handle(args) -> int:
    from .cards import _open
    from .cli import emit

    conn = _open()
    if args.collection_cmd == "show":
        if args.available:
            packs = available_packs(conn)
            if args.json:
                emit([{"code": c, "name": n} for c, n in packs], as_json=True)
                return 0
            # A dict per pack ran to 189 lines for a list whose whole use
            # is to be scanned for a code to type back.
            width = max((len(c) for c, _ in packs), default=0)
            for code, name in packs:
                print(f"  {code:<{width}}  {name}")
            print(f"\n{len(packs)} pack(s)")
            return 0
        owned = owned_packs(conn)
        if args.json:
            emit({"owned": owned, "count": len(owned)}, as_json=True)
            return 0
        if not owned:
            print("No collection set - every card is offered. "
                  "`mc-jarvis collection set <pack>...` to narrow it.")
            return 0
        print(f"{len(owned)} pack(s): {', '.join(owned)}")
        return 0

    if args.collection_cmd == "clear":
        had = clear(conn)
        if args.json:
            emit({"cleared": had}, as_json=True)
            return 0
        print(f"Collection cleared ({', '.join(had)})." if had
              else "No collection was set.")
        print("Every card is offered again until you set one.")
        return 0

    if not args.packs:
        print("mc-jarvis collection set: name at least one pack code. "
              "`collection show --available` lists them.")
        return 1
    # `set` replaces the whole collection, and a live test replaced a real
    # one with a single pack for a one-off question. What is already
    # recorded has to be said out loud before it is thrown away.
    existing = owned_packs(conn)
    if existing and not getattr(args, "replace", False) \
            and sorted(existing) != sorted(args.packs):
        print(f"mc-jarvis collection set: you already own "
              f"{len(existing)} pack(s): {', '.join(existing)}. This would "
              f"replace that list. Pass --replace to change it, or name "
              f"every pack you own.")
        return 1
    try:
        result = set_packs(conn, args.packs)
    except UnknownPack as exc:
        print(f"mc-jarvis collection: {exc}")
        return 1
    if args.json:
        emit(result, as_json=True)
        return 0
    # "owned: 1" said nothing about what had just been written to disk, or
    # that it now narrows every later search. A player was left unaware a
    # lasting change had been made on their behalf.
    names = dict(available_packs(conn))
    print("Recorded " + ", ".join(names.get(p, p)
                                  for p in owned_packs(conn)) + ".")
    print("`--owned` searches are narrowed to these until you change it: "
          "`collection set ... --replace`, or `collection clear` to forget.")
    return 0
