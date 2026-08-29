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

import re
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
        # `signature_set` is passed in, not read from config. Taking it
        # from the override entry meant `None`, so the cap applied to the
        # hero's OWN cards - which rejected every published Adam Warlock
        # deck for holding 2 Cosmic Ward, a card printed at limit 2.
        if lower is not None and row["set_code"] != override.get(
                "_signature_set"):
            cap = min(cap, lower)
    return cap


# Mechanisms that keep a card out of the DECKBUILDING count. The Rules
# Reference settles the first two outright - `Permanent` (p.32) and
# `Linked (Card Title)` (p.27) - and both use the same words: the keyword
# exempts a card from the deck-size limits at either end. Run
# `mc-jarvis rules show Permanent` for the wording, which comes from the
# reader's own rulebook. `hero_special` sets are separate decks entirely,
# and identity faces and back faces were never cards in the deck.
#
# `config` is deliberately absent. Rogue's Touched and Valkyrie's
# Death-Glow carry no permanent keyword, so that rule does not reach them:
# they are ordinary deck cards that an ability sets aside during setup,
# and they DO count toward the 40.
NOT_DECKBUILDING = ("permanent", "linked", "hero_special", "identity",
                    "back_face")


def deckbuilding_cards(conn, deck) -> dict[str, int]:
    """What counts toward the deck-size minimum.

    Distinct from `included`, and the corpus proves the distinction is
    real. Every hero's smallest published deck is exactly
    `40 + <permanent signature cards>`: Rogue and Valkyrie floor at 40,
    Wolverine, X-23 and Vision at 41, Psylocke at 42 with two permanents,
    Spectrum at 43 with three.

    `included` answers "what will I draw"; this answers "what did I
    build". A permanent is in neither. Touched is in this one only.
    """
    out = excluded(conn, deck)
    return {code: n for code, n in deck.slots.items()
            if out.get(code) not in NOT_DECKBUILDING}


def check_size(conn, deck, config) -> Finding:
    rules = config["deck_rules"]
    size = sum(deckbuilding_cards(conn, deck).values())
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


# `Linked (Specialized Training)`, `Linked (Captain America upgrade)`,
# `Linked (Absorbing Man minion)` - a card title, optionally followed by
# the type word that disambiguates it.
LINKED_RE = re.compile(r"Linked\s*\(([^)]+)\)", re.I)
_LINK_TYPES = ("upgrade", "minion", "ally", "event", "support", "resource",
               "side scheme", "attachment", "treachery")


def _enabler_name(clause: str) -> str:
    """The card title inside a `Linked (...)` clause.

    The trailing type word is a disambiguator, not part of the name:
    `Captain America upgrade` is the Captain America UPGRADE, told apart
    from the leader and the ally of the same name.
    """
    name = clause.strip()
    for kind in _LINK_TYPES:
        if name.lower().endswith(" " + kind):
            return name[: -(len(kind) + 1)].strip()
    return name


def linked_groups(conn) -> dict[str, list[dict]]:
    """Enabler card name -> the linked cards it brings into play.

    Derived from the linked cards' own text rather than configured: each
    one names its enabler, which is the only place the relationship is
    written down.
    """
    groups: dict[str, list[dict]] = {}
    for row in conn.execute(
            "SELECT code, name, type_code, text FROM cards "
            "WHERE text LIKE '%Linked (%'"):
        match = LINKED_RE.search(row["text"] or "")
        if not match:
            continue
        enabler = _enabler_name(match.group(1))
        groups.setdefault(enabler, []).append(
            {"code": row["code"], "name": row["name"],
             "type_code": row["type_code"], "enabler": enabler})
    return groups


def arriving(conn, deck) -> list[dict]:
    """Linked cards this deck will acquire during play.

    RR p.27 keeps linked cards out of the deck, and the corpus agrees: 0
    of 1,501 published decks list one. But 215 list an ENABLER, so one
    deck in seven gains cards this way, and saying only "not in the deck"
    describes a game the player does not have - a Specialized Training
    deck really does end up with a Specialist upgrade in play, and in the
    deck once it is discarded.

    Only enablers the PLAYER's deck holds count. The Trickster Magic
    allies are linked to encounter minions, so whether they arrive is a
    property of the scenario rather than of this deck.
    """
    cards = included(conn, deck)
    if not cards:
        return []
    groups = linked_groups(conn)
    marks = ",".join("?" * len(cards))
    held = {r["name"] for r in conn.execute(
        f"SELECT name FROM cards WHERE code IN ({marks})", list(cards))}
    out = []
    for enabler, members in sorted(groups.items()):
        if enabler in held:
            out.extend(sorted(members, key=lambda m: m["name"]))
    return out


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
    out = []
    if found:
        out.append(Finding(
            rule="campaign", ok=True, kind="note", cards=found,
            detail=f"{len(found)} campaign card(s) - {', '.join(found)}. "
                   f"Whether you have earned these depends on campaign "
                   f"progress, which this tool does not model and marvelcdb "
                   f"does not record."))

    later = arriving(conn, deck)
    if later:
        names = [c["name"] for c in later]
        out.append(Finding(
            rule="linked", ok=True, kind="note", cards=names,
            detail=f"{len(names)} linked card(s) join this deck during "
                   f"play - {', '.join(names)}. They are set aside at "
                   f"setup, arrive when their enabler resolves, and cycle "
                   f"through the deck from then on, so they are in no "
                   f"count below."))
    return out


