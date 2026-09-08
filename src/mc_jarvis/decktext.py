"""Decks written by hand: a list of cards, or a spreadsheet.

marvelcdb hands out JSON keyed by card code. A person writing a deck out
writes names, and the names do not resolve cleanly: 93 of the 1,641
player cards share a name with another. Most of that collapses once the
population is right -- encounter-side printings and hero signature cards
are not deck members, and a card's two faces are one card -- and an
aspect settles most of what survives. Ten names do not resolve even
then, and those are reported with their codes rather than guessed at,
because a deck built from the wrong Spider-Man is worse than no deck.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

# Types a constructed deck can hold. A hero card is not one of them.
PLAYER_TYPES = ("ally", "event", "upgrade", "support", "resource",
                "player_side_scheme")
# `3x Tackle`, `3 Tackle`, `Tackle x3`, `Tackle` -- the four shapes a
# handwritten list actually uses.
_LEADING = re.compile(r"^\s*(\d+)\s*[xX*]?\s+(.*)$")
_TRAILING = re.compile(r"^(.*?)\s+[xX*]\s*(\d+)\s*$")
_META = re.compile(r"^\s*(hero|aspect|name|deck)\s*[:=]\s*(.+?)\s*$", re.I)
_HEADER = re.compile(r"\b(name|card|title)\b", re.I)
_COUNT_COLUMN = re.compile(r"\b(count|qty|quantity|number|#|copies)\b", re.I)


class DeckTextError(RuntimeError):
    """The file was read but does not describe a deck this can build."""


def _rows_from_csv(text: str) -> tuple[list[tuple[str, int]], dict]:
    """A spreadsheet export: a name column and, usually, a count column."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in reader if any(str(c).strip() for c in r)]
    if not rows:
        return [], {}
    head = [str(c).strip() for c in rows[0]]
    name_at, count_at = 0, None
    if any(_HEADER.search(c) for c in head):
        for i, cell in enumerate(head):
            if _HEADER.search(cell):
                name_at = i
            elif _COUNT_COLUMN.search(cell):
                count_at = i
        rows = rows[1:]
    elif len(head) > 1 and head[-1].isdigit():
        # No header, but the last column is a number: a bare two-column
        # export, which is what a spreadsheet gives you by default.
        count_at = len(head) - 1
    out = []
    for row in rows:
        cells = [str(c).strip() for c in row]
        if name_at >= len(cells) or not cells[name_at]:
            continue
        count = 1
        if count_at is not None and count_at < len(cells):
            digits = re.sub(r"\D", "", cells[count_at])
            count = int(digits) if digits else 1
        out.append((cells[name_at], count))
    return out, {}


def _rows_from_list(text: str) -> tuple[list[tuple[str, int]], dict]:
    """One card per line, with the count wherever the writer put it."""
    entries, meta = [], {}
    for raw in text.splitlines():
        # A comment marker only counts at the start of a line: three
        # supports are named `Safe House #29` and the like, and stripping
        # from the first `#` anywhere turned them into `Safe House`.
        line = "" if raw.lstrip().startswith("#") else raw.rstrip()
        if not line.strip():
            continue
        found = _META.match(line)
        if found:
            meta[found.group(1).lower()] = found.group(2)
            continue
        count, name = 1, line.strip()
        lead = _LEADING.match(line)
        trail = _TRAILING.match(line)
        if lead:
            count, name = int(lead.group(1)), lead.group(2).strip()
        elif trail:
            name, count = trail.group(1).strip(), int(trail.group(2))
        # A leading bullet or dash is decoration, not part of the name.
        name = re.sub(r"^[-*•]\s*", "", name).strip()
        if name:
            entries.append((name, count))
    return entries, meta


def parse(text: str, *, is_csv: bool = False) -> tuple[list, dict]:
    """Split a written deck into (name, count) pairs and its metadata."""
    if is_csv or _looks_like_a_table(text):
        rows, meta = _rows_from_csv(text)
        # A spreadsheet can still carry `Hero: X` in a leading cell, so
        # the line reader is asked for the metadata either way.
        _, line_meta = _rows_from_list(text)
        return rows, {**line_meta, **meta}
    return _rows_from_list(text)


def _looks_like_a_table(text: str) -> bool:
    for raw in text.splitlines():
        line = "" if raw.lstrip().startswith("#") else raw.strip()
        if not line or _META.match(line):
            continue
        cells = re.split(r"[,;\t]", line)
        return len(cells) > 1 and bool(
            _HEADER.search(line) or cells[-1].strip().isdigit())
    return False


def _hero_set(conn, hero: str) -> tuple[str, str]:
    """The hero card and the set its signature cards live in.

    Two heroes are printed as `Black Panther`, T'Challa and Shuri, and
    they carry different signature cards. Taking the first row silently
    resolved a T'Challa deck against Shuri's set, which then reported
    T'Challa's own cards as names matching nothing.
    """
    # A code settles it, and is what the refusal below asks for.
    exact = conn.execute(
        "SELECT code, set_code FROM cards WHERE code = ? "
        "AND type_code IN ('hero', 'alter_ego')", (hero.strip(),)).fetchone()
    if exact:
        return exact["code"], exact["set_code"]
    rows = [dict(r) for r in conn.execute(
        "SELECT DISTINCT c.code, c.set_code, c.name FROM cards c "
        "LEFT JOIN card_titles t ON t.code = c.code "
        "WHERE (lower(c.name) = lower(?) OR t.title = lower(?)) "
        "AND c.type_code = 'hero' AND c.is_reprint = 0 ORDER BY c.code",
        (hero.strip(), hero.strip()))]
    if not rows:
        raise DeckTextError(f"{hero!r} is not a hero in the card data.")
    if len(rows) > 1:
        raise DeckTextError(
            f"{hero!r} names more than one hero, and they do not share "
            f"signature cards: "
            + ", ".join(f"{r['code']} ({r['set_code']})" for r in rows)
            + ". Name the one you mean by its code or its alter-ego.")
    return rows[0]["code"], rows[0]["set_code"]


