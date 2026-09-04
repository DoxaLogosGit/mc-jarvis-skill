"""Deck against scenario (assessment spec §9.2).

Four pairings, each a count beside a count in matched units. Every one of
them replaced an earlier pairing that compared the wrong quantities,
because the original was written from a keyword's name rather than from
what the Rules Reference says the keyword does.

Two rules govern every number here.

**The scenario side reads `card_keywords`, never card text.** A text match
cannot tell printing a keyword from granting it: `Jennix` says each
Inheritor minion gains guard, `Unus` gains retaliate on a threat
condition. Counting those as printed made four hand counts too high and
one scenario table wrong by two thirds (design §10.14). The table carries
no side or type, so every read joins `cards` for them - villain retaliate
is a different problem from minion retaliate (design §10.11).

**The deck side cannot use `printed`.** It is a syntax flag, and what
matters here is reliability: `Star-Lord`, `Yondu` and `War Machine` never
print ranged, yet their attacks always have it. So the deck side is
classified here (design §10.11).
"""
from __future__ import annotations

import re

from .threatremoval import designations, profile as removal_profile

# A keyword the card confers on itself with no condition attached is
# reliable in a way a one-attack event is not. The two read almost alike
# -- "Star-Lord's attacks gain ranged" against Marvel Boy's "this attack
# gains ranged" -- and the discriminator is the determiner: a permanent
# grant is possessive (`'s`, `your`, `its`), a one-off is demonstrative.
# `this` and `that` are both five characters, so a fixed-width lookbehind
# separates them.
_SELF_GRANT = re.compile(
    r"(?<!this )(?<!that )(?:attacks?|basic attacks?) (?:gain|gains) (\w+)",
    re.I)
_CONDITIONAL = re.compile(r"^\s*(?:if\b|play only if\b|while\b)", re.I)
_GLOBAL_GRANT = re.compile(r"each (?:\w+ )?(?:minion|enemy|character|ally)"
                           r"[^.]{0,40}gains?", re.I)
_DAMAGES_VILLAIN = re.compile(
    r"damage to (?:the villain|an enemy|each enemy|that enemy)", re.I)
_REMOVES_THREAT = re.compile(r"remove.{0,40}threat", re.I)
# Damage reachable only by attacking is still blocked by Guard.
_NEEDS_ATTACK = re.compile(
    r"(?:after|when) (?:\w+ ){0,3}(?:attacks|makes a basic attack)", re.I)


def _plain(text: str | None) -> str:
    return re.sub(r"<[^>]+>|\[\[|\]\]", "", text or "").strip()


def villain_rows(conn, sets) -> list[dict]:
    """The scenario's villain stages.

    Villains are NOT in the encounter deck, so `assess.deck_cards` never
    returns them. Reading only that list reported zero villain retaliate
    for Zola, who prints Retaliate 1 on all three stages -- the single
    most important retaliate fact in the game (design §10.11).
    """
    if not sets:
        return []
    marks = ",".join("?" * len(sets))
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM cards WHERE set_code IN ({marks}) "
        f"AND type_code = 'villain' AND is_reprint = 0", list(sets))]


def scenario_keyword(conn, cards, keyword: str) -> dict:
    """Printed copies of a keyword, split villain from everything else.

    `cards` are the scenario rows for one trajectory step PLUS the villain
    stages, so this answers for the opening deck and the grown deck
    separately while still seeing the villain.
    """
    if not cards:
        return {"villain": 0, "other": 0, "total": 0, "global_grants": []}
    by_code = {c["code"]: c for c in cards}
    marks = ",".join("?" * len(by_code))
    villain = other = 0
    for row in conn.execute(
            f"SELECT k.code, c.type_code FROM card_keywords k "
            f"JOIN cards c ON c.code = k.code "
            f"WHERE k.keyword = ? AND k.printed = 1 "
            f"AND k.code IN ({marks})", [keyword] + list(by_code)):
        n = by_code[row["code"]].get("quantity") or 1
        if row["type_code"] == "villain":
            villain += n
        else:
            other += n
    # A card that gives every minion the keyword is worth more than its
    # own row, and no count of printed copies sees it (design §10.14).
    grants = [{"code": c["code"], "name": c["name"]} for c in cards
              if _GLOBAL_GRANT.search(_plain(c.get("text")))
              and keyword in (c.get("text") or "").lower()]
    return {"villain": villain, "other": other, "total": villain + other,
            "global_grants": grants}


