"""What an ally costs to use (spec §10.6, §10.7).

An ally's threat removal is not its THW value. It pays for every basic
power out of its own hit points, so the useful figure is how many times
it can act before it is defeated -- and that figure is bounded in five
different ways, only two of which are numbers we hold.

The two we hold are `attack_cost` and `thwart_cost`: the count of
consequential damage icons printed beneath each stat (RR p.13,
`Consequential Damage`). They are printed separately and differ on 56
allies, so neither substitutes for the other.

The other three live in card text and are not derivable, so this module
does not try. It marks the ally instead. `Cannonball` reduces
consequential damage by the number of [[AERIAL]] cards in hand, which is
hand state no index can see; his computed bound of 2 is a floor, not a
ceiling. `Spider-Ham` prints a genuine 0 on both stats and would compute
as unbounded, while a Forced Response deals him damage after every
attack or thwart. The card whose indexed cost is lowest is the one where
the arithmetic misleads most.
"""
from __future__ import annotations

import json
import re
from math import ceil

# Rule deviations: the card says something the cost fields cannot
# express, and the answer is on the card. 34 of 307 player-legal allies
# carry at least one (spec §10.7).
_CONSEQUENTIAL = re.compile(r"consequential", re.I)
_HP_DERIVED = re.compile(
    r"gets? \+\d+ hit point|hit points? for each|additional hit point", re.I)

# `it` is deliberately absent from the pronoun group. It denotes the
# enemy far more often than the ally: matching it made Iron Fist and
# Psylocke look self-damaging when the damage goes to the card they
# attack.
_SELF_DAMAGE = (r"deal \d+ damage to (?:him|her|{n})\b",
                r"(?:him|her|{n}) takes? \d+ damage")

# A cost charged per use of a basic power that is not hit points, so
# `ceil(health / cost)` cannot express it. 11 player-legal allies have
# one. `Blade` is why this marker exists: his Forced Response makes every
# thwart or attack cost a [physical] resource or he is discarded, and his
# text contains none of the words the other markers look for.
_PER_USE_TRIGGER = (r"(?:After|When) (?:{n}) "
                    r"(?:attacks|thwarts|thwarts or attacks|attacks or thwarts)")
_PER_USE_COST = re.compile(
    r"spend a |spend \d|discard (?:him|her)\b|exhaust|remove \d+ [a-z ]*counter",
    re.I)

ICONS = ("scheme_hazard", "scheme_acceleration", "scheme_amplify")

# An absent `*_cost`. Usually an upstream omission that no lookup can
# resolve -- but not always, so this never means "nothing to read".
# `Blade` carries no consequential damage icons because his price is a
# resource per use, and reading his card is the only way to learn that.
UNKNOWN = "cost-unknown"
UNBOUNDED = "cost-zero"       # a printed 0, which is not a missing value


def markers(name: str, text: str | None) -> frozenset[str]:
    """Reasons to read this card rather than trust its numbers."""
    t = text or ""
    if not t:
        return frozenset()
    out = set()
    if _CONSEQUENTIAL.search(t):
        out.add("consequential-modified")
    if _HP_DERIVED.search(t):
        out.add("hit-points-derived")
    # Match on the first word of the name as well as the whole of it:
    # "Bob, Agent of Hydra" is referred to as "Bob" in his own text.
    first = re.escape(name.split(",")[0].split()[0])
    whole = re.escape(name)
    for pat in _SELF_DAMAGE:
        if any(re.search(pat.format(n=n), t, re.I) for n in (whole, first)):
            out.add("self-damage")
            break
    if _PER_USE_COST.search(t) and any(
            re.search(_PER_USE_TRIGGER.format(n=n), t, re.I)
            for n in (whole, first)):
        out.add("per-use-cost")
    elif re.search(rf"discard (?:{whole}|{first})\b", t, re.I):
        # Distinct from a per-use cost: the ally leaves play as part of
        # an ability or a failed entry condition rather than paying for
        # a basic power. `Goliath` discards himself at end of phase,
        # `Angela` if her search finds no minion. Hit points never
        # governed how long either one stays.
        out.add("self-discard")
    return frozenset(out)


def uses(health: int | None, cost: int | None) -> int | float | None:
    """How many times the ally can use a basic power before defeat.

    Returns None when the price is unknown. A null `*_cost` is an
    upstream omission and must not be defaulted to 1 -- 11 player-legal
    allies have one, and guessing would price Cloak and every Deadpool
    ally wrong in a way nothing downstream could detect.

    A printed 0 is a real value, not a gap, and yields no bound at all.
    """
    if health is None or cost is None:
        return None
    if cost == 0:
        return float("inf")
    # The ally resolves its power, THEN takes the damage, so an ally on
    # 5 hit points paying 3 acts twice, not once.
    return ceil(health / cost)


def _bound(health, cost, stat):
    n = uses(health, cost)
    if n is None or stat is None:
        return {"uses": None, "total": None}
    if n == float("inf"):
        return {"uses": "unbounded", "total": "unbounded"}
    return {"uses": n, "total": n * stat}


def ally_rows(conn, codes) -> list[dict]:
    """One row per distinct ally, with both bounds and every marker."""
    if not codes:
        return []
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT code, name, faction_code, set_code, cost, health, "
        f"attack, thwart, attack_cost, thwart_cost, text, raw, "
        f"{', '.join(ICONS)} "
        f"FROM cards WHERE code IN ({marks}) AND type_code = 'ally' "
        f"ORDER BY name, code", list(codes)).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        icons = {k.removeprefix("scheme_"): d[k] for k in ICONS if d[k]}
        flags = set(markers(d["name"], d["text"]))
        if (d["thwart"] is not None and d["thwart_cost"] is None) or \
           (d["attack"] is not None and d["attack_cost"] is None):
            flags.add(UNKNOWN)
        if d["thwart_cost"] == 0 or d["attack_cost"] == 0:
            flags.add(UNBOUNDED)
        out.append({
            "code": d["code"], "name": d["name"],
            # Name is not a key (spec §8): two Cannonballs, two Cosmos and
            # two Ant-Men exist with different stats and different costs.
            "faction": d["faction_code"], "set_code": d["set_code"],
            "cost": d["cost"], "health": d["health"],
            "thwart": d["thwart"], "thwart_cost": d["thwart_cost"],
            "attack": d["attack"], "attack_cost": d["attack_cost"],
            "thwarting": _bound(d["health"], d["thwart_cost"], d["thwart"]),
            "attacking": _bound(d["health"], d["attack_cost"], d["attack"]),
            "icons": icons,
            "markers": sorted(flags),
        })
    return out


def totals(rows: list[dict]) -> dict:
    """Deck aggregates.

    `thwarting` and `attacking` are ALTERNATIVES, never addends. An ally
    spends one pool of hit points across thwarting, attacking and
    blocking, so adding the two totals double-spends every hit point in
    the deck. They are reported side by side so the trade is visible.
    """
    def add(key):
        return sum(r[key]["total"] for r in rows
                   if isinstance(r[key]["total"], int))

    return {
        "allies": len(rows),
        "thwart_ceiling": add("thwarting"),
        "attack_ceiling": add("attacking"),
        "unpriced": sum(1 for r in rows if UNKNOWN in r["markers"]),
        "marked": sum(1 for r in rows
                      if set(r["markers"]) - {UNKNOWN, UNBOUNDED}),
        "icon_burden": {
            k: sum(r["icons"].get(k, 0) for r in rows)
            for k in ("hazard", "acceleration", "amplify")
            if any(r["icons"].get(k) for r in rows)
        },
    }