def candidates(conn, name: str, *, hero_set: str | None,
               aspects: list[str], backs: set[str]) -> list[dict]:
    """Every player card a written name could mean, narrowed in order.

    The order is the point. Dropping encounter printings takes 93 clashes
    to 82, dropping other heroes' signature cards to 38, and dropping the
    back half of a double-sided card to 27. An aspect settles all but ten.
    """
    written = name.strip()
    # A trailing `(justice)` or `(27011)` is how a writer says which one
    # they meant, and the refusal below asks for exactly that.
    hint = ""
    bracket = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", written)
    if bracket:
        written, hint = bracket.group(1).strip(), bracket.group(2).strip()
    for token in (written, hint):
        if not token:
            continue
        exact = conn.execute(
            "SELECT code, canonical_code, name, type_code, faction_code, "
            "set_code, cost FROM cards WHERE code = ?", (token,)).fetchone()
        if exact:
            return [dict(exact)]
    rows = [dict(r) for r in conn.execute(
        f"SELECT code, canonical_code, name, type_code, faction_code, "
        f"set_code, cost FROM cards WHERE lower(name) = lower(?) "
        f"AND is_reprint = 0 AND type_code IN "
        f"({','.join('?' * len(PLAYER_TYPES))})", (written,) + PLAYER_TYPES)]
    # An encounter-side printing is never a deck member.
    rows = [r for r in rows if r["faction_code"] != "encounter"]
    # A signature card belongs to one hero; it is only a candidate when
    # that hero is the one playing.
    rows = [r for r in rows if r["faction_code"] != "hero"
            or (hero_set and r["set_code"] == hero_set)]
    if len(rows) > 1:
        rows = [r for r in rows if r["code"] not in backs] or rows
    if len(rows) > 1 and hint:
        # An inline hint is a disambiguator, so it filters exactly. The
        # deck-level Aspect line cannot: a deck holds basic cards too.
        exactly = [r for r in rows
                   if (r["faction_code"] or "").lower() == hint.lower()
                   or (r["type_code"] or "").lower() == hint.lower()]
        rows = exactly or rows
    if len(rows) > 1 and aspects:
        wanted = {a.strip().lower() for a in aspects}
        # A signature card of the hero being played is never filtered out
        # by aspect: it has no aspect. Dropping it picked the basic ally
        # of the same name instead -- Rogue's own Gambit became the
        # generic one, silently, in six corpus decks.
        narrowed = [r for r in rows
                    if (r["faction_code"] or "").lower() in wanted
                    or r["faction_code"] in ("basic", "hero")]
        rows = narrowed or rows
    seen, unique = set(), []
    for r in rows:
        if r["canonical_code"] in seen:
            continue
        seen.add(r["canonical_code"])
        unique.append(r)
    return unique


def to_payload(conn, text: str, *, is_csv: bool = False,
               source: str = "") -> dict:
    """A written deck as the marvelcdb-shaped payload `normalise` wants."""
    from . import assess

    entries, meta = parse(text, is_csv=is_csv)
    if not entries:
        raise DeckTextError(
            f"{source or 'this file'} holds no card lines. A deck is one "
            f"card per line, optionally with a count (`3x Tackle`), or a "
            f"spreadsheet with a name column and a count column.")
    if not meta.get("hero"):
        raise DeckTextError(
            "no hero named. Add a `Hero: <name>` line - the deck rules "
            "depend on it, and a hero card is not a deck member so it "
            "cannot be read from the list.")
    hero_code, hero_set = _hero_set(conn, meta["hero"])
    aspects = [a for a in re.split(r"[,/|]", meta.get("aspect", "")) if a.strip()]

    backs = assess.back_faces(conn)
    slots: dict[str, int] = {}
    missing: list[tuple[str, int]] = []
    ambiguous: list[tuple[str, int]] = []
    for name, count in entries:
        options = candidates(conn, name, hero_set=hero_set, aspects=aspects,
                             backs=backs)
        if not options:
            # Two different problems. A name matching nothing is probably
            # a typo; a name matching several means the player owns the
            # card and only the tool is unsure which one.
            missing.append((f"{name} [no card of that name - check the "
                            f"spelling, or give the card code]", count))
            continue
        if len(options) > 1:
            ambiguous.append(
                (f"{name} [which one? "
                 + " or ".join(f"{o['code']} ({o['faction_code']} "
                               f"{o['type_code']})" for o in options)
                 + "]", count))
            continue
        code = options[0]["canonical_code"]
        slots[code] = slots.get(code, 0) + int(count)
    # A name that does not resolve is not a reason to refuse the whole
    # list. Somebody pasting a decklist wants the forty-eight cards that
    # did resolve looked at, with the other two named. These keys match
    # no card code, so `normalise` files them under `Deck.unknown` and
    # every check that depends on a complete deck already says so.
    for entry, count in ambiguous + missing:
        slots[entry] = slots.get(entry, 0) + int(count)
    return {"name": meta.get("name") or meta.get("deck") or Path(
        source or "deck").stem,
        "hero_code": hero_code, "slots": slots,
        "meta": {"aspect": aspects[0]} if aspects else {}}
