"""Deck import (spec §10, as corrected by §10.1).

Normalisation only. Whether a deck is LEGAL is `deckcheck`'s question, and
keeping the two apart is what lets the regression corpus fetch thousands
of decks before a validator exists to run over them.

Every shape here was measured against the live API on 2026-08-27, across
124 published decks. Three of them differ from what §10 records, and each
difference is noted where it bites.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API = "https://marvelcdb.com/api/public"
USER_AGENT = "mc-jarvis (+https://marvelcdb.com)"
# `.../decklist/view/64331/nova-justice`, or the bare id.
DECK_URL_RE = re.compile(r"marvelcdb\.com/decklist/view/(\d+)", re.I)
BARE_ID_RE = re.compile(r"^\d+$")


class DeckError(RuntimeError):
    """The deck cannot be read, or names a hero this index does not have."""


@dataclass
class Deck:
    name: str
    hero_code: str
    hero_name: str
    aspects: list[str] = field(default_factory=list)
    # `meta.format`, absent on 118 of 124 decks. Absent means current.
    deck_format: str = "current"
    # Canonical codes only: a deck names whichever printing its builder
    # owned, and 337 player cards have more than one (§10.1).
    slots: dict[str, int] = field(default_factory=dict)
    # Slots naming a card this index does not carry. Reported, never
    # dropped - a silently shorter deck fails a size check for a reason
    # the player cannot see.
    unknown: dict[str, int] = field(default_factory=dict)
    ignore_limit: dict[str, int] = field(default_factory=dict)
    id: str | None = None
    source: str = ""


def parse_meta(raw) -> dict:
    """`meta` as a dict, whatever the endpoint gave.

    A JSON string on every deck the `by_date` endpoint returns, and an
    already-decoded object elsewhere (§10). Junk yields `{}` rather than
    an exception: the corpus is thousands of user-authored decks, and one
    malformed field must not end the run.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def deck_id(ref: str) -> str | None:
    """The marvelcdb id in `ref`, or None if it is a path."""
    match = DECK_URL_RE.search(ref)
    if match:
        return match.group(1)
    return ref if BARE_ID_RE.match(ref.strip()) else None