from pathlib import Path

import yaml

from . import deckrules, identity as identity_mod
from . import paths

CONFIG_PATH = paths.bundled("legality.yaml")


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def _signature_set(conn, hero_code: str) -> str | None:
    """The set holding the hero's own cards.

    Signature is decided by SET MEMBERSHIP, not faction. Spider-Woman is
    the reason: of 685 player cards across 74 hero sets, 681 are
    `faction: hero` and the other four are hers - one per aspect, by
    design. Judging her by faction fails her deck for holding the two
    off-aspect signature cards she cannot remove, and skews her
    equal-aspect count with the two she can't remove either.
    """
    row = conn.execute("SELECT set_code FROM cards WHERE code = ?",
                       (hero_code,)).fetchone()
    return row["set_code"] if row else None


def _aspect_cards(conn, deck) -> list[dict]:
    """Included cards that are subject to aspect rules.

    Signature cards are excluded by set membership before any faction is
    read, which is what keeps Spider-Woman's four aspect-printed signature
    cards out of both the purity check and the balance count.
    """
    cards = included(conn, deck)
    if not cards:
        return []
    signature = _signature_set(conn, deck.hero_code)
    marks = ",".join("?" * len(cards))
    return [dict(r, quantity=cards[r["code"]]) for r in conn.execute(
        f"SELECT code, name, faction_code, set_code, type_code, traits, "
        f"resource_physical, resource_mental, resource_energy, "
        f"resource_wild FROM cards WHERE code IN ({marks})", list(cards))
        if r["set_code"] != signature]


def _override(conn, deck, config) -> dict | None:
    """The identity's deckbuilding override, with its own set attached.

    `_signature_set` is added here rather than stored in config: the set
    is a fact about the card data, and duplicating it in YAML is one more
    thing to fall out of date.
    """
    key = identity_mod.key_for_code(conn, deck.hero_code)
    entry = deckrules.for_identity(conn, config, key) if key else None
    if entry is None:
        return None
    return dict(entry, _signature_set=_signature_set(conn, deck.hero_code))


def _allowed_off_aspect(conn, row, allowance) -> bool:
    """Whether one card falls under an identity's off-aspect allowance.

    Read from `cards.traits` - the PRINTED trait line - and not from
    `card_traits`, which records the `[[X-MEN]]` markup a card's text
    REFERENCES. The two are different questions, and the second one
    answers "which cards care about X-Men", not "which cards are X-Men".
    """
    if row["type_code"] != allowance.get("type_code"):
        return False
    traits = (row["traits"] or "").lower()
    wanted = allowance.get("trait")
    if wanted and wanted.lower() not in traits:
        return False
    any_of = allowance.get("traits_any")
    if any_of and not any(t.lower() in traits for t in any_of):
        return False
    resource = allowance.get("resource")
    if resource and not (row[f"resource_{resource}"] or 0):
        return False
    return True


def _allowance_breach(conn, rows, off, allowance) -> str | None:
    """Whether the allowance's own cap is exceeded.

    `limit_unit: distinct_titles` is Maria Hill's: three S.H.I.E.L.D.
    supports at their full copy count, so the cap is on titles rather
    than on cards - three titles times `deck_limit` each, not three cards.
    """
    limit = allowance.get("limit")
    if limit is None:
        return None
    covered = [r for r in rows if r["code"] in off]
    if allowance.get("limit_unit") == "distinct_titles":
        used = len({r["name"] for r in covered})
        unit = "distinct title(s)"
    else:
        used = sum(r["quantity"] for r in covered)
        unit = "card(s)"
    if used <= limit:
        return None
    return (f"the off-aspect allowance permits {limit} {unit} and this deck "
            f"uses {used}")


ASPECT_FACTIONS = ("justice", "leadership", "aggression", "protection",
                   "pool")


def _declaration_looks_stale(rows, aspects, rules) -> str | None:
    """Whether the deck's own cards contradict its declared aspect.

    marvelcdb keeps the declaration in `meta`, separately from the cards,
    so a player can rebuild into another aspect and leave it behind - or
    never set it. Judging purity against a stale declaration rejects a
    legal deck AND names the wrong cards, which is worse than saying
    nothing.

    Only fires when the disagreement is overwhelming. The threshold sits
    in a measured empty band: 1,325 of 1,478 decks match their
    declaration completely, 15 match 10% or less, and almost nothing sits
    between. The 50-90% band is mostly legal off-aspect allowances and
    must not be swept up with these.
    """
    cards = [r for r in rows if r["faction_code"] in ASPECT_FACTIONS]
    total = sum(r["quantity"] for r in cards)
    if total < rules.get("declaration_min_cards", 5):
        return None
    match = sum(r["quantity"] for r in cards
                if r["faction_code"] in set(aspects))
    share = match / total
    if share > rules.get("declaration_trusted_above", 0.2):
        return None
    held = sorted({r["faction_code"] for r in cards})
    return (f"the deck declares {', '.join(aspects)} but only "
            f"{share:.0%} of its aspect cards match - it actually holds "
            f"{', '.join(held)}. marvelcdb stores the declared aspect "
            f"separately from the cards, so it is probably out of date; "
            f"purity was not judged against it")


