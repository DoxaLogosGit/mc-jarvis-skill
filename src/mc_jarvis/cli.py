"""argparse tree and dispatch. Logic lives in the modules, not here."""
from __future__ import annotations

import argparse
import json as _json
import sys
from typing import Any


def _leaf(sub, name: str, help_: str, **kw) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help_, **kw)
    p.add_argument("--json", action="store_true", help="emit JSON")
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
    search = _leaf(card_sub, "search", "search cards")
    search.add_argument("query", nargs="?", default=None)
    search.add_argument("--aspect")
    search.add_argument("--type")
    search.add_argument("--cost")
    search.add_argument("--trait")
    search.add_argument("--text")
    search.add_argument("--limit", type=int, default=20)
    show = _leaf(card_sub, "show", "one card in full")
    show.add_argument("name")
    show.add_argument("--explain", action="store_true",
                      help="expand keywords with rules text and page cites")

    ident = _leaf(sub, "identity", "all faces and forms of an identity",
                  aliases=["hero"])
    ident.add_argument("name")

    enc = _leaf(sub, "encounter", "villain stats and set contents")
    enc.add_argument("name")

    rules = sub.add_parser("rules", help="rules lookup")
    rules_sub = rules.add_subparsers(dest="rules_cmd")
    rshow = _leaf(rules_sub, "show", "a Rules Reference entry")
    rshow.add_argument("term")
    rsearch = _leaf(rules_sub, "search", "full-text search the rules")
    rsearch.add_argument("text")

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
    if name == "card":
        from . import cards
        if args.card_cmd == "search":
            return cards.handle_search(args)
        if args.card_cmd == "show":
            return cards.handle_show(args)
    print(f"mc-jarvis: '{name}' is not implemented yet", file=sys.stderr)
    return 3


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.command:
        build_parser().print_help()
        return 2
    # A flag that silently does nothing is the "did you filter?" bug class
    # spec §13 warns about. The collection lands in the next plan.
    if getattr(args, "owned", False):
        print("mc-jarvis: --owned needs a collection, which is not built "
              "yet in this version", file=sys.stderr)
        return 3
    return _dispatch(args.command, args)
