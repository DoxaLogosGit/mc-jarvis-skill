"""Deck shape (spec §10).

Reads `deckcheck.included` - the draw pile - and never `deck.slots`. §10
requires it: a permanent upgrade left in the cost curve describes a deck
the player never shuffles, and the exclusion rules exist precisely so
that `check` and `stats` see the same cards.

`deckbuilding_size` is reported alongside because the two genuinely
differ. Touched counts toward the 40 and is never drawn (§10.3), so a
Rogue deck is 40 built and 39 drawn - a difference worth showing rather
than leaving the reader to wonder which number is wrong.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .allycost import ally_rows, totals
from .deckcheck import arriving, deckbuilding_cards, included
from .threatremoval import profile as removal_profile

RESOURCES = ("physical", "mental", "energy", "wild")

_EMPTY = {
    "size": 0, "deckbuilding_size": 0, "cost_curve": {}, "mean_cost": 0.0,
    "over": 0, "no_cost": 0, "resources": {}, "by_type": {}, "by_aspect": {},
    "arrives_later": [], "allies": [], "ally_totals": {},
    "threat_removal": {},
}


def profile(conn, deck) -> dict:
    cards = included(conn, deck)
    built = sum(deckbuilding_cards(conn, deck).values())
    if not cards:
        return dict(_EMPTY, aspects=deck.aspects, deckbuilding_size=built)

    marks = ",".join("?" * len(cards))
    rows = [dict(r) for r in conn.execute(
        f"SELECT code, name, type_code, faction_code, cost, "
        f"resource_physical, resource_mental, resource_energy, "
        f"resource_wild FROM cards WHERE code IN ({marks})", list(cards))]

    curve: Counter = Counter()
    resources: Counter = Counter()
    by_aspect: Counter = Counter()
    by_type: dict[str, dict] = defaultdict(
        lambda: {"copies": 0, "cards": []})
    no_cost = cost_total = costed = 0

    for row in rows:
        copies = cards[row["code"]]
        if row["cost"] is None:
            # A null cost is the ABSENCE of a cost, not a cost of nothing.
            # Resources and some upgrades have none, and folding them in
            # as 0 drags the mean toward a number no card in the deck has.
            no_cost += copies
        else:
            curve[row["cost"]] += copies
            cost_total += row["cost"] * copies
            costed += copies
        for name in RESOURCES:
            resources[name] += (row[f"resource_{name}"] or 0) * copies
        by_aspect[row["faction_code"]] += copies
        entry = by_type[row["type_code"]]
        entry["copies"] += copies
        entry["cards"].append({"code": row["code"], "name": row["name"],
                               "quantity": copies})

    allies = ally_rows(conn, cards)

    return {
        "aspects": deck.aspects,
        # What you will draw.
        "size": sum(cards.values()),
        # What you built. Larger whenever a card is set aside at setup but
        # still counted toward the minimum (§10.3).
        "deckbuilding_size": built,
        "cost_curve": dict(sorted(curve.items())),
        "mean_cost": round(cost_total / costed, 2) if costed else 0.0,
        # Reported with the mean so the denominator is visible: the cards
        # with no cost are not in it.
        "over": costed,
        "no_cost": no_cost,
        "resources": {k: v for k, v in resources.items() if v},
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
        "by_aspect": dict(by_aspect.most_common()),
        # Linked cards are set aside at setup and join the deck when
        # their enabler resolves (RR p.27), so they are in none of the
        # numbers above - but a deck holding Specialized Training really
        # does end up with a Specialist upgrade. Named rather than
        # counted, because when they arrive is a property of the game
        # rather than of the deck.
        "arrives_later": [{"code": c["code"], "name": c["name"],
                           "via": c["enabler"]} for c in arriving(conn, deck)],
        # Allies are the only card type whose output is priced in its own
        # hit points, so THW alone overstates them (§10.6). Both bounds
        # are reported because they compete for the same pool, and the
        # markers say which rows the numbers do not describe (§10.7).
        "allies": allies,
        "ally_totals": totals(allies),
        # Split by what limits each kind: exhaustion caps basic thwarts
        # (and the ally limit caps those again), while resources cap the
        # `(thwart)`-designated abilities, which do not exhaust the hero.
        "threat_removal": removal_profile(conn, deck),
    }


def render(p: dict) -> None:
    """Text output for `deck stats`.

    `--json` carries the whole profile, including a row per ally. The text
    form deliberately does not: dumping the nested structures ran to 415
    lines for a 50-card deck, which is not something anyone reads. Summary
    here, detail in JSON.
    """
    print(f"{p['size']} cards drawn"
          + (f", {p['deckbuilding_size']} built"
             if p["deckbuilding_size"] != p["size"] else "")
          + f"  ({', '.join(p['aspects']) or 'no aspect'})")

    curve = "  ".join(f"{k}:{v}" for k, v in p["cost_curve"].items())
    print(f"  cost {curve}   mean {p['mean_cost']} over {p['over']}"
          + (f", {p['no_cost']} with no cost" if p["no_cost"] else ""))
    print("  resources  "
          + "  ".join(f"{k} {v}" for k, v in p["resources"].items()))
    print("  types      "
          + "  ".join(f"{k} {v['copies']}"
                      for k, v in p["by_type"].items()))

    a = p.get("ally_totals") or {}
    if a.get("allies"):
        print(f"  allies {a['allies']}: lifetime thwart "
              f"{a['thwart_lifetime']}, attack {a['attack_lifetime']} "
              f"(alternatives, not a sum)")
        if a.get("unpriced"):
            print(f"    {a['unpriced']} have no consequential damage cost "
                  f"upstream, so no bound is computed for them")
        if a.get("marked"):
            print(f"    {a['marked']} carry card text the cost fields do "
                  f"not express - read those cards")
        if a.get("icon_burden"):
            print("    encounter icons they add: "
                  + ", ".join(f"{k} {v}"
                              for k, v in a["icon_burden"].items()))

    t = p.get("threat_removal") or {}
    if t:
        b = t["basic_thwart"]
        print(f"  threat removal: basic thwart ceiling {b['ceiling']} "
              f"(hero {b['hero']} + {b['allies_fielded']} of "
              f"{b['allies_in_deck']} allies, limit {b['ally_limit']})")
        if b.get("exempt_allies"):
            print("    outside the limit: "
                  + ", ".join(c["name"] for c in b["exempt_allies"]))
        if b.get("raises_limit"):
            print("    could raise the limit if played: "
                  + ", ".join(
                      f"{c['name']}"
                      + (" (conditional)" if c["conditional"] else "")
                      for c in b["raises_limit"]))
        print(f"    plus {t['designated_thwart']['copies']} (thwart) card(s) "
              f"- these do not exhaust the hero - and "
              f"{t['non_thwart_removal']['copies']} that remove threat "
              f"without thwarting, which Patrol cannot stop")

    if p["arrives_later"]:
        print("  arrives later: "
              + ", ".join(f"{c['name']} (via {c['via']})"
                          for c in p["arrives_later"]))