def deck_keyword(conn, codes, keyword: str) -> dict:
    """Sources of a keyword in a deck, classified by reliability.

    `always` is a self-grant with no condition - the character simply has
    the keyword. `conditional` needs a trait or board state. `per_use`
    grants it for one attack. `mentions_only` grants nothing at all and is
    reported so a reader can see why a card was not counted.
    """
    if not codes:
        return {"always": [], "conditional": [], "per_use": [],
                "mentions_only": []}
    marks = ",".join("?" * len(codes))
    out = {"always": [], "conditional": [], "per_use": [], "mentions_only": []}
    for r in conn.execute(
            f"SELECT code, name, text FROM cards WHERE code IN ({marks}) "
            f"AND LOWER(text) LIKE ?", list(codes) + [f"%{keyword}%"]):
        plain = _plain(r["text"])
        entry = {"code": r["code"], "name": r["name"],
                 "copies": codes[r["code"]]}
        grants = [m for m in _SELF_GRANT.findall(plain)
                  if m.lower() == keyword]
        if not grants:
            # A grant inside an ability that resolves one attack. Keywords
            # come in lists -- Marvel Boy's "this attack gains piercing and
            # ranged" -- so the keyword need not follow `gains` directly.
            granted = re.search(
                rf"gains? (?:[\w']+(?:,| and| or)? ){{0,4}}?{keyword}\b",
                plain, re.I)
            out["per_use" if granted else "mentions_only"].append(entry)
        elif _CONDITIONAL.match(plain):
            out["conditional"].append(entry)
        else:
            out["always"].append(entry)
    return out


# Acceleration tokens are a liability for almost every deck and an engine
# for one. Deadpool's `Cable`, `Montage` and `It Ain't Over...` all scale
# with them, and `Exhausting Personality` places one deliberately as a
# cost. Reporting acceleration as a plain problem for that deck states the
# opposite of the truth (design §10.13).
_SCALES_WITH_TOKENS = re.compile(r"for each acceleration token", re.I)
_PLACES_TOKEN = re.compile(r"(?:place|add)s? \d* ?acceleration token", re.I)
_REMOVES_TOKEN = re.compile(r"remove (?:an?|\d+) acceleration token", re.I)
# Icons and tokens are formally distinct and an effect naming one does
# nothing to the other, so these are counted apart.
_REMOVES_ICON = re.compile(r"lose(?:s)? each \[?acceleration", re.I)


def acceleration_interest(conn, codes) -> dict:
    """Deck cards that care about acceleration, by what they do to it."""
    out = {"scales_with": [], "places": [], "removes_token": [],
           "removes_icon": []}
    if not codes:
        return out
    marks = ",".join("?" * len(codes))
    for r in conn.execute(
            f"SELECT code, name, text FROM cards WHERE code IN ({marks}) "
            f"AND LOWER(text) LIKE '%acceleration%'", list(codes)):
        entry = {"code": r["code"], "name": r["name"],
                 "copies": codes[r["code"]]}
        text = r["text"] or ""
        if _SCALES_WITH_TOKENS.search(text):
            out["scales_with"].append(entry)
        if _PLACES_TOKEN.search(text):
            out["places"].append(entry)
        if _REMOVES_TOKEN.search(text):
            out["removes_token"].append(entry)
        if _REMOVES_ICON.search(text):
            out["removes_icon"].append(entry)
    return out


