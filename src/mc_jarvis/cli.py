"""argparse tree and dispatch. Logic lives in the modules, not here."""
from __future__ import annotations

import argparse
import json as _json
import sys
from typing import Any


def _difficulties():
    """Imported lazily: `assess` pulls in the index layer."""
    from .assess import DIFFICULTIES
    return list(DIFFICULTIES)


def _players(value: str) -> int:
    """A player count the game actually supports.

    Learn to Play describes a game for one to four players, and every
    per-player value scales off this number. Unvalidated, `--players -3`
    reported a scenario with -17 threat and `--players 999` one with
    6997, both stated as flatly as a real figure.
    """
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number")
    if not 1 <= n <= 4:
        raise argparse.ArgumentTypeError(
            f"{n} is not a supported player count - the game is played by "
            f"one to four players, and every per-player value scales off "
            f"this number")
    return n


def _positive(value: str) -> int:
    """A result limit of at least one.

    SQLite reads a negative LIMIT as no limit, so `--limit -5` returned
    the whole table while the footer claimed the results were complete.
    """
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number")
    if n < 1:
        raise argparse.ArgumentTypeError(f"{n} is not a usable limit")
    return n


def _leaf(sub, name: str, help_: str, *, owned: bool = False,
          **kw) -> argparse.ArgumentParser:
    """A leaf command. `--json` everywhere; `--owned` only where it acts.

    `--owned` used to be added unconditionally and rejected at dispatch,
    which offered a filter on `doctor` and `timing` that could never
    happen (§10.1). It is now opt-in, and `collection.OWNED_COMMANDS`
    records which commands take it.
    """
    p = sub.add_parser(name, help=help_, **kw)
    p.add_argument("--json", action="store_true", help="emit JSON")
    if owned:
        p.add_argument("--owned", action="store_true",
                       help="restrict to packs in your collection")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mc-jarvis")
    sub = parser.add_subparsers(dest="command")

    _leaf(sub, "doctor", "check prerequisites and environment")
    _leaf(sub, "status", "index age, counts, staleness")

    init_p = _leaf(sub, "init", "one-time bootstrap")
    src = init_p.add_mutually_exclusive_group()
    src.add_argument("--from-html", metavar="FILE",
                     help="saved FFG product page HTML")
    src.add_argument("--browser", action="store_true",
                     help="fetch the FFG page with Playwright")

    _leaf(sub, "update", "refresh sources and rebuild the index")

    skill_p = _leaf(sub, "install-skill", "place the skill for every harness")
    skill_p.add_argument("--link", action="store_true",
                         help="symlink instead of copy (developer use)")
    skill_p.add_argument("--global", dest="global_", action="store_true",
                         help="install to user-global paths")

    # `card` takes an explicit verb: a bare positional would make
    # `card show Vision` parse `show` as the query (spec §5.1).
    card = sub.add_parser("card", help="card lookup")
    card_sub = card.add_subparsers(dest="card_cmd")
    search = _leaf(card_sub, "search", "search cards", owned=True)
    search.add_argument("query", nargs="?", default=None)
    search.add_argument("--aspect")
    search.add_argument("--type")
    search.add_argument("--cost")
    search.add_argument("--trait")
    search.add_argument("--text")
    search.add_argument("--limit", type=_positive, default=20)
    show = _leaf(card_sub, "show", "one card in full", owned=True)
    show.add_argument("name")
    show.add_argument("--explain", action="store_true",
                      help="expand keywords with rules text and page cites")

    ident = _leaf(sub, "identity", "all faces and forms of an identity",
                  owned=True,
                  aliases=["hero"])
    ident.add_argument("name")

    enc = _leaf(sub, "encounter", "villain stats and set contents",
                owned=True)
    enc.add_argument("name")

    rules = sub.add_parser("rules", help="rules lookup")
    rules_sub = rules.add_subparsers(dest="rules_cmd")
    rshow = _leaf(rules_sub, "show", "a Rules Reference entry", owned=True)
    rshow.add_argument("term")
    rsearch = _leaf(rules_sub, "search", "full-text search the rules")
    rsearch.add_argument("text")

    rul = _leaf(sub, "rulings",
                "designer rulings the rulebook does not yet cover")
    rul.add_argument("text", nargs="?", default=None,
                     help="search the rulings instead of listing them")

    deck_p = _leaf(sub, "deck", "import, validate and describe a deck")
    deck_sub = deck_p.add_subparsers(dest="deck_cmd", required=True)
    for verb, help_ in (("fetch", "normalise a deck"),
                        ("check", "legality, rule by rule"),
                        ("stats", "curves, mixes and densities")):
        leaf = _leaf(deck_sub, verb, help_)
        leaf.add_argument(
            "deck", help="a marvelcdb id, a marvelcdb URL, or a JSON file")

    col = _leaf(sub, "collection", "packs you own")
    col.add_argument("collection_cmd", choices=["set", "show"])
    col.add_argument("packs", nargs="*", help="pack codes, for `set`")
    col.add_argument("--available", action="store_true",
                     help="list every pack code this index knows")

    asr = _leaf(sub, "assess", "what a scenario throws at you")
    asr.add_argument("villain", help="a scenario, or a villain that names one")
    asr.add_argument("--modular", action="append",
                     help="the modular sets on your table; REPLACES the "
                          "scenario's defaults rather than adding to them")
    asr.add_argument("--players", type=_players, default=1)
    asr.add_argument("--difficulty", default="standard",
                     choices=_difficulties())
    asr.add_argument("--heroic", type=int, default=0,
                     help="recorded, but does not change the numbers yet")
    asr.add_argument("--nemesis", action="append")
    asr.add_argument("--deck",
                     help="a marvelcdb deck id or a local decklist JSON; "
                          "cross-references it against the scenario at "
                          "every step of the deck's growth")

    tim = _leaf(sub, "timing", "trigger ordering and the game round")
    tim.add_argument("trigger", nargs="?", default=None,
                     help="a timing trigger, e.g. Response, When Defeated")
    tim.add_argument("--round", action="store_true",
                     help="show the game round structure instead")

    return parser


def emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(_json.dumps(payload, indent=2, ensure_ascii=False))
        return
    _render(payload)


def _render(payload: Any, indent: int = 0) -> None:
    pad = "  " * indent
    if isinstance(payload, list):
        for item in payload:
            _render(item, indent)
            if isinstance(item, dict):
                print()
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                print(f"{pad}{key}:")
                _render(value, indent + 1)
            else:
                print(f"{pad}{key}: {value}")
    else:
        print(f"{pad}{payload}")


ALIASES = {"hero": "identity"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse and normalise. argparse records the alias the user typed, not
    the canonical name (verified: `hero X` yields command == "hero"), so
    normalisation lives here rather than in `main` - otherwise anything
    that parses without going through `main` sees the raw alias."""
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None):
        args.command = ALIASES.get(args.command, args.command)
    return args


def _dispatch(name: str, args) -> int:
    if name == "doctor":
        from . import doctor
        return doctor.handle(args)
    if name == "init":
        from . import init
        return init.run(args)
    if name == "update":
        from . import update
        return update.run(args)
    if name == "status":
        from . import update
        return update.status(args)
    if name == "card":
        from . import cards
        if args.card_cmd == "search":
            return cards.handle_search(args)
        if args.card_cmd == "show":
            return cards.handle_show(args)
    if name == "identity":
        from . import cards
        return cards.handle_identity(args)
    if name == "encounter":
        from . import cards
        return cards.handle_encounter(args)
    if name == "install-skill":
        from . import skill_install
        return skill_install.run(args)
    if name == "rulings":
        from . import rulings
        return rulings.handle(args)
    if name == "deck":
        from . import deckfetch
        return deckfetch.handle(args)
    if name == "collection":
        from . import collection
        return collection.handle(args)
    if name == "assess":
        from . import assess
        return assess.handle(args)
    if name == "timing":
        from . import timing
        return timing.handle(args)
    if name == "rules":
        from . import rules
        if args.rules_cmd == "show":
            return rules.handle_show(args)
        if args.rules_cmd == "search":
            return rules.handle_search(args)
    print(f"mc-jarvis: '{name}' is not implemented yet", file=sys.stderr)
    return 3


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.command:
        build_parser().print_help()
        return 2
    # A flag that silently does nothing is the "did you filter?" bug class
    # spec §13 warns about. The collection lands in the next plan.
    return _dispatch(args.command, args)