def _get(url: str):
    """Fetch and decode, turning every transport failure into a DeckError.

    marvelcdb answers an unknown deck id with a NON-JSON body rather than
    a 404, so `json.loads` raises where an `OSError` handler would never
    see it. Decoding here keeps that from reaching the user as a
    traceback.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except OSError as exc:
        raise DeckError(f"cannot reach marvelcdb: {exc}") from exc
    try:
        return json.loads(body)
    except ValueError:
        raise DeckError(
            "marvelcdb did not return a deck. It answers an unknown id with "
            "a non-JSON page rather than an error, so this usually means the "
            "deck does not exist or is not public.") from None


def fetch_by_date(day: str) -> list[dict]:
    """Every published deck for one day.

    The payload carries the same keys as the single-deck endpoint, so the
    regression corpus costs one request per day rather than one per deck.
    """
    payload = _get(f"{API}/decklists/by_date/{day}")
    return payload if isinstance(payload, list) else []


def normalise(conn, payload: dict, *, source: str) -> Deck:
    """A marvelcdb payload as a `Deck`, with every slot canonicalised."""
    hero_code = payload.get("hero_code") or ""
    hero = conn.execute(
        "SELECT name FROM cards WHERE code = ?", (hero_code,)).fetchone()
    if hero is None:
        raise DeckError(
            f"hero {hero_code!r} is not in the card data. mc-jarvis indexes "
            f"marvelsdb, which does not carry every release marvelcdb "
            f"already knows - a partial deck would be worse than no answer.")

    meta = parse_meta(payload.get("meta"))
    aspects = [meta[key] for key in ("aspect", "aspect2") if meta.get(key)]

    slots: dict[str, int] = {}
    unknown: dict[str, int] = {}
    for code, count in (payload.get("slots") or {}).items():
        row = conn.execute(
            "SELECT canonical_code FROM cards WHERE code = ?",
            (code,)).fetchone()
        if row is None:
            unknown[code] = unknown.get(code, 0) + int(count)
            continue
        canonical = row["canonical_code"]
        slots[canonical] = slots.get(canonical, 0) + int(count)

    return Deck(
        id=str(payload["id"]) if payload.get("id") is not None else None,
        name=payload.get("name") or "",
        hero_code=hero_code,
        hero_name=payload.get("hero_name") or hero["name"],
        aspects=aspects,
        # Absent means current: 118 of 124 decks carry no `format` at all,
        # so reading absence as "unknown" would exclude the corpus.
        deck_format=meta.get("format") or "current",
        slots=slots, unknown=unknown,
        ignore_limit={k: int(v) for k, v in
                      (payload.get("ignoreDeckLimitSlots") or {}).items()},
        source=source)


def fetch(conn, ref: str) -> Deck:
    """A deck from a marvelcdb id, a marvelcdb URL, or a local JSON file."""
    identifier = deck_id(ref)
    if identifier is not None:
        return normalise(conn, _get(f"{API}/decklist/{identifier}"),
                         source=f"marvelcdb:{identifier}")
    path = Path(ref)
    if not path.is_file():
        raise DeckError(
            f"{ref!r} is neither a marvelcdb deck id, a marvelcdb URL, nor a "
            f"file that exists.")
    return normalise(conn, json.loads(path.read_text(encoding="utf-8")),
                     source=str(path))


def corpus_path():
    from . import paths

    return paths.data_dir() / "decks"


def corpus(*, exclude_legacy: bool = True):
    """Published decks previously fetched by `tools/deck_corpus.py`.

    `format: legacy` decks were built under a different rule set. Left in,
    they inflate the rejection rate with format mismatches that read as
    bugs in `legality.yaml` - contaminating the exact signal the corpus
    exists to provide. Measured: 5 of 124 sampled decks are `legacy`.
    """
    for path in sorted(corpus_path().glob("*.json")):
        for payload in json.loads(path.read_text(encoding="utf-8")):
            meta = parse_meta(payload.get("meta"))
            if exclude_legacy and meta.get("format") == "legacy":
                continue
            yield payload


def _print_findings(deck, findings) -> None:
    from . import deckcheck

    rules = [f for f in findings if f.kind == "rule"]
    notes = [f for f in findings if f.kind == "note"]
    print(f"{deck.name} - {deck.hero_name}, "
          f"{'/'.join(deck.aspects) or 'no aspect recorded'}")
    for finding in rules:
        print(f"  {'ok  ' if finding.ok else 'FAIL'} {finding.rule}: "
              f"{finding.detail}")
        if finding.rr_entry and not finding.ok:
            print(f"       see: mc-jarvis rules show {finding.rr_entry!r}")
    for finding in notes:
        print(f"  note {finding.rule}: {finding.detail}")
    print(f"\n  {'legal' if deckcheck.verdict(findings) else 'NOT legal'}"
          f" by the rules this tool encodes")


def handle(args) -> int:
    from .cards import _open
    from .cli import emit

    conn = _open()
    try:
        deck = fetch(conn, args.deck)
    except DeckError as exc:
        print(f"mc-jarvis deck: {exc}")
        return 1

    if args.deck_cmd == "fetch":
        emit({"id": deck.id, "name": deck.name, "hero": deck.hero_name,
              "aspects": deck.aspects, "format": deck.deck_format,
              "cards": sum(deck.slots.values()), "slots": deck.slots,
              "unknown": deck.unknown}, as_json=args.json)
        if not args.json and deck.unknown:
            print(f"  {sum(deck.unknown.values())} card(s) are not in this "
                  f"index: {', '.join(sorted(deck.unknown))}")
        return 0

    if args.deck_cmd == "stats":
        from . import deckstats

        emit(deckstats.profile(conn, deck), as_json=args.json)
        return 0

    from . import deckcheck

    findings = deckcheck.check(conn, deck)
    legal = deckcheck.verdict(findings)
    if args.json:
        emit({"deck": deck.name, "hero": deck.hero_name, "legal": legal,
              "findings": [vars(f) for f in findings]}, as_json=True)
    else:
        _print_findings(deck, findings)
    return 0 if legal else 1
