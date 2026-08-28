"""Deck legality (spec §10, corrected by §10.1, extended by §10.2).

`legality.yaml` is the highest-risk component in this project: an error in
it is invisible and propagates into every downstream feature. Two things
hold it down - the regression corpus of published decks, and the rule that
every value there carries the Rules Reference entry it came from, so the
wording is read from the user's own rulebook rather than restated here.

ORDER MATTERS, and §10 states the trap outright: classify and remove
out-of-deck cards BEFORE applying unique matching. Sp//dr's set carries
`SP//dr Suit` as both a hero face and a permanent support, so reversing
the order makes her fail her own legality check.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PLAYER_TYPES = ("ally", "event", "upgrade", "support", "resource")


@dataclass
class Finding:
    rule: str
    ok: bool
    detail: str
    cards: list[str] = field(default_factory=list)
    rr_entry: str | None = None
    # `rule` findings decide the verdict; `note` findings never do. A note
    # is something the tool can SEE but cannot JUDGE - campaign cards are
    # the case (§10.2), where whether the player earned them lives in the
    # campaign book rather than in any data this project holds.
    kind: str = "rule"


def verdict(findings) -> bool:
    """Legal or not. Notes are excluded by construction, not by care."""
    return all(f.ok for f in findings if f.kind == "rule")


def excluded(conn, deck) -> dict[str, str]:
    """Slots that are not part of the constructed deck, and why.

    Read from `out_of_deck`, which `outofdeck.classify` fills from all
    four mechanisms: the `permanent` keyword (Wolverine's Claws), the
    `hero_special` set type (Iceman's Frostbite), identity faces, and the
    config entries for cards the data does not mark at all - Rogue's
    Touched, Valkyrie's Death-Glow.
    """
    if not deck.slots:
        return {}
    marks = ",".join("?" * len(deck.slots))
    out = {r["code"]: r["mechanism"] for r in conn.execute(
        f"SELECT code, mechanism FROM out_of_deck WHERE code IN ({marks})",
        list(deck.slots))}
    for code in _back_faces(conn) & set(deck.slots):
        out.setdefault(code, "back_face")
    return out


def _back_faces(conn) -> set[str]:
    """Codes that are the back of a card already counted by its front.

    The same rule `assess.back_faces` applies to encounter cards, reused
    rather than reimplemented: `back_link` separated the 24 ambiguous
    player-card stems cleanly into 19 faces and 5 resource variants, with
    nothing left over (§10.1).
    """
    from . import assess

    return assess.back_faces(conn)


def included(conn, deck) -> dict[str, int]:
    """The constructed deck: every slot the exclusions leave behind.

    Reprints cannot appear here - `deckfetch` canonicalises every slot
    before a deck reaches this module.
    """
    out = excluded(conn, deck)
    return {code: n for code, n in deck.slots.items() if code not in out}


def _limit(row, override: dict | None = None) -> int:
    """A card's per-deck cap.

    The null fallback is NOT reimplemented here: `index.resolve_deck_limit`
    already encodes it, and the index build already asserts that
    `deck_limit` never exceeds `quantity`, both per printing and across
    printings. A second copy of that rule would drift from the first.

    An identity override can lower the cap: Warlock's
    `max_copies_non_signature` binds below `deck_limit` for every card
    outside his own set.
    """
    from . import index as index_mod

    cap = index_mod.resolve_deck_limit(dict(row)) or (row["quantity"] or 1)
    if override:
        lower = override.get("max_copies_non_signature")
        if lower is not None and row["set_code"] != override.get("set_code"):
            cap = min(cap, lower)
    return cap


def check_size(conn, deck, config) -> Finding:
    rules = config["deck_rules"]
    size = sum(included(conn, deck).values())
    minimum = rules["minimum_size"]
    detail = f"{size} cards, minimum {minimum}"
    if deck.unknown:
        # Never report a short deck without saying that some of it did not
        # resolve; the player did not build the shortfall.
        missing = ", ".join(sorted(deck.unknown))
        detail += (f" - but {sum(deck.unknown.values())} card(s) are not in "
                   f"this index at all ({missing}), so the count is a floor")
    return Finding(rule="deck_size", ok=size >= minimum, detail=detail,
                   rr_entry=rules.get("rr_entry"))


def check_copies(conn, deck, override: dict | None = None) -> Finding:
    cards = included(conn, deck)
    if not cards:
        return Finding(rule="deck_limit", ok=True, detail="no cards")
    marks = ",".join("?" * len(cards))
    over = []
    names = []
    for row in conn.execute(
            f"SELECT code, name, deck_limit, quantity, set_code FROM cards "
            f"WHERE code IN ({marks})", list(cards)):
        cap = _limit(row, override)
        if cards[row["code"]] > cap:
            over.append(f"{row['name']} x{cards[row['code']]} (limit {cap})")
            names.append(row["name"])
    return Finding(
        rule="deck_limit", ok=not over,
        detail="; ".join(over) if over else "every card within its limit",
        cards=names)


def notes(conn, deck) -> list[Finding]:
    """What the tool can see but cannot judge (§10.2).

    Campaign rewards are marked `faction_code = 'campaign'` - 146 cards
    across 15 sets, of which 68 genuinely enter a player deck. Their copy
    limits are ordinary and are checked normally; what is unknowable is
    whether this player EARNED them, which lives in the campaign book and
    is not recorded by marvelcdb either.
    """
    cards = included(conn, deck)
    if not cards:
        return []
    marks = ",".join("?" * len(cards))
    found = [r["name"] for r in conn.execute(
        f"SELECT name FROM cards WHERE code IN ({marks}) "
        f"AND faction_code = 'campaign' ORDER BY name", list(cards))]
    if not found:
        return []
    return [Finding(
        rule="campaign", ok=True, kind="note", cards=found,
        detail=f"{len(found)} campaign card(s) - {', '.join(found)}. Whether "
               f"you have earned these depends on campaign progress, which "
               f"this tool does not model and marvelcdb does not record.")]