def bypasses(conn, codes) -> dict:
    """Cards that answer Guard and Patrol by not being the forbidden action.

    Guard forbids attacking the villain and Patrol forbids thwarting the
    main scheme; neither forbids damage or threat removal (design §10.12).
    Designators compound, so membership is tested per token.
    """
    if not codes:
        return {"guard": [], "patrol": [], "attack_contingent": []}
    marks = ",".join("?" * len(codes))
    guard, patrol, contingent = [], [], []
    for r in conn.execute(
            f"SELECT code, name, text FROM cards WHERE code IN ({marks})",
            list(codes)):
        text, acts = r["text"] or "", designations(r["text"])
        entry = {"code": r["code"], "name": r["name"],
                 "copies": codes[r["code"]]}
        if _DAMAGES_VILLAIN.search(text) and "attack" not in acts:
            (contingent if _NEEDS_ATTACK.search(text) else guard).append(entry)
        if _REMOVES_THREAT.search(text) and "thwart" not in acts:
            patrol.append(entry)
    return {"guard": guard, "patrol": patrol,
            "attack_contingent": contingent}


def pairings(conn, cards, deck, *, sets=()) -> dict:
    """The four cross-references for one trajectory step.

    `cards` is that step's encounter rows, so calling this per step
    answers for the opening deck and for the fully-grown deck separately.
    A keyword that arrives with a modular set is invisible in the opening
    deck and decisive by the end, and one figure for the whole session
    would hide that.
    """
    from .deckcheck import included

    # A villain stage is not an encounter-deck row; without this the
    # villain half of every keyword split reads zero.
    cards = list(cards) + villain_rows(conn, sets)
    codes = included(conn, deck)
    removal = removal_profile(conn, deck)
    bypass = bypasses(conn, codes)

    def copies(entries):
        return sum(e["copies"] for e in entries)

    tough = scenario_keyword(conn, cards, "toughness")
    guard = scenario_keyword(conn, cards, "guard")
    patrol = scenario_keyword(conn, cards, "patrol")
    retaliate = scenario_keyword(conn, cards, "retaliate")
    piercing = deck_keyword(conn, codes, "piercing")
    ranged = deck_keyword(conn, codes, "ranged")

    return {
        # 1. Not a rate against a rate. 97 of 116 acceleration icons sit on
        # side schemes, so thwarting one reduces the acceleration that
        # generates the threat you must thwart (design §10.13).
        "acceleration": {
            "scenario_icons": sum((c.get("scheme_acceleration") or 0)
                                  * (c.get("quantity") or 1) for c in cards),
            "icons_on_side_schemes": sum(
                (c.get("scheme_acceleration") or 0) * (c.get("quantity") or 1)
                for c in cards if c["type_code"] == "side_scheme"),
            "deck_basic_thwart_ceiling": removal["basic_thwart"]["ceiling"],
            "deck_designated_thwarts": removal["designated_thwart"]["copies"],
            "deck_non_thwart_removal": removal["non_thwart_removal"]["copies"],
            "deck_interest": acceleration_interest(conn, codes),
            "note": "a ceiling, not a rate; and a loop, not a ratio",
        },
        # 2. The mechanism is piercing, which mostly never says "tough".
        # Searching the word found one answer where there are eleven
        # (design §10.10).
        "tough": {
            "scenario_sources": tough,
            "deck_piercing": {k: copies(v) for k, v in piercing.items()},
            "deck_piercing_cards": piercing,
            # One tough card annuls a whole damage instance whatever its
            # size, so Tough is regressive in hit size (design §10.9).
            "note": "tough annuls an instance, not a point",
        },
        # 3. Ranged does exactly one thing: it ignores retaliate. Villain
        # retaliate taxes every attack all game; a minion's taxes only the
        # attacks you choose to make into it (design §10.11).
        "retaliate": {
            "scenario_sources": retaliate,
            "deck_ranged": {k: copies(v) for k, v in ranged.items()},
            "deck_ranged_cards": ranged,
            "note": "a one-shot kill pays no retaliate",
        },
        # 4. Both keywords forbid an ACTION, so non-attack damage and
        # non-thwart removal pass through untouched (design §10.12).
        "guard_and_patrol": {
            "guard": guard,
            "patrol": patrol,
            "deck_non_attack_damage": copies(bypass["guard"]),
            "deck_non_thwart_removal": copies(bypass["patrol"]),
            "excluded_needs_an_attack": copies(bypass["attack_contingent"]),
            "ally_attack_answers_the_minion": removal["basic_thwart"][
                "allies_fielded"],
            # Guard only bites while a guard minion is ENGAGED with you.
            "note": "potential guard, never active guard",
        },
    }
