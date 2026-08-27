"""Scenario threat profile (spec §1-§8, Part 1).

Facts and derived statistics only. No card recommendations: turning
"6 Tough minions, 2 answers" into "cut a Tackle" is the model's job,
taught by SKILL.md. A `recommend_tech()` here would invert the project's
architecture and make the feature untestable - you can assert numbers, you
cannot assert opinions.

A scenario is NOT a villain (spec §14.10). Seven scenarios have no villain
set of their own and six villain sets are components of a scenario rather
than scenarios themselves, so this module keys everything on the set that
holds the main scheme, and treats a component named on its own as a
question to answer rather than a deck to assemble.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .encounterdeck import load_config

DIFFICULTIES = ("standard", "expert", "standard_ii", "expert_ii",
                "standard_iii", "standard_pvp")


class UnknownScenario(RuntimeError):
    """The name given is not a scenario this index can assemble."""


@dataclass
class Scenario:
    # The set holding the main scheme. Named `scenario_set`, not
    # `villain_set`: the old name encoded a relationship the data does not
    # have (§14.10).
    scenario_set: str
    modulars: list[str] = field(default_factory=list)
    difficulty: str = "standard"
    players: int = 1
    heroic: int = 0
    nemesis: list[str] = field(default_factory=list)
    # Sets that may be shuffled in DURING play (§14.9). Empty for the
    # great majority of scenarios.
    pool: list[str] = field(default_factory=list)
    modular_kind: str = "none"


def _host_scenarios(conn, code: str) -> list[str]:
    """Scenarios a component set belongs to.

    A set of villains with no main scheme is a component: `marauders` is
    the seven villains `morlock_siege` and `on_the_run` draw from, and
    the four Wrecking Crew sets are faced together under one main scheme.
    The link is not in the data as a column, so it is read the only way it
    is written down - the scenario's own Contents block, which names the
    component set (§14.1).
    """
    hosts = []
    for row in conn.execute(
            "SELECT DISTINCT c.set_code, c.text FROM cards c "
            "WHERE c.type_code = 'main_scheme' AND c.text LIKE '%Contents%'"):
        name = conn.execute("SELECT name FROM sets WHERE code = ?",
                            (code,)).fetchone()
        if name and name["name"] and name["name"] in (row["text"] or ""):
            hosts.append(row["set_code"])
    return sorted(set(hosts))


def resolve(conn, villain: str, *, modular=None, players: int = 1,
            difficulty: str = "standard", heroic: int = 0,
            nemesis=()) -> Scenario:
    """A scenario, named by its own code or by a villain that appears in it."""
    row = conn.execute(
        "SELECT code FROM sets WHERE code = ? OR lower(name) = lower(?)",
        (villain, villain)).fetchone()
    if row is None:
        raise UnknownScenario(
            f"{villain!r} is not in the card data. mc-jarvis indexes "
            f"marvelcdb, which does not carry every scenario that is "
            f"playable - a partial deck would be worse than no answer.")
    code = row["code"]

    has_scheme = conn.execute(
        "SELECT 1 FROM cards WHERE set_code = ? AND type_code = 'main_scheme'",
        (code,)).fetchone()
    if not has_scheme:
        kind_row = conn.execute(
            "SELECT card_set_type_code FROM sets WHERE code = ?",
            (code,)).fetchone()
        set_kind = kind_row["card_set_type_code"] if kind_row else None
        if set_kind in ("modular", "nemesis"):
            raise UnknownScenario(
                f"{code!r} is a {set_kind} set, not a scenario. Assess the "
                f"scenario you are facing and pass this set with "
                f"--{'modular' if set_kind == 'modular' else 'nemesis'}.")
        hosts = _host_scenarios(conn, code)
        raise UnknownScenario(
            f"{code!r} has no main scheme, so it is a component of a "
            f"scenario rather than a scenario itself"
            + (f" - it is faced in: {', '.join(hosts)}. Assess one of those."
               if hosts else
               ". No scenario's Contents block names it, so which scenario "
               "faces it cannot be read from the card data."))

    mapped = conn.execute(
        "SELECT kind, modular_set FROM scenario_modulars WHERE scenario_set = ?",
        (code,)).fetchall()
    if not mapped and modular is None:
        raise UnknownScenario(
            f"{code!r} has no modular mapping. Pass --modular to say which "
            f"sets are on your table.")

    kind = mapped[0]["kind"] if mapped else "open"
    if modular is not None:
        # An explicit list REPLACES the default (§6).
        modulars = list(modular)
    else:
        modulars = [m["modular_set"] for m in mapped if m["modular_set"]]

    return Scenario(scenario_set=code, modulars=modulars,
                    difficulty=difficulty, players=players, heroic=heroic,
                    nemesis=list(nemesis), modular_kind=kind)


def _sets(scenario: Scenario) -> list[str]:
    return ([scenario.scenario_set] + scenario.modulars
            + [scenario.difficulty] + scenario.nemesis)


def back_faces(conn, config: dict | None = None) -> set[str]:
    """Codes that are the back of a card already counted by its front.

    `back_link` is the rule. It was cross-checked against the code-suffix
    pattern (`X+b` beside an `X+a`): 66 rows agree, and the 4 the suffix
    pattern adds were read one at a time. Three are separate physical
    cards sharing a code stem; one has an upstream-wrong `back_link` on
    its front and is listed in config.
    """
    config = config if config is not None else load_config()
    linked = {r["back_link"] for r in conn.execute(
        "SELECT DISTINCT back_link FROM cards WHERE back_link IS NOT NULL")}
    return linked | set(config.get("back_faces") or {})


def back_face_gate(conn, config: dict | None = None) -> list[str]:
    """Any `X+b` deck row that is neither linked nor a decided case.

    Without this, a new double-sided card silently adds a phantom copy to
    whatever scenario ships it.
    """
    config = config if config is not None else load_config()
    decided = (set(config.get("back_faces") or {})
               | set(config.get("not_back_faces") or {}))
    linked = back_faces(conn, config)
    problems = []
    for row in conn.execute(
            "SELECT c.code, c.name, c.set_code FROM cards c "
            "JOIN encounter_role e ON e.code = c.code "
            "WHERE e.role = 'deck' AND c.code LIKE '%b' AND EXISTS ("
            "  SELECT 1 FROM cards f "
            "  WHERE f.code = substr(c.code, 1, length(c.code) - 1) || 'a')"):
        if row["code"] in linked or row["code"] in decided:
            continue
        problems.append(
            f"{row['code']} ({row['name']}, {row['set_code']}): looks like a "
            f"back face but nothing links it. Read the card: add it to "
            f"`back_faces` if it is one, `not_back_faces` if the set really "
            f"ships two.")
    return problems


def deck_cards(conn, scenario: Scenario, *, added: int = 0) -> list[dict]:
    """Every card in the encounter deck, one row per printing.

    `quantity` is carried, never collapsed: the Rhino set ships
    `Stampede x3 boost 1` and `Charge x2 boost 2`, and a mean over rows is
    not the expected boost of a card the player draws (§4.5).

    Three exclusions, each measured rather than assumed: cards the role
    classifier keeps out of the deck, reprints of a card already counted
    (10 deck rows), and back faces (70 deck rows - `aoa_mission` gives 10
    rows for 5 missions).

    Cards that start in play but cycle back are INCLUDED and carry their
    `role`, so the opening deck can be reported apart from what the deck
    holds over a game.
    """
    codes = _sets(scenario) + scenario.pool[:added]
    marks = ",".join("?" * len(codes))
    rows = [dict(r) for r in conn.execute(
        f"SELECT c.*, e.role, e.returns_to_deck FROM cards c "
        f"JOIN encounter_role e ON e.code = c.code "
        f"WHERE c.set_code IN ({marks}) AND c.is_reprint = 0 "
        f"AND (e.role = 'deck' OR e.returns_to_deck = 1) "
        f"ORDER BY c.set_code, c.code", codes)]
    backs = back_faces(conn)
    return [r for r in rows if r["code"] not in backs]


def _by_type(cards: list[dict]) -> dict[str, dict]:
    from collections import defaultdict

    out: dict[str, dict] = defaultdict(
        lambda: {"copies": 0, "rows": 0, "cards": []})
    for c in cards:
        entry = out[c["type_code"]]
        entry["copies"] += c["quantity"]
        entry["rows"] += 1
        entry["cards"].append({"code": c["code"], "name": c["name"],
                               "quantity": c["quantity"]})
    return {k: dict(v) for k, v in sorted(out.items())}


def profile(conn, scenario: Scenario, *, added: int = 0) -> dict:
    """What a scenario's encounter deck contains, with the cards behind it.

    Two sizes, not one. `deck_size` counts everything the deck will hold
    over a game; `opening_deck_size` excludes the cards that begin in play
    and only cycle in later. Reporting a single number would be wrong for
    one of the two questions a player actually asks, and there is no way
    to tell from the number which one it answered.
    """
    from collections import Counter

    cards = deck_cards(conn, scenario, added=added)
    size = sum(c["quantity"] for c in cards)
    cycling = [c for c in cards if c["role"] != "deck"]

    boost_total = sum((c.get("boost") or 0) * c["quantity"] for c in cards)
    histogram: Counter = Counter()
    by_set: Counter = Counter()
    for c in cards:
        histogram[c.get("boost") or 0] += c["quantity"]
        by_set[c["set_code"]] += c["quantity"]

    return {
        "scenario": scenario.scenario_set,
        "modulars": scenario.modulars,
        "modular_kind": scenario.modular_kind,
        "difficulty": scenario.difficulty,
        "players": scenario.players,
        "deck_size": size,
        "opening_deck_size": size - sum(c["quantity"] for c in cycling),
        # Named, not just subtracted: three cards corpus-wide, and a
        # reader who sees the two sizes differ deserves to know which.
        "cycles_in": [{"code": c["code"], "name": c["name"],
                       "quantity": c["quantity"]} for c in cycling],
        "boost": {
            # Quantity-weighted over the WHOLE deck: a card with no boost
            # value has zero boost icons and stays in the denominator.
            "mean": (boost_total / size) if size else 0.0,
            "total": boost_total,
            "over": size,
            "histogram": dict(sorted(histogram.items())),
            # Counted, never averaged (§4.4).
            "star_copies": sum(c["quantity"] for c in cards
                               if c.get("boost_star")),
        },
        "by_type": _by_type(cards),
        "by_set": dict(by_set),
        "minions": _minions(conn, cards),
        "treacheries": _treacheries(conn, cards),
        "side_schemes": _side_schemes(cards, scenario.players),
        "scheme_pressure": {
            # Acceleration icons raise the main scheme every round, so
            # they compound in a way a threat total does not.
            "acceleration_icons": sum(
                (c.get("scheme_acceleration") or 0) * c["quantity"]
                for c in cards),
        },
        "keywords": _keyword_copies(conn, cards, printed=True),
    }

# The four scheme icons carried as columns (§4.1). Counted, never summed
# with threat: an acceleration icon is a rate, threat is a quantity.
ICON_FIELDS = ("scheme_acceleration", "scheme_amplify", "scheme_crisis",
               "scheme_hazard")


def _keyword_copies(conn, cards: list[dict], *, printed: bool) -> dict:
    """Keyword counts, quantity-weighted, from `card_keywords`.

    Read from the table rather than re-matched here, so the keyword list
    has one home. `printed` selects the card's own keywords over the ones
    it grants or gains on a condition - a split worth 261 mentions against
    80 printed cards for `surge` alone.
    """
    if not cards:
        return {}
    by_code = {c["code"]: c["quantity"] for c in cards}
    marks = ",".join("?" * len(by_code))
    out: dict[str, int] = {}
    for row in conn.execute(
            f"SELECT code, keyword FROM card_keywords "
            f"WHERE code IN ({marks}) AND printed = ?",
            list(by_code) + [int(printed)]):
        out[row["keyword"]] = out.get(row["keyword"], 0) + by_code[row["code"]]
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _span(cards: list[dict], field_: str) -> dict | None:
    values = [c[field_] for c in cards if c.get(field_) is not None]
    return {"min": min(values), "max": max(values)} if values else None


def _named(cards: list[dict], **extra) -> list[dict]:
    return [{"code": c["code"], "name": c["name"], "quantity": c["quantity"],
             **{k: f(c) for k, f in extra.items()}} for c in cards]


def _threat(card: dict, players: int) -> int:
    """`*_fixed` means the value does not scale with player count (§4.6).

    Applying per-hero scaling to a fixed-threat scheme is the same error as
    printing raw villain HP: a number that is right for one table and
    silently wrong for every other.
    """
    base = card.get("base_threat") or 0
    return base if card.get("base_threat_fixed") else base * players


def _minions(conn, cards: list[dict]) -> dict:
    rows = [c for c in cards if c["type_code"] == "minion"]
    return {
        "rows": len(rows),
        "copies": sum(c["quantity"] for c in rows),
        "health": _span(rows, "health"),
        "attack": _span(rows, "attack"),
        "scheme": _span(rows, "scheme"),
        # A per-hero minion is a different card at 4 players than at 1.
        "scales_per_hero": sum(1 for c in rows if c.get("health_per_hero")),
        "keywords": _keyword_copies(conn, rows, printed=True),
        "granted_keywords": _keyword_copies(conn, rows, printed=False),
        "cards": _named(rows),
    }


def _treacheries(conn, cards: list[dict]) -> dict:
    rows = [c for c in cards if c["type_code"] == "treachery"]
    copies = sum(c["quantity"] for c in rows)
    printed = _keyword_copies(conn, rows, printed=True)
    granted = _keyword_copies(conn, rows, printed=False)
    surge = printed.get("surge", 0)
    return {
        "rows": len(rows),
        "copies": copies,
        # Two fields, never one. A card that says "this card gains surge"
        # surges only when its condition holds, and the condition is the
        # whole card. Rhino's suite is 12 conditional copies and 0 printed
        # ones; a single number would report an 86% surge rate for a deck
        # that never surges on its own.
        "surge_copies": surge,
        "conditional_surge_copies": granted.get("surge", 0),
        "surge_rate": (surge / copies) if copies else 0.0,
        "keywords": printed,
        "cards": _named(rows),
    }


def _side_schemes(cards: list[dict], players: int) -> dict:
    rows = [c for c in cards if c["type_code"] == "side_scheme"]
    icons = {f.replace("scheme_", ""):
             sum((c.get(f) or 0) * c["quantity"] for c in rows)
             for f in ICON_FIELDS}
    return {
        "rows": len(rows),
        "copies": sum(c["quantity"] for c in rows),
        "threat_total": sum(_threat(c, players) * c["quantity"] for c in rows),
        "icons": {k: v for k, v in icons.items() if v},
        "cards": _named(rows, threat=lambda c: _threat(c, players)),
    }
