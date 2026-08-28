"""Identity grouping and RR p.45 unique-card matching (spec §8)."""
from __future__ import annotations

import sqlite3

IDENTITY_TYPES = ("hero", "alter_ego")


def _norm(title: str | None) -> str | None:
    return title.strip().lower() if title else None


def build(conn: sqlite3.Connection) -> int:
    """Group identity faces and compute unique-match title sets.

    Identities group on `set_code`, not `back_link`: `back_link` is null
    on extra hero forms, so grouping by it loses Archangel, Ant-Man's
    giant form and Wasp's third face, and splits Ironheart's three
    identity cards into three identities (spec §8).
    """
    conn.execute("DELETE FROM identity_faces")
    conn.execute("DELETE FROM identities")

    rows = conn.execute(
        "SELECT code, name, set_code, type_code FROM cards "
        "WHERE type_code IN (?, ?) AND set_code IS NOT NULL "
        "AND code = canonical_code ORDER BY code", IDENTITY_TYPES).fetchall()

    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["set_code"], []).append(r)

    for key, faces in groups.items():
        primary = next((f for f in faces if f["type_code"] == "hero"),
                       faces[0])
        conn.execute(
            "INSERT INTO identities (identity_key, name) VALUES (?, ?)",
            (key, primary["name"]))
        conn.executemany(
            "INSERT INTO identity_faces (identity_key, code) VALUES (?, ?)",
            [(key, f["code"]) for f in faces])

    _build_card_titles(conn)
    conn.commit()
    return len(groups)


def _build_card_titles(conn: sqlite3.Connection) -> None:
    """Record each unique card's three name roles (RR p.45).

    An identity contributes every hero-face name as a title and every
    alter-ego-face name as an alter-ego title, so all six of Ironheart's
    faces share one set.
    """
    conn.execute("DELETE FROM card_titles")

    face_roles: dict[str, list[tuple[str, str]]] = {}
    for key in [r["identity_key"] for r in conn.execute(
            "SELECT identity_key FROM identities")]:
        rows = conn.execute(
            "SELECT c.code, c.name, c.subname, c.type_code FROM identity_faces f "
            "JOIN cards c ON c.code = f.code WHERE f.identity_key = ?",
            (key,)).fetchall()
        titles = [_norm(r["name"]) for r in rows if r["type_code"] == "hero"]
        alter = [_norm(r["name"]) for r in rows
                 if r["type_code"] == "alter_ego"]
        for r in rows:
            pairs = [("title", t) for t in titles if t]
            pairs += [("alter_ego", a) for a in alter if a]
            if _norm(r["subname"]):
                pairs.append(("subtitle", _norm(r["subname"])))
            face_roles[r["code"]] = pairs

    payload: list[tuple[str, str, str]] = []
    for r in conn.execute(
            "SELECT code, name, subname FROM cards WHERE is_unique = 1"):
        code = r["code"]
        if code in face_roles:
            payload.extend((code, role, title)
                           for role, title in face_roles[code])
            continue
        if _norm(r["name"]):
            payload.append((code, "title", _norm(r["name"])))
        if _norm(r["subname"]):
            payload.append((code, "subtitle", _norm(r["subname"])))

    conn.executemany(
        "INSERT OR IGNORE INTO card_titles (code, role, title) "
        "VALUES (?, ?, ?)", payload)


def key_for_code(conn, code: str) -> str | None:
    """The identity a card face belongs to, or None if it is not a face."""
    row = conn.execute(
        "SELECT identity_key FROM identity_faces WHERE code = ?",
        (code,)).fetchone()
    return row["identity_key"] if row else None