def check_aspects(conn, deck, config) -> Finding:
    """Aspect count, aspect purity, and the equal-split allowance."""
    rules = config["deck_rules"]["aspects"]
    entry = rules.get("rr_entry")
    always = set(rules.get("always_allowed") or ())

    if not deck.aspects:
        # A NOTE, not a failure. marvelcdb records the aspect in `meta`
        # and some decks carry none; that is a gap in what was recorded,
        # not evidence the deck is illegal. Failing here would reject a
        # legal deck for its author's omission.
        return Finding(
            rule="aspects", ok=True, kind="note", rr_entry=entry,
            detail="no aspect is recorded for this deck, so purity was not "
                   "checked - marvelcdb keeps it in `meta` rather than "
                   "deriving it from the cards")

    override = _override(conn, deck, config)
    allowed = (override or {}).get("aspects") or rules["default_max"]
    if len(deck.aspects) > allowed:
        return Finding(
            rule="aspects", ok=False, rr_entry=entry,
            detail=f"declares {len(deck.aspects)} aspects "
                   f"({', '.join(deck.aspects)}) and {deck.hero_name} may "
                   f"choose {allowed}")

    rows_all = _aspect_cards(conn, deck)
    stale = _declaration_looks_stale(rows_all, deck.aspects, rules)
    if stale is not None:
        return Finding(rule="aspects", ok=True, kind="note", rr_entry=entry,
                       detail=stale)

    chosen = set(deck.aspects)
    if (override or {}).get("all_aspects"):
        # Adam Warlock takes an equal number from all four, so every
        # aspect is legal and the declared pair says nothing.
        chosen |= {"justice", "leadership", "aggression", "protection"}
    rows = rows_all
    off_rows = [r for r in rows if r["faction_code"] not in chosen | always]

    # An identity may permit specific off-aspect cards: Cyclops takes
    # [[X-MEN]] allies from any aspect, Cable player side schemes, Wonder
    # Man energy events, Gamora up to six attack/thwart events, Maria Hill
    # three S.H.I.E.L.D. support titles. All seven live in
    # `deckbuilding_overrides`, scanned from the identity cards.
    allowance = (override or {}).get("off_aspect_allowance")
    if allowance:
        permitted = {r["code"] for r in off_rows
                     if _allowed_off_aspect(conn, r, allowance)}
        breach = _allowance_breach(conn, rows, permitted, allowance)
        if breach:
            return Finding(rule="aspects", ok=False, rr_entry=entry,
                           detail=breach)
        off_rows = [r for r in off_rows if r["code"] not in permitted]

    off = sorted({r["name"] for r in off_rows})
    if off:
        return Finding(
            rule="aspects", ok=False, rr_entry=entry, cards=off,
            detail=f"{len(off)} card(s) belong to no chosen aspect: "
                   f"{', '.join(off[:6])}")

    # An identity that may take two aspects does not merely ALLOW them:
    # Spider-Woman's card requires an equal number of cards from each, so
    # an `aspects: 2` check on its own passes a split her card forbids.
    if override and override.get("equal_aspects") and len(deck.aspects) > 1:
        per = {a: 0 for a in deck.aspects}
        for row in rows:
            if row["faction_code"] in per:
                per[row["faction_code"]] += row["quantity"]
        if len(set(per.values())) > 1:
            return Finding(
                rule="aspects", ok=False, rr_entry=entry,
                detail=f"{deck.hero_name} needs an equal number of cards "
                       f"from each chosen aspect; this deck has "
                       f"{', '.join(f'{a} {n}' for a, n in per.items())}")

    return Finding(rule="aspects", ok=True, rr_entry=entry,
                   detail=", ".join(deck.aspects))


def check_unique(conn, deck) -> Finding:
    """No two matching unique cards, over the INCLUDED cards only."""
    codes = list(included(conn, deck)) + [deck.hero_code]
    pairs = identity_mod.matching_pairs(conn, codes)
    return Finding(
        rule="unique", ok=not pairs,
        detail=("; ".join(f"{a}/{b}" for a, b in pairs) if pairs
                else "no unique clashes"),
        cards=[c for pair in pairs for c in pair])


def check(conn, deck, config: dict | None = None) -> list[Finding]:
    """Every rule, in the order §10 requires.

    Exclusion first - `included` is what every later check reads - then
    size, copies, aspects and uniqueness. Notes come last and never
    change the verdict.
    """
    config = config if config is not None else load_config()
    override = _override(conn, deck, config)
    return [check_size(conn, deck, config),
            check_copies(conn, deck, override),
            check_aspects(conn, deck, config),
            check_unique(conn, deck)] + notes(conn, deck)
