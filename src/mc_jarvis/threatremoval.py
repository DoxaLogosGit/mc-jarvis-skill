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

**Abilities designated `(thwart)` are not.** The same entry rules that
resolving a `Hero Action (thwart)` leaves the hero ready unless the card
says otherwise. These are additional instances, gated by resources and
draw rather than by exhaustion, so they must not be added to the basic
thwarts as though they competed for the same limit.

**Threat removal that is not a thwart is a third thing.** It bypasses
Patrol entirely (design §10.12), and it is not a thwart attempt for any
card that cares about one.
"""
from __future__ import annotations

import re

from .allycost import ally_rows
from .deckcheck import included

# RR p.7. Three things about this number, all of which a bare constant
# gets wrong:
#   - It limits allies IN PLAY. The deck may hold any number, and 62% of
#     1,501 published decks hold more.
#   - Cards raise it. `The Triskelion` (leadership) unconditionally;
#     `Avengers Tower`, `Utopia`, `Flight Squadron` and `Knowhere` on a
#     trait condition. All five must be in play to do anything, so they
#     are named as potential rather than applied to the ceiling.
#   - Allies are exempted from it. `Stinger`, the four `New Recruits`
#     (Surge, Anole, Bling!, Indra) and the four `trickster_magic` linked
#     allies do not consume a slot, so they field in addition to the base.
ALLY_LIMIT = 3

_RAISES_LIMIT = re.compile(r"increase your ally limit", re.I)
_EXEMPT = re.compile(r"not count against (?:your |the )?ally limit", re.I)
# Every raise but The Triskelion, and the New Recruits exemptions, are
# gated on a trait the deck may not have.
_CONDITIONAL = re.compile(r"^\s*(?:if|play only if)\b", re.I)

_DESIGNATOR = re.compile(r"<i>\(([a-z/]+)\)</i>", re.I)
_REMOVES_THREAT = re.compile(r"remove.{0,40}threat", re.I)
# A trigger that fires once a scheme's final threat is gone names the
# removal as its condition and removes nothing itself. Seven player cards matched on that phrase alone,
# two of them in Daredevil's Sense deck.
_CONDITION = re.compile(r"remov\w*\s+(?:the last|all)\s+threat", re.I)


# Removal whose amount grows with the board: one upgrade per scheme, one
# ally per trait. A flat count reads these as their minimum.
_SCALES = re.compile(r"\bfor each\b|\bequal to\b|\bwhere X\b", re.I)
# Tested per clause: across a whole card, 12 of 54 matches scaled a cost,
# damage, or threat taken off the card itself rather than the removal.
_CLAUSE = re.compile(r"\.\s|→")


def removal_scales(text: str | None) -> bool:
    plain = re.sub(r"<[^>]+>", "", text or "")
    return any(_SCALES.search(c) and removes_threat(c)
               for c in _CLAUSE.split(plain))


_TEMPORARY = re.compile(r"\bfor (?:this|that)\b|\buntil the end\b|"
                        r"\bthis (?:round|phase)\b|→", re.I)
_STAT_SUBSTITUTE = re.compile(
    r"use your (ATK|THW|DEF|REC) in place of your "
    r"((?:ATK|THW|DEF|REC)(?:,? (?:and )?(?:ATK|THW|DEF|REC))*)", re.I)


def stat_modifiers(conn, cards: dict[str, int], hero_code: str,
                   stat: str) -> list[dict]:
    """Cards in the deck that lastingly raise the identity's `stat`.

    The ceiling reads the printed stat, which is the floor: a THW 1 hero
    with two THW upgrades thwarts for 3. Named, never summed - each must be
    in play, and most are limited per player. A bonus lasting one thwart
    or one phase is an event's effect, not the hero's stat."""
    names = {r["name"].lower() for r in conn.execute(
        "SELECT name FROM cards WHERE code IN (SELECT code FROM "
        "identity_faces WHERE identity_key = (SELECT identity_key FROM "
        "identity_faces WHERE code = ?))", (hero_code,))}
    subject = "|".join(["your hero", "your identity", "you"]
                       + sorted(re.escape(n) for n in names))
    # The subject may open a later clause, after "and" or a comma - a card
    # granting hit points first and DEF second was missed when only a
    # sentence start counted.
    pattern = re.compile(
        rf"(?:^|\band |, )(?:{subject}) gets? "
        rf"(?:\+\d \w+,? (?:and )?)*\+(\d) {stat}\b", re.I)
    out = []
    if not cards:
        return out
    marks = ",".join("?" * len(cards))
    for r in conn.execute(f"SELECT code, name, text FROM cards "
                          f"WHERE code IN ({marks}) ORDER BY name",
                          list(cards)):
        plain = re.sub(r"<[^>]+>|\[\[|\]\]", "", r["text"] or "")
        for sentence in re.split(r"(?<=\.)\s+|\n", plain):
            m = pattern.search(sentence.strip())
            if m and not _TEMPORARY.search(sentence):
                out.append({"code": r["code"], "name": r["name"],
                            "copies": cards[r["code"]],
                            "plus": int(m.group(1)),
                            "conditional": bool(re.match(
                                r"\s*(?:while|if)\b", sentence, re.I))})
                break
    return out


def stat_substitutes(conn, cards: dict[str, int], stat: str) -> list[dict]:
    """Cards that make the identity use another stat in place of `stat`.
    The Best Offense... makes Daredevil thwart with DEF, so his printed
    THW 1 is not the number he thwarts for."""
    out = []
    if not cards:
        return out
    marks = ",".join("?" * len(cards))
    for r in conn.execute(f"SELECT code, name, text FROM cards "
                          f"WHERE code IN ({marks}) ORDER BY name",
                          list(cards)):
        for used, replaced in _STAT_SUBSTITUTE.findall(r["text"] or ""):
            if stat.upper() in replaced.upper():
                out.append({"code": r["code"], "name": r["name"],
                            "copies": cards[r["code"]], "uses": used.upper()})
    return out


def removes_threat(text: str | None) -> bool:
    return bool(_REMOVES_THREAT.search(_CONDITION.sub("", text or "")))


# An ability starts at its bold label. `Hero Action` needs hero form,
# `Alter-Ego Action` alter-ego form, and a bare `Action`, `Response` or
# `Interrupt` works in either (RR p.4, Ability). Daredevil removes threat from
# alter-ego form, which few heroes can, and a THW 1 stat line hid it.
_LABEL = re.compile(r"<b>\W*([^<]{1,40}?)\W*</b>")


def side_decks(conn, hero_code: str) -> list[dict]:
    """The hero's `hero_special` sets: kept outside the deck, never
    drawn from it, so in none of the deck's numbers."""
    return [{"set_code": r["code"], "name": r["name"],
             "cards": [dict(c) for c in conn.execute(
                 "SELECT code, name, type_code, quantity FROM cards "
                 "WHERE set_code = ? AND code = canonical_code "
                 "ORDER BY code", (r["code"],))]}
            for r in conn.execute(
                "SELECT s.code, s.name FROM sets s JOIN cards h "
                "  ON h.set_code = s.parent_code "
                "WHERE h.code = ? AND s.card_set_type_code = 'hero_special' "
                "ORDER BY s.code", (hero_code,))]


