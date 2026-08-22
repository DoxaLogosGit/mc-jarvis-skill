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
    """RR p.45. Two unique cards match if EITHER:

      - they share a title and both have no subtitle and no alter-ego
        title; or
      - the subtitle or alter-ego title of one matches the title,
        subtitle, or alter-ego title of the other.

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
