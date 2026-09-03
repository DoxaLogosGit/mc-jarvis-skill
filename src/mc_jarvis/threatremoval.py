"""Threat removal capacity (assessment spec §9.2, item 1).

§9 originally asked for "threat removal available per turn". That number
does not exist: a true rate needs readying, exhaustion, resource cost and
draw, which is a simulation. What exists is two ceilings that are limited
by different things, and conflating them produces a figure that is wrong
in whichever direction the reader assumes.

**Basic thwarts are limited by exhaustion.** RR p.44: "A character must
exhaust to use this power." So each character contributes one basic thwart
per turn unless something readies it -- and the ally side is capped again
by the ally limit of three (RR p.7), which is a limit on allies *in play*,
not allies in the deck. A deck holding twelve allies still fields three.

**Abilities designated `(thwart)` are not.** The same entry: "Unless
specified by the ability's text, a hero does not exhaust" to resolve a
`Hero Action (thwart)`. These are additional instances, gated by resources
and draw rather than by exhaustion, so they must not be added to the basic
thwarts as though they competed for the same limit.

**Threat removal that is not a thwart is a third thing.** It bypasses
Patrol entirely (design §10.12), and it is not a thwart attempt for any
card that cares about one.
"""
from __future__ import annotations

import re

from .allycost import ally_rows
from .deckcheck import included

# RR p.7. A limit on allies in play; the deck may hold any number.
ALLY_LIMIT = 3

_DESIGNATOR = re.compile(r"<i>\(([a-z/]+)\)</i>", re.I)
_REMOVES_THREAT = re.compile(r"remove.{0,40}threat", re.I)


def designations(text: str | None) -> frozenset[str]:
    """The action types a card's abilities are designated as.

    Designators compound -- `(attack/thwart)`, `(attack/defense/thwart)` --
    so membership is tested per token. A substring test on `(thwart)`
    misses six cards and miscounts `Hit and Run` (design §10.12).
    """
    out: set[str] = set()
    for m in _DESIGNATOR.finditer(text or ""):
        out |= {p for p in m.group(1).lower().split("/")
                if p in ("attack", "thwart", "defense")}
    return frozenset(out)


def profile(conn, deck) -> dict:
    """Threat removal in a deck, split by what limits each kind."""
    cards = included(conn, deck)
    hero = conn.execute(
        "SELECT name, thwart FROM cards WHERE code = ?",
        (deck.hero_code,)).fetchone()
    hero_thw = hero["thwart"] if hero else None

    designated: list[dict] = []
    non_thwart: list[dict] = []
    if cards:
        marks = ",".join("?" * len(cards))
        for r in conn.execute(
                f"SELECT code, name, type_code, text FROM cards "
                f"WHERE code IN ({marks})", list(cards)):
            acts = designations(r["text"])
            entry = {"code": r["code"], "name": r["name"],
                     "copies": cards[r["code"]]}
            if "thwart" in acts:
                designated.append(entry)
            elif _REMOVES_THREAT.search(r["text"] or ""):
                non_thwart.append(entry)

    allies = [a for a in ally_rows(conn, cards) if a["thwart"]]
    # Sorted by THW so the ceiling reflects the three best, which is what a
    # player fielding three allies would choose.
    best = sorted(allies, key=lambda a: a["thwart"], reverse=True)[:ALLY_LIMIT]

    return {
        # Limited by exhaustion: one basic thwart each, per turn.
        "basic_thwart": {
            "hero": hero_thw,
            "allies_in_deck": len(allies),
            "allies_fielded": len(best),
            "ally_limit": ALLY_LIMIT,
            # A ceiling, not a rate: it assumes the three best allies are
            # in play, ready, and spending their activation on thwarting
            # rather than attacking or blocking (design §10.6).
            "ceiling": (hero_thw or 0) + sum(a["thwart"] for a in best),
        },
        # Limited by resources and draw, NOT by exhaustion, so these are
        # additional to the above rather than competing with it.
        "designated_thwart": {
            "cards": designated,
            "copies": sum(e["copies"] for e in designated),
        },
        # Removes threat without being a thwart: passes through Patrol.
        "non_thwart_removal": {
            "cards": non_thwart,
            "copies": sum(e["copies"] for e in non_thwart),
        },
    }