def removal_form(text: str | None) -> str | None:
    """Which form can use a card's threat removal: `hero`, `alter_ego`,
    `either`, or None when the card removes none."""
    text = text or ""
    labels = list(_LABEL.finditer(text))
    forms: set[str] = set()
    # Text before the first label is constant, and works in either form.
    bounds = [0] + [m.start() for m in labels] + [len(text)]
    for i in range(len(bounds) - 1):
        chunk = text[bounds[i]:bounds[i + 1]]
        if not ("thwart" in designations(chunk)
                or removes_threat(chunk)):
            continue
        label = labels[i - 1].group(1).lower() if i else ""
        forms.add("hero" if label.startswith("hero")
                  else "alter_ego" if label.startswith("alter-ego")
                  else "either")
    if not forms:
        return None
    if "either" in forms or {"hero", "alter_ego"} <= forms:
        return "either"
    return forms.pop()


def _by_form(entries: list[dict]) -> dict:
    out = {"hero": 0, "alter_ego": 0, "either": 0}
    for e in entries:
        if e.get("form"):
            out[e["form"]] += e["copies"]
    return out


def _removers(conn, cards: dict[str, int]) -> tuple[list[dict], list[dict]]:
    designated: list[dict] = []
    non_thwart: list[dict] = []
    if not cards:
        return designated, non_thwart
    marks = ",".join("?" * len(cards))
    for r in conn.execute(
            f"SELECT code, name, type_code, text FROM cards "
            f"WHERE code IN ({marks})", list(cards)):
        entry = {"code": r["code"], "name": r["name"],
                 "copies": cards[r["code"]],
                 "form": removal_form(r["text"]) or "either",
                 "scales": removal_scales(r["text"])}
        if "thwart" in designations(r["text"]):
            designated.append(entry)
        elif removes_threat(r["text"]):
            non_thwart.append(entry)
    return designated, non_thwart


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