def roles_for(conn, code: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {"title": set(), "subtitle": set(),
                                "alter_ego": set()}
    for r in conn.execute(
            "SELECT role, title FROM card_titles WHERE code = ?", (code,)):
        out[r["role"]].add(r["title"])
    return out


def titles_for(conn, code: str) -> set[str]:
    """Every title a card carries, in any role."""
    roles = roles_for(conn, code)
    return roles["title"] | roles["subtitle"] | roles["alter_ego"]


def matches(conn, code_a: str, code_b: str) -> bool:
    """Whether two unique cards count as the same identity (RR p.45).

    Two branches, and the rulebook states both: one covers bare titles
    with nothing else to compare, the other cross-matches any name a card
    carries against any name the other carries. Run `mc-jarvis rules show
    "Identity"` for the wording; it is not reproduced here.

    The two clauses must stay separate. Flattening every name into one
    set and intersecting - the obvious implementation - reports the two
    Black Panther heroes as matching, because they share a title while
    their alter-egos are T'Challa and Shuri. It also has to catch the
    reverse case, an ally matching through its subtitle (spec §8).
    """
    a, b = roles_for(conn, code_a), roles_for(conn, code_b)
    if not any(a.values()) or not any(b.values()):
        return False          # non-unique cards never match

    a_secondary = a["subtitle"] | a["alter_ego"]
    b_secondary = b["subtitle"] | b["alter_ego"]

    if a["title"] & b["title"] and not a_secondary and not b_secondary:
        return True

    a_all = a["title"] | a_secondary
    b_all = b["title"] | b_secondary
    return bool(a_secondary & b_all) or bool(b_secondary & a_all)


# RR p.45-46 define four distinct scopes for matching, and they do not
# agree with each other. Verified against the Rules Reference 2026-08-22.
VILLAIN_TYPES = ("villain",)


def matching_pairs(conn, codes) -> list[tuple[str, str]]:
    """Every matching pair within a set of cards.

    This is the deckbuilding scope (RR p.45): matching cards cannot be
    doubled up in one deck, and the chosen identity counts as one of the
    cards being compared.
    """
    codes = list(dict.fromkeys(codes))
    # Faces of one identity always share titles with each other. They are
    # one card, so they never conflict - without this, every hero reports
    # a collision with their own alter-ego.
    owner = {r["code"]: r["identity_key"] for r in conn.execute(
        "SELECT code, identity_key FROM identity_faces")}
    out = []
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            if a in owner and owner[a] == owner.get(b):
                continue
            if matches(conn, a, b):
                out.append((a, b))
    return out


def _type_of(conn, code: str) -> str | None:
    row = conn.execute(
        "SELECT type_code FROM cards WHERE code = ?", (code,)).fetchone()
    return row["type_code"] if row else None


def blocks_entering_play(conn, code: str, in_play: list[str]) -> list[str]:
    """Which in-play cards stop `code` from entering play (RR p.46).

    The rule bars a non-villain card from entering play while something
    it matches is already there, and it spans the whole table rather than
    one player: with the Nebula identity in play, Gamora's signature
    Nebula ally cannot enter from any deck.

    Villains are exempt as the card entering play. RR p.45 also permits a
    scenario whose villain matches a chosen identity, so a matching
    villain never blocks and is never blocked.
    """
    if _type_of(conn, code) in VILLAIN_TYPES:
        return []
    return [other for other in in_play
            if _type_of(conn, other) not in VILLAIN_TYPES
            and matches(conn, code, other)]


def identities_conflict(conn, identity_keys) -> list[tuple[str, str]]:
    """Identity pairs that cannot be chosen together (RR p.45).

    The rulebook bars two players from picking identities that match.
    Compared face-to-face, since every face contributes its titles to the
    identity.
    """
    keys = list(dict.fromkeys(identity_keys))
    faces = {}
    for key in keys:
        faces[key] = [r["code"] for r in conn.execute(
            "SELECT code FROM identity_faces WHERE identity_key = ?", (key,))]

    out = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if any(matches(conn, fa, fb)
                   for fa in faces[a] for fb in faces[b]):
                out.append((a, b))
    return out


def villain_matches_identity(conn, villain_code: str,
                             identity_key: str) -> bool:
    """Whether a villain matches a chosen identity.

    Reported, never enforced: RR p.45 explicitly allows a scenario whose
    villains match chosen identities, so Nebula may face the Nebula
    villain. Worth surfacing as a flavour note, not as an error.
    """
    return any(matches(conn, villain_code, face)
               for face in [r["code"] for r in conn.execute(
                   "SELECT code FROM identity_faces WHERE identity_key = ?",
                   (identity_key,))])