def _strip(text: str | None) -> str:
    """Card text without its markup, so a leading `If`/`Play only if` is
    visible to a start-anchored match."""
    return re.sub(r"<[^>]+>|\[\[|\]\]", "", text or "").strip()


def profile(conn, deck) -> dict:
    """Threat removal in a deck, split by what limits each kind."""
    cards = included(conn, deck)
    hero = conn.execute(
        "SELECT name, thwart FROM cards WHERE code = ?",
        (deck.hero_code,)).fetchone()
    hero_thw = hero["thwart"] if hero else None

    designated, non_thwart = _removers(conn, cards)

    rows = {r["code"]: r for r in conn.execute(
        f"SELECT code, name, text FROM cards WHERE code IN "
        f"({','.join('?' * len(cards))})", list(cards))} if cards else {}

    raisers = [{"code": c, "name": r["name"],
                "conditional": bool(_CONDITIONAL.match(_strip(r["text"])))}
               for c, r in rows.items() if _RAISES_LIMIT.search(r["text"] or "")]

    allies = [a for a in ally_rows(conn, cards) if a["thwart"]]
    exempt, counted = [], []
    for a in allies:
        text = rows[a["code"]]["text"] if a["code"] in rows else ""
        (exempt if _EXEMPT.search(text or "") else counted).append(a)
    # Sorted by THW so the ceiling reflects the best allies a player would
    # field. Exempt allies consume no slot, so they are added on top.
    best = sorted(counted, key=lambda a: a["thwart"],
                  reverse=True)[:ALLY_LIMIT] + exempt

    substitutes = stat_substitutes(conn, cards, "THW")
    for s in substitutes:
        stat = conn.execute(
            f"SELECT {s['uses'].lower() if s['uses'] != 'DEF' else 'defense'}"
            f" AS v FROM cards WHERE code = ?", (deck.hero_code,)).fetchone()
        s["printed"] = stat["v"] if stat else None
        s["raised_by"] = stat_modifiers(conn, cards, deck.hero_code,
                                        s["uses"])

    return {
        # Limited by exhaustion: one basic thwart each, per turn.
        "basic_thwart": {
            "hero": hero_thw,
            # The ceiling reads the printed THW; these change it in play.
            "hero_thw_raised_by": stat_modifiers(conn, cards,
                                                 deck.hero_code, "THW"),
            "hero_thw_replaced_by": substitutes,
            "allies_in_deck": len(allies),
            "allies_fielded": len(best),
            "ally_limit": ALLY_LIMIT,
            # Field in addition to the limit rather than within it.
            "exempt_allies": [{"code": a["code"], "name": a["name"]}
                              for a in exempt],
            # Named, never applied: each must be in play, and all but
            # The Triskelion also need a trait the deck may not have.
            "raises_limit": raisers,
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
        # Which form each removal card needs. The hero's own THW needs
        # hero form; allies thwart whichever form the hero is in.
        "by_form": _by_form(designated + non_thwart),
        # Outside the deck: never drawn, so not in any number above.
        "side_decks": [
            dict(sd, removal=_by_form(sum(_removers(
                conn, {c["code"]: c["quantity"] or 1
                       for c in sd["cards"]}), [])))
            for sd in side_decks(conn, deck.hero_code)],
    }
