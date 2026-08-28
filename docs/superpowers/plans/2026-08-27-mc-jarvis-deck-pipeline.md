# Deck Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mc-jarvis deck fetch|check|stats` and `mc-jarvis collection set|show` — import a marvelcdb deck, say whether it is legal and why, describe its shape, and let every card-returning command filter to what the player owns.

**Architecture:** Four layers, each testable alone. `deckfetch.py` turns a marvelcdb id, URL, or local file into a normalised `Deck` and never touches the index's rules. `collection.py` owns pack ownership and the one SQL predicate every filtered command shares. `deckcheck.py` applies `legality.yaml` to a `Deck`, in the order §10 requires. `deckstats.py` aggregates the same excluded card list `deckcheck` produces, so a permanent upgrade cannot be legal-but-counted. Out-of-deck classification is **not** rebuilt: `outofdeck.classify` already populates `out_of_deck` with all four mechanisms.

**Tech Stack:** Python 3.10+, SQLite with FTS5, PyYAML, `urllib.request`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-mc-jarvis-design.md`

> **Read §10.1 first.** The working pass of 2026-08-27 corrects §10 in two
> places — the collection filter and the `01043a`–`01043d` case — and adds
> three findings §10 does not have. Where §10.1 and §10 disagree, §10.1 is
> right; it has numbers.

**Out of scope:** `assess --deck` (assess spec §9). It consumes `Deck` and lands once this plan is done. Do not begin it.

## Global Constraints

- **The repository ships code and configuration only.** No card text, no rules text, no PDFs, no built index, and **no fetched decks**. The decklist corpus in Task 5 lives under `data/` (gitignored) and never under `tests/`.
- **`config/legality.yaml` gets numbers and pointers, never prose.** Every rule added there comes from the rulebook, so it carries the value and an `rr_entry`; the wording is read from `rules_entries` at print time. `config/timing.yaml`'s `tie_breaks` is the worked example. CI rejects a pasted sentence.
- **Every leaf command takes `--json`.** Added by `cli._leaf`; do not add it by hand.
- **A task's real-data check is a gate, not a closing flourish.** "Expected: a small number" is not a threshold. Every gate names a number that can fail.
- **A negative result about this data is only as strong as the variants tried**, and must be reported with the variants listed.
- **Ownership is binary and there is no copy arithmetic** (§10). `deck_limit` binds before physical copies, verified across all 1,607 player cards.
- **Report a card the index does not carry; never drop it silently** (§10.1).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/mc_jarvis/deckfetch.py` | Fetch and normalise. marvelcdb id/URL/file → `Deck`. Also the `by_date` bulk path. Knows nothing about legality. |
| `src/mc_jarvis/collection.py` | Owned packs: storage, `set`/`show`, and the single `owned_predicate()` every filtered query uses. |
| `src/mc_jarvis/deckcheck.py` | `legality.yaml` applied to a `Deck`, in §10's required order. |
| `src/mc_jarvis/deckstats.py` | Curves and mixes over the same included-card list `deckcheck` computes. |
| `config/legality.yaml` | Gains `deck_rules`: sizes, aspect purity, the dual-aspect and `pool` exceptions — each a number plus an `rr_entry`. |
| `tests/test_deckfetch.py`, `tests/test_collection.py`, `tests/test_deckcheck.py`, `tests/test_deckstats.py` | |

`deckfetch` is separate from `deckcheck` because a deck you cannot validate is still worth reading, and because the corpus in Task 5 fetches thousands of decks without validating any of them until the validator exists.

---

## Task 1: Fetch and normalise a deck

Implements §10's source contract, with §10.1's corrections and the API shapes measured 2026-08-27 across 124 published decks.

**Files:**
- Create: `src/mc_jarvis/deckfetch.py`
- Modify: `src/mc_jarvis/schema.py` (no change needed — verify), `pyproject.toml` (no change)
- Test: `tests/test_deckfetch.py`

**Interfaces:**
- Produces:
  - `deckfetch.Deck` — dataclass: `id: str | None`, `name: str`, `hero_code: str`, `hero_name: str`, `aspects: list[str]`, `deck_format: str`, `slots: dict[str, int]` (canonical codes), `unknown: dict[str, int]`, `ignore_limit: dict[str, int]`, `source: str`
  - `deckfetch.parse_meta(raw) -> dict`
  - `deckfetch.normalise(conn, payload: dict, *, source: str) -> Deck`
  - `deckfetch.fetch(conn, ref: str) -> Deck`
  - `deckfetch.fetch_by_date(day: str) -> list[dict]`
  - `deckfetch.DeckError`

### What the API actually returns

Measured 2026-08-27 over 124 decks from five `by_date` days. **Three of these differ from §10.**

| Field | Reality |
|---|---|
| `meta` | a **JSON string** on every observed deck (`'{"aspect":"justice"}'`). §10 warns it is a decoded object elsewhere; parse both. |
| `format` | **inside `meta`**, not at the top level. 118 absent, 5 `legacy`, 1 `current`. **Absent means current.** |
| `aspect2` | inside `meta`, on 3 of 124. Dual aspect is real and rare. |
| `aspect` | `justice` 34, `aggression` 29, `leadership` 29, `protection` 29, **`pool` 3** — Deadpool's own aspect. |
| `ignoreDeckLimitSlots` | present on every deck and **`null` on all 124**. Handle it, do not rely on exercising it. |
| `by_date` payload | carries the **same keys as the single-deck endpoint**, so the corpus needs one request per day, not one per deck. |

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deckfetch.py
import pytest

from mc_jarvis import deckfetch, index


def _mkdb(tmp_path, cards):
    """cards: (code, name, type_code, pack_code, duplicate_of)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, pack_code, duplicate_of, "
        "canonical_code, is_reprint, raw) VALUES (?, ?, ?, ?, ?, ?, ?, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[4] or c[0], int(bool(c[4])))
         for c in cards])
    conn.commit()
    return conn


def test_meta_parses_from_a_json_string():
    """Measured: `meta` is a JSON string on all 124 sampled decks. §10 warns
    it is an already-decoded object on other endpoints, so both must work."""
    assert deckfetch.parse_meta('{"aspect":"justice"}') == {
        "aspect": "justice"}
    assert deckfetch.parse_meta({"aspect": "justice"}) == {
        "aspect": "justice"}


def test_meta_that_is_absent_or_junk_is_empty_not_fatal():
    for raw in (None, "", "   ", "not json"):
        assert deckfetch.parse_meta(raw) == {}


def test_format_is_read_from_meta_and_absent_means_current():
    """§10 puts `format` at the top level; measured, it is inside `meta`,
    and absent on 118 of 124 decks. Reading absence as "unknown" would
    exclude 95% of the regression corpus."""
    assert deckfetch.parse_meta('{"aspect":"justice"}').get("format") is None


def test_both_aspects_are_carried(tmp_path):
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "Spider-Man",
        "meta": '{"aspect":"justice","aspect2":"leadership"}', "slots": {}},
        source="test")
    assert deck.aspects == ["justice", "leadership"]
    assert deck.deck_format == "current"


def test_a_reprinted_slot_resolves_to_its_canonical_card(tmp_path):
    """§10.1: 337 player cards are reprints. A deck names whichever
    printing its builder owned, so two decks holding the same card can
    name different codes."""
    conn = _mkdb(tmp_path, [
        ("01001a", "Spider-Man", "hero", "core", None),
        ("27047", "Dum Dum Dugan", "ally", "sm", None),
        ("50021", "Dum Dum Dugan", "ally", "aos", "27047")])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": '{"aspect":"justice"}', "slots": {"50021": 1}},
        source="test")
    assert deck.slots == {"27047": 1}


def test_two_printings_of_one_card_are_added_not_listed_twice(tmp_path):
    conn = _mkdb(tmp_path, [
        ("01001a", "Spider-Man", "hero", "core", None),
        ("27047", "Dum Dum Dugan", "ally", "sm", None),
        ("50021", "Dum Dum Dugan", "ally", "aos", "27047")])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": "{}", "slots": {"27047": 1, "50021": 1}}, source="test")
    assert deck.slots == {"27047": 2}


def test_a_slot_the_index_does_not_carry_is_reported_not_dropped(tmp_path):
    """§10.1: coverage is bounded by marvelcdb, exactly as it is for
    scenarios. Dropping the slot yields a deck that fails a size check for
    a reason the player cannot see."""
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": "{}", "slots": {"99999": 3}}, source="test")
    assert deck.slots == {}
    assert deck.unknown == {"99999": 3}


def test_an_unknown_hero_is_an_error_not_a_silent_deck(tmp_path):
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    with pytest.raises(deckfetch.DeckError, match="99999a"):
        deckfetch.normalise(conn, {
            "id": 1, "name": "D", "hero_code": "99999a", "hero_name": "?",
            "meta": "{}", "slots": {}}, source="test")


def test_ignore_deck_limit_slots_survives_being_null(tmp_path):
    """Present on every observed deck and null on all 124 of them."""
    conn = _mkdb(tmp_path, [("01001a", "Spider-Man", "hero", "core", None)])
    deck = deckfetch.normalise(conn, {
        "id": 1, "name": "D", "hero_code": "01001a", "hero_name": "S",
        "meta": "{}", "slots": {}, "ignoreDeckLimitSlots": None},
        source="test")
    assert deck.ignore_limit == {}


@pytest.mark.parametrize("ref,want", [
    ("64331", "64331"),
    ("https://marvelcdb.com/decklist/view/64331/nova-justice", "64331"),
    ("https://marvelcdb.com/decklist/view/64331", "64331"),
])
def test_a_deck_id_is_recognised_in_any_of_its_forms(ref, want):
    assert deckfetch.deck_id(ref) == want


def test_a_local_file_is_not_mistaken_for_an_id(tmp_path):
    path = tmp_path / "deck.json"
    path.write_text("{}", encoding="utf-8")
    assert deckfetch.deck_id(str(path)) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_deckfetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.deckfetch'`

- [ ] **Step 3: Write `deckfetch.py`**

```python
"""Deck import (spec §10, as corrected by §10.1).

Normalisation only. Whether a deck is LEGAL is `deckcheck`'s question,
and keeping them apart is what lets the regression corpus in the
validator's own plan fetch thousands of decks before a validator exists.

Everything here was measured against the live API on 2026-08-27, over 124
published decks. Three of the shapes differ from what §10 records, and
each difference is noted where it bites.
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
    an exception: the corpus is thousands of user-authored decks and one
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
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


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
            f"marvelcdb, which does not carry every release the site itself "
            f"already knows - a partial deck would be worse than no answer.")

    meta = parse_meta(payload.get("meta"))
    aspects = [meta[key] for key in ("aspect", "aspect2")
               if meta.get(key)]

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
        hero_code=hero_code, hero_name=payload.get("hero_name") or hero["name"],
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_deckfetch.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Gate against the live API**

```python
# tests/test_deckfetch.py — append
@pytest.mark.integration
def test_the_live_api_still_has_the_shape_this_module_assumes(real_index):
    """Every assumption in this module, re-checked against the live site.
    Measured 2026-08-27 over 124 decks across five days; this checks one
    day, which is enough to catch a shape change.

    If this fails, read the payload before changing the parser: a field
    that moved is a finding, not a bug to route around.
    """
    decks = deckfetch.fetch_by_date("2026-08-01")
    assert len(decks) > 5, len(decks)

    required = {"id", "name", "hero_code", "hero_name", "slots", "meta",
                "ignoreDeckLimitSlots"}
    for deck in decks:
        assert required <= set(deck), sorted(required - set(deck))
        # `format` at the TOP level is what §10 claimed; it is in `meta`.
        assert "format" not in deck

    metas = [deckfetch.parse_meta(d["meta"]) for d in decks]
    assert all("aspect" in m for m in metas)
    assert all(m.get("format") in (None, "legacy", "current") for m in metas)


@pytest.mark.integration
def test_a_real_deck_normalises_with_no_unknown_slots(real_index):
    """An unknown slot means marvelsdb is behind marvelcdb. A few are
    expected after a new release; a flood means the card data is stale."""
    decks = deckfetch.fetch_by_date("2026-08-01")
    parsed = []
    for payload in decks:
        try:
            parsed.append(deckfetch.normalise(real_index, payload,
                                              source="gate"))
        except deckfetch.DeckError:
            continue
    assert parsed, "no deck from that day resolved at all"
    missing = sum(len(d.unknown) for d in parsed)
    assert missing <= len(parsed), (
        f"{missing} unknown slots across {len(parsed)} decks - the card "
        f"data is probably stale; run `mc-jarvis update`")
```

- [ ] **Step 6: Run the gate**

Run: `uv run pytest tests/test_deckfetch.py -m integration -v`

**Gate.** `by_date` for 2026-08-01 returns **35** decks; every one carries the seven required keys, none carries a top-level `format`, and every `meta` has an `aspect`. If `format` appears at the top level, §10 was right and §10.1 is wrong — read the payload and correct the spec rather than the code.

- [ ] **Step 7: Commit**

```bash
git add src/mc_jarvis/deckfetch.py tests/test_deckfetch.py
git commit -m "feat: fetch and normalise a marvelcdb deck, canonicalising reprints"
```

---

## Task 2: Collection, and what `--owned` means per command

Implements §10's collection model with §10.1's corrected filter.

**Files:**
- Create: `src/mc_jarvis/collection.py`
- Modify: `src/mc_jarvis/schema.py`, `src/mc_jarvis/index.py` (`SCHEMA_VERSION`), `src/mc_jarvis/cli.py`
- Test: `tests/test_collection.py`

**Interfaces:**
- Produces:
  - `collection.owned_packs(conn) -> list[str]`
  - `collection.set_packs(conn, packs) -> dict`
  - `collection.owned_predicate() -> str` — SQL fragment for a `WHERE` clause
  - `collection.filter_codes(conn, codes) -> list[str]`
  - `collection.UnknownPack`
  - `collection.OWNED_COMMANDS: frozenset[str]`

### The filter is over the canonical group, not the pack

§10 gives the filter as `WHERE pack_code IN (owned)`. §10.1 measured why that is wrong: **337 player cards are reprints**, so owning Agents of S.H.I.E.L.D. lets you play Dum Dum Dugan whether or not you own Sinister Motives. Own *any* printing, have the card.

§10's actual point is untouched — ownership stays binary and there is still no copy arithmetic — because `deck_limit` binds before physical copies.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_collection.py
import pytest

from mc_jarvis import collection, index


def _mkdb(tmp_path):
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO packs (code, name) VALUES (?, ?)",
        [("core", "Core Set"), ("sm", "Sinister Motives"),
         ("aos", "Agents of S.H.I.E.L.D.")])
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, pack_code, duplicate_of, "
        "canonical_code, is_reprint, raw) VALUES (?, ?, ?, ?, ?, ?, ?, '{}')",
        [("01001a", "Spider-Man", "hero", "core", None, "01001a", 0),
         ("27047", "Dum Dum Dugan", "ally", "sm", None, "27047", 0),
         ("50021", "Dum Dum Dugan", "ally", "aos", "27047", "27047", 1),
         ("27099", "Web-Shooter", "upgrade", "sm", None, "27099", 0)])
    conn.commit()
    return conn


def test_owning_a_reprint_pack_gives_you_the_card(tmp_path):
    """§10.1's correction. `WHERE pack_code IN (owned)` - §10's filter -
    would hide Dum Dum Dugan from a player who owns only Agents of
    S.H.I.E.L.D., because his canonical printing is in Sinister Motives."""
    conn = _mkdb(tmp_path)
    collection.set_packs(conn, ["core", "aos"])
    assert "27047" in collection.filter_codes(conn, ["27047", "27099"])


def test_a_card_from_no_owned_pack_is_filtered_out(tmp_path):
    conn = _mkdb(tmp_path)
    collection.set_packs(conn, ["core", "aos"])
    assert "27099" not in collection.filter_codes(conn, ["27047", "27099"])


def test_an_empty_collection_filters_nothing_out(tmp_path):
    """No collection means the player has not said, which is different
    from owning nothing. Filtering everything away would look like a
    broken index."""
    conn = _mkdb(tmp_path)
    assert collection.owned_packs(conn) == []
    assert set(collection.filter_codes(conn, ["27047", "27099"])) == {
        "27047", "27099"}


def test_setting_packs_replaces_rather_than_appends(tmp_path):
    conn = _mkdb(tmp_path)
    collection.set_packs(conn, ["core", "sm"])
    collection.set_packs(conn, ["core"])
    assert collection.owned_packs(conn) == ["core"]


def test_an_unknown_pack_code_is_named_not_ignored(tmp_path):
    """A typo that silently sets an empty collection is the worst
    outcome: every later search quietly returns less."""
    conn = _mkdb(tmp_path)
    with pytest.raises(collection.UnknownPack, match="corr"):
        collection.set_packs(conn, ["core", "corr"])


def test_owned_is_offered_only_where_it_means_something():
    """`cli._leaf` adds `--owned` to all 14 leaf commands (§10.1), so
    un-stubbing it is a per-command decision. It is meaningless on
    `doctor`, `status`, `update`, `install-skill`, `timing` and
    `rules search`, and offering it there implies a filter that never
    happens."""
    assert "card search" in collection.OWNED_COMMANDS
    assert "identity" in collection.OWNED_COMMANDS
    for name in ("doctor", "status", "update", "install-skill", "timing",
                 "rules search"):
        assert name not in collection.OWNED_COMMANDS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_collection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.collection'`

- [ ] **Step 3: Add the table to `schema.py`**

```sql
-- Packs the player owns. Ownership is BINARY (spec §10): `deck_limit`
-- never exceeds `quantity` across all 1,607 player cards, so owning a
-- pack means owning enough copies to play any card in it to its limit.
-- There is no copy arithmetic anywhere in this system, and the intuitive
-- "count what I own against what I want" model is the wrong one.
CREATE TABLE IF NOT EXISTS owned_packs (
    pack_code TEXT PRIMARY KEY
);
```

Bump `SCHEMA_VERSION` from 20 to 21.

- [ ] **Step 4: Write `collection.py`**

```python
"""Pack ownership (spec §10, corrected by §10.1).

One predicate, shared. Every command that filters by ownership uses
`owned_predicate()` rather than writing its own `WHERE`, because the
filter is subtler than it looks and a second copy would get it wrong.
"""
from __future__ import annotations

# Commands where `--owned` changes the answer. `cli._leaf` puts the flag
# on all 14 leaves; these are the ones that return cards (§10.1). The
# others accept it today and reject it at dispatch, which is worse than
# not offering it: it implies a filter that never happens.
OWNED_COMMANDS = frozenset({
    "card search", "card show", "identity", "encounter", "rules show",
})


class UnknownPack(RuntimeError):
    """A pack code that is not in the index."""


def owned_packs(conn) -> list[str]:
    return [r["pack_code"] for r in conn.execute(
        "SELECT pack_code FROM owned_packs ORDER BY pack_code")]


def set_packs(conn, packs) -> dict:
    """Replace the collection. Unknown codes raise rather than vanish."""
    wanted = sorted(dict.fromkeys(packs))
    known = {r["code"] for r in conn.execute("SELECT code FROM packs")}
    missing = [p for p in wanted if p not in known]
    if missing:
        raise UnknownPack(
            f"not pack codes in this index: {', '.join(missing)}. Run "
            f"`mc-jarvis collection show --available` for the list; a typo "
            f"here silently narrows every later search.")
    conn.execute("DELETE FROM owned_packs")
    conn.executemany("INSERT INTO owned_packs (pack_code) VALUES (?)",
                     [(p,) for p in wanted])
    conn.commit()
    return {"owned": len(wanted)}


def owned_predicate() -> str:
    """A `WHERE` fragment selecting cards the player can field.

    Over the CANONICAL GROUP, not the pack. §10 gives this as
    `pack_code IN (owned)`, which is wrong for any reprinted card: 337
    player cards have more than one printing, and owning Agents of
    S.H.I.E.L.D. lets you play Dum Dum Dugan whether or not you own
    Sinister Motives.
    """
    return ("canonical_code IN (SELECT canonical_code FROM cards "
            " WHERE pack_code IN (SELECT pack_code FROM owned_packs))")


def filter_codes(conn, codes) -> list[str]:
    """`codes` narrowed to what the player owns.

    An EMPTY collection filters nothing: the player has not said what they
    own, which is not the same as owning nothing. Returning nothing there
    looks exactly like a broken index.
    """
    codes = list(codes)
    if not codes or not owned_packs(conn):
        return codes
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT code FROM cards WHERE code IN ({marks}) "
        f"AND {owned_predicate()}", codes)
    return [r["code"] for r in rows]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_collection.py -v`
Expected: PASS, 6 tests

- [ ] **Step 6: Gate against the real corpus**

```bash
uv run python -c "
from mc_jarvis import index, paths, collection
conn = index.connect(paths.db_path())
packs = [r['code'] for r in conn.execute('SELECT code FROM packs ORDER BY code')]
print('packs:', len(packs))
collection.set_packs(conn, ['core'])
n = conn.execute(f'SELECT COUNT(*) FROM cards WHERE {collection.owned_predicate()}').fetchone()[0]
print('cards playable owning only the Core Set:', n)
collection.set_packs(conn, packs)
n = conn.execute(f'SELECT COUNT(*) FROM cards WHERE {collection.owned_predicate()}').fetchone()[0]
total = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
print('owning everything:', n, 'of', total)
conn.execute('DELETE FROM owned_packs'); conn.commit()
"
```

**Gate.** Owning every pack must select **every card** — if it does not, the canonical-group join is dropping rows and every `--owned` answer is short. Owning only `core` must select strictly fewer, and more than zero.

- [ ] **Step 7: Wire the CLI**

In `cli.build_parser`, replace the unconditional `--owned` in `_leaf` with an explicit opt-in. Change `_leaf`'s signature to take `owned: bool = False`, add the flag only when asked, and pass `owned=True` on the five commands in `OWNED_COMMANDS`. Then add the collection command:

```python
    col = _leaf(sub, "collection", "packs you own")
    col.add_argument("collection_cmd", choices=["set", "show"])
    col.add_argument("packs", nargs="*",
                     help="pack codes, for `set`")
    col.add_argument("--available", action="store_true",
                     help="list every pack code this index knows")
```

and in `_dispatch`:

```python
    if name == "collection":
        from . import collection as coll
        return coll.handle(args)
```

Delete the global rejection at `cli.py:196`.

- [ ] **Step 8: Commit**

```bash
git add src/mc_jarvis/collection.py src/mc_jarvis/schema.py \
        src/mc_jarvis/index.py src/mc_jarvis/cli.py tests/test_collection.py
git commit -m "feat: collection tracking, filtered over canonical printings"
```

---

## Task 3: Deck size, copies, and the exclusion order

Implements §10's copy rules and the Sp//dr ordering constraint. **This task builds the half of `deck check` that does not need `legality.yaml` to grow.**

**Files:**
- Create: `src/mc_jarvis/deckcheck.py`
- Test: `tests/test_deckcheck.py`

**Interfaces:**
- Consumes: `deckfetch.Deck`, the `out_of_deck` table
- Produces:
  - `deckcheck.Finding` — dataclass `rule: str`, `ok: bool`, `detail: str`, `cards: list[str]`
  - `deckcheck.included(conn, deck) -> dict[str, int]`
  - `deckcheck.excluded(conn, deck) -> dict[str, str]` — code → mechanism
  - `deckcheck.check_size(conn, deck, config) -> Finding`
  - `deckcheck.check_copies(conn, deck, override=None) -> Finding`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deckcheck.py
import pytest

from mc_jarvis import deckcheck, deckfetch, index


def _mkdb(tmp_path, cards, out_of_deck=()):
    """cards: (code, name, type_code, pack, deck_limit, quantity)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, pack_code, deck_limit, "
        "quantity, canonical_code, is_reprint, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[0]) for c in cards])
    conn.executemany(
        "INSERT INTO out_of_deck (code, mechanism, note) VALUES (?, ?, NULL)",
        out_of_deck)
    conn.commit()
    return conn


def _deck(**kw):
    base = {"name": "D", "hero_code": "h1", "hero_name": "H",
            "aspects": ["justice"], "slots": {}}
    base.update(kw)
    return deckfetch.Deck(**base)


def test_a_permanent_card_is_not_in_the_deck(tmp_path):
    """A permanent upgrade left in the count inflates deck size and skews
    every curve of a deck it was never part of."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("c1", "Claws", "upgrade", "core", 1, 1),
                  ("c2", "Aid", "ally", "core", 3, 3)],
                 out_of_deck=[("c1", "permanent")])
    deck = _deck(slots={"c1": 1, "c2": 3})
    assert deckcheck.included(conn, deck) == {"c2": 3}
    assert deckcheck.excluded(conn, deck) == {"c1": "permanent"}


def test_exclusion_happens_before_unique_matching(tmp_path):
    """Sp//dr, named in §10. Her set has `SP//dr Suit` as a hero face AND
    a permanent support of the same title, both in play at once. Unique
    matching would reject the deck - except the permanent card was never
    in it. Reversing the order makes her fail her own legality check."""
    conn = _mkdb(tmp_path,
                 [("h1", "SP//dr Suit", "hero", "spdr", None, 1),
                  ("s1", "SP//dr Suit", "support", "spdr", 1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("h1", "identity"), ("s1", "permanent")])
    deck = _deck(hero_code="h1", slots={"s1": 1, "a1": 3})
    assert deckcheck.included(conn, deck) == {"a1": 3}


def test_deck_size_counts_included_cards_only(tmp_path):
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("p1", "Perm", "upgrade", "core", 1, 1),
                  ("a1", "Ally", "ally", "core", 3, 3)],
                 out_of_deck=[("p1", "permanent")])
    deck = _deck(slots={"p1": 1, "a1": 3})
    finding = deckcheck.check_size(conn, deck, {"deck_rules": {
        "minimum_size": 40, "rr_entry": "Deck"}})
    assert not finding.ok
    assert "3" in finding.detail


def test_a_null_deck_limit_falls_back_to_quantity(tmp_path):
    """§10: `deck_limit` is null on 120 player cards. Null is not
    "unlimited" - without the fallback the validator has no cap at all and
    accepts arbitrary quantities of a signature card."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1),
                            ("s1", "Signature", "ally", "core", None, 2)])
    ok = deckcheck.check_copies(conn, _deck(slots={"s1": 2}))
    assert ok.ok
    bad = deckcheck.check_copies(conn, _deck(slots={"s1": 3}))
    assert not bad.ok
    assert "s1" in bad.cards


def test_the_four_wakanda_forever_variants_are_four_slots(tmp_path):
    """§10.1: §10 calls 01043a-d a multi-part card whose faces should
    collapse. They are four RESOURCE VARIANTS - energy, mental, physical,
    wild - each separately deck-legal, with limits 1, 1, 1 and 2. Five
    copies, not one. Collapsing them undercounts a legal deck by four."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1)]
                 + [(f"01043{s}", "Wakanda Forever!", "event", "core", lim,
                     lim) for s, lim in
                    (("a", 1), ("b", 1), ("c", 1), ("d", 2))])
    deck = _deck(slots={"01043a": 1, "01043b": 1, "01043c": 1, "01043d": 2})
    assert sum(deckcheck.included(conn, deck).values()) == 5
    assert deckcheck.check_copies(conn, deck).ok


def test_a_double_sided_card_is_one_card_not_two(tmp_path):
    """§10.1: 19 player-card code stems are genuine double-sided faces -
    Psi-Knife, Odin, Norn Stone, the four Basic upgrades. `back_link`
    marks them, and it is the same discriminator `assess.back_faces`
    already uses for encounter cards. Counting both faces inflates the
    deck by one card each."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("41002a", "Psi-Knife", "upgrade", "psy", 1, 1),
                  ("41002b", "Psi-Knife", "upgrade", "psy", 1, 1)])
    conn.execute("UPDATE cards SET back_link = '41002b' WHERE code = '41002a'")
    conn.commit()
    deck = _deck(slots={"41002a": 1, "41002b": 1})
    assert deckcheck.included(conn, deck) == {"41002a": 1}


def test_a_resource_variant_is_not_a_back_face(tmp_path):
    """The other side of the same rule, and why `back_link` rather than a
    code-suffix pattern: the Wakanda Forever! variants share a stem and
    are four separate cards."""
    conn = _mkdb(tmp_path,
                 [("h1", "Hero", "hero", "core", None, 1),
                  ("01043a", "Wakanda Forever!", "event", "core", 1, 1),
                  ("01043b", "Wakanda Forever!", "event", "core", 1, 1)])
    deck = _deck(slots={"01043a": 1, "01043b": 1})
    assert deckcheck.included(conn, deck) == {"01043a": 1, "01043b": 1}


def test_a_deck_with_unknown_slots_says_so(tmp_path):
    """A deck whose size fails because three cards could not be resolved
    must not report "37 cards, needs 40" as if the player built it wrong."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1)])
    deck = _deck(slots={}, unknown={"99999": 3})
    finding = deckcheck.check_size(conn, deck, {"deck_rules": {
        "minimum_size": 40, "rr_entry": "Deck"}})
    assert "99999" in finding.detail
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_deckcheck.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.deckcheck'`

- [ ] **Step 3: Write the first half of `deckcheck.py`**

```python
"""Deck legality (spec §10).

`legality.yaml` is the highest-risk component in this project: an error in
it is invisible and propagates into every downstream feature. Two things
hold it down - the regression corpus of published decks, and the rule that
every value here carries the Rules Reference entry it came from, so the
wording is read from the user's own rulebook rather than restated.

ORDER MATTERS, and §10 states the trap outright: classify and remove
out-of-deck cards BEFORE applying unique matching. Sp//dr's set has
`SP//dr Suit` as both a hero face and a permanent support, so reversing
the order makes her fail her own legality check.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Finding:
    rule: str
    ok: bool
    detail: str
    cards: list[str] = field(default_factory=list)
    rr_entry: str | None = None


def excluded(conn, deck) -> dict[str, str]:
    """Slots that are not part of the constructed deck, and why.

    Read from `out_of_deck`, which `outofdeck.classify` fills from all
    four mechanisms: the `permanent` keyword, the `hero_special` set type,
    identity faces, and the config entries for cards the data does not
    mark at all (Rogue's Touched, Valkyrie's Death-Glow).
    """
    if not deck.slots:
        return {}
    marks = ",".join("?" * len(deck.slots))
    return {r["code"]: r["mechanism"] for r in conn.execute(
        f"SELECT code, mechanism FROM out_of_deck WHERE code IN ({marks})",
        list(deck.slots))}


def included(conn, deck) -> dict[str, int]:
    """The constructed deck: every slot the exclusions leave behind.

    Three exclusions, not one. `out_of_deck` covers permanents, the
    `hero_special` decks, identity faces and the config entries. Back
    faces are the third: a double-sided card is two rows in marvelsdb and
    counting both inflates the deck (§10.1 measured 19 such player-card
    groups). Reprints cannot appear here - `deckfetch` canonicalises every
    slot before the deck reaches this module.
    """
    out = excluded(conn, deck)
    backs = _back_faces(conn)
    return {code: n for code, n in deck.slots.items()
            if code not in out and code not in backs}


def _back_faces(conn) -> set[str]:
    """Codes that are the back of a card already counted by its front.

    The same rule `assess.back_faces` applies to encounter cards, reused
    rather than reimplemented: `back_link` separated the 24 ambiguous
    player-card stems cleanly into 19 faces and 5 resource variants, with
    nothing left over (§10.1).
    """
    from . import assess

    return assess.back_faces(conn)


def _limit(row, override: dict | None = None) -> int:
    """A card's per-deck cap.

    The null fallback is NOT reimplemented here: `index.resolve_deck_limit`
    already encodes it, and the index build already asserts that
    `deck_limit` never exceeds `quantity` (both per printing and across
    printings). A second copy of that rule would drift from the first.

    An identity override can lower the cap: Warlock's
    `max_copies_non_signature: 1` binds below `deck_limit` for every card
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
    cards = included(conn, deck)
    size = sum(cards.values())
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
    for row in conn.execute(
            f"SELECT code, name, deck_limit, quantity, set_code FROM cards "
            f"WHERE code IN ({marks})", list(cards)):
        cap = _limit(row, override)
        if cards[row["code"]] > cap:
            over.append(f"{row['name']} x{cards[row['code']]} (limit {cap})")
    return Finding(
        rule="deck_limit", ok=not over,
        detail="; ".join(over) if over else "every card within its limit",
        cards=[c.split(" x")[0] for c in over])
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_deckcheck.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add src/mc_jarvis/deckcheck.py tests/test_deckcheck.py
git commit -m "feat: deck size and copy limits, excluding before matching"
```

---

## Task 4: Aspect purity, uniqueness, and `legality.yaml`

Completes `deck check`.

**Files:**
- Modify: `src/mc_jarvis/deckcheck.py`, `config/legality.yaml`
- Test: `tests/test_deckcheck.py`

**Interfaces:**
- Consumes: `deckrules.for_identity`, `identity.matches`
- Produces:
  - `deckcheck.check_aspects(conn, deck, config) -> Finding`
  - `deckcheck.check_unique(conn, deck) -> Finding`
  - `deckcheck.check(conn, deck, config=None) -> list[Finding]`

- [ ] **Step 1: Add `deck_rules` to `config/legality.yaml`**

Every value carries the entry it came from. **No rulebook sentences** — CI rejects them, and `mc-jarvis rules show <entry>` prints the wording from the user's own copy.

```yaml
# Deckbuilding rules, from the Rules Reference. NUMBERS AND POINTERS ONLY:
# each value names the RR entry it came from, and the wording is read from
# `rules_entries` on the user's machine at print time. The same rule the
# timing reference follows.
deck_rules:
  minimum_size: 40
  rr_entry: Deck

  # One aspect, or two under the dual-aspect allowance. Measured across
  # 124 published decks: 121 single-aspect, 3 with `aspect2`.
  aspects:
    default_max: 1
    rr_entry: Aspect

  # Deadpool's own aspect. 3 of 124 sampled decks declare it.
  pool_aspect: pool
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_deckcheck.py — append
def test_a_single_aspect_deck_passes(tmp_path):
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1)])
    config = {"deck_rules": {"aspects": {"default_max": 1,
                                         "rr_entry": "Aspect"},
                             "pool_aspect": "pool"}}
    assert deckcheck.check_aspects(conn, _deck(aspects=["justice"]),
                                   config).ok


def test_two_aspects_fail_unless_the_identity_allows_it(tmp_path):
    """`deckbuilding_overrides` already records the identities that may
    choose two aspects; the rule is not a blanket allowance."""
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1)])
    config = {"deck_rules": {"aspects": {"default_max": 1,
                                         "rr_entry": "Aspect"},
                             "pool_aspect": "pool"}}
    finding = deckcheck.check_aspects(
        conn, _deck(aspects=["justice", "leadership"]), config)
    assert not finding.ok
    assert "two aspects" in finding.detail


def test_an_identity_that_may_take_two_aspects_passes(tmp_path):
    """Spider-Woman's override is already in `deckbuilding_overrides` with
    `aspects: 2`. The dual-aspect allowance is per identity, not a blanket
    rule, and 3 of 124 sampled decks use it."""
    conn = _mkdb(tmp_path, [("h1", "Spider-Woman", "hero", "core", None, 1)])
    conn.execute("INSERT INTO identity_faces (identity_key, code) "
                 "VALUES ('spider_woman', 'h1')")
    conn.commit()
    config = {"deck_rules": {"aspects": {"default_max": 1,
                                         "rr_entry": "Aspect"},
                             "pool_aspect": "pool"},
              "deckbuilding_overrides": [
                  {"identity": "spider_woman", "aspects": 2,
                   "equal_aspects": True}]}
    assert deckcheck.check_aspects(conn, _deck(aspects=["justice", "leadership"]),
                                   config).ok


def test_an_equal_aspect_identity_needs_the_counts_to_match(tmp_path):
    """Spider-Woman's card caps nothing; it requires an EQUAL number from
    each chosen aspect. An `aspects: 2` check alone passes a deck that is
    14 Justice and 2 Leadership, which her card forbids."""
    conn = _mkdb(tmp_path,
                 [("h1", "Spider-Woman", "hero", "core", None, 1),
                  ("j1", "J", "ally", "core", 3, 3),
                  ("l1", "L", "ally", "core", 3, 3)])
    conn.executemany("UPDATE cards SET faction_code = ? WHERE code = ?",
                     [("justice", "j1"), ("leadership", "l1")])
    conn.execute("INSERT INTO identity_faces (identity_key, code) "
                 "VALUES ('spider_woman', 'h1')")
    conn.commit()
    config = {"deck_rules": {"aspects": {"default_max": 1,
                                         "rr_entry": "Aspect"},
                             "pool_aspect": "pool"},
              "deckbuilding_overrides": [
                  {"identity": "spider_woman", "aspects": 2,
                   "equal_aspects": True}]}
    deck = _deck(hero_code="h1", aspects=["justice", "leadership"],
                 slots={"j1": 3, "l1": 1})
    finding = deckcheck.check_aspects(conn, deck, config)
    assert not finding.ok
    assert "equal" in finding.detail


def test_a_deck_declaring_no_aspect_is_reported_not_assumed(tmp_path):
    conn = _mkdb(tmp_path, [("h1", "Hero", "hero", "core", None, 1)])
    config = {"deck_rules": {"aspects": {"default_max": 1,
                                         "rr_entry": "Aspect"},
                             "pool_aspect": "pool"}}
    finding = deckcheck.check_aspects(conn, _deck(aspects=[]), config)
    assert not finding.ok


def test_unique_matching_runs_only_over_included_cards(tmp_path):
    """The other half of the Sp//dr constraint: `check` must call
    `included` and never `deck.slots`."""
    conn = _mkdb(tmp_path,
                 [("h1", "SP//dr Suit", "hero", "spdr", None, 1),
                  ("s1", "SP//dr Suit", "support", "spdr", 1, 1)],
                 out_of_deck=[("h1", "identity"), ("s1", "permanent")])
    assert deckcheck.check_unique(conn, _deck(hero_code="h1",
                                              slots={"s1": 1})).ok
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_deckcheck.py -k aspect -v`
Expected: FAIL — `AttributeError: module 'mc_jarvis.deckcheck' has no attribute 'check_aspects'`

- [ ] **Step 4: Implement the remaining checks**

Append to `deckcheck.py`:

```python
from pathlib import Path

import yaml

from . import deckrules, identity as identity_mod

CONFIG_PATH = Path(__file__).parent / "_bundled" / "legality.yaml"


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def check_aspects(conn, deck, config) -> Finding:
    """One aspect unless the identity says otherwise.

    The allowance is per-identity and already measured: `deckrules.scan`
    finds the overrides in identity card prose, because `deck_requirements`
    is null on every identity in the data.
    """
    rules = config["deck_rules"]["aspects"]
    entry = rules.get("rr_entry")
    if not deck.aspects:
        return Finding(
            rule="aspects", ok=False, rr_entry=entry,
            detail="the deck declares no aspect, so purity cannot be "
                   "checked - marvelcdb records it in `meta`, not from the "
                   "cards")
    allowed = rules["default_max"]
    key = identity_mod.key_for_code(conn, deck.hero_code)
    override = deckrules.for_identity(conn, config, key) if key else None
    if override and override.get("aspects"):
        allowed = override["aspects"]
    if len(deck.aspects) > allowed:
        return Finding(
            rule="aspects", ok=False, rr_entry=entry,
            detail=f"declares {len(deck.aspects)} aspects "
                   f"({', '.join(deck.aspects)}) and {deck.hero_name} may "
                   f"choose {allowed}")

    # Spider-Woman and Warlock do not merely ALLOW extra aspects: their
    # cards require an equal number of cards from each. Checking the count
    # of aspects alone passes a 14/2 split their own card forbids.
    if override and override.get("equal_aspects") and len(deck.aspects) > 1:
        cards = included(conn, deck)
        if cards:
            marks = ",".join("?" * len(cards))
            per: dict[str, int] = {a: 0 for a in deck.aspects}
            for row in conn.execute(
                    f"SELECT code, faction_code FROM cards "
                    f"WHERE code IN ({marks})", list(cards)):
                if row["faction_code"] in per:
                    per[row["faction_code"]] += cards[row["code"]]
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
    clashes = []
    for i, left in enumerate(codes):
        for right in codes[i + 1:]:
            if identity_mod.matches(conn, left, right):
                clashes.append(f"{left}/{right}")
    return Finding(
        rule="unique", ok=not clashes,
        detail="; ".join(clashes) if clashes else "no unique clashes",
        cards=clashes)


def check(conn, deck, config: dict | None = None) -> list[Finding]:
    """Every rule, in the order §10 requires.

    Exclusion first - `included` is what every later check reads - then
    size, copies, aspects and uniqueness.
    """
    config = config if config is not None else load_config()
    key = identity_mod.key_for_code(conn, deck.hero_code)
    override = deckrules.for_identity(conn, config, key) if key else None
    return [check_size(conn, deck, config),
            check_copies(conn, deck, override),
            check_aspects(conn, deck, config),
            check_unique(conn, deck)]
```

If `identity.key_for_code` does not exist, add it:

```python
def key_for_code(conn, code: str) -> str | None:
    row = conn.execute(
        "SELECT identity_key FROM identity_faces WHERE code = ?",
        (code,)).fetchone()
    return row["identity_key"] if row else None
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_deckcheck.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/mc_jarvis/deckcheck.py src/mc_jarvis/identity.py \
        config/legality.yaml tests/test_deckcheck.py
git commit -m "feat: aspect purity and unique matching, over included cards"
```

---

## Task 5: The regression corpus

§10's only stated mitigation for `legality.yaml`. **This task is the reason `deck check` can be trusted at all.**

**Files:**
- Modify: `src/mc_jarvis/deckfetch.py`
- Create: `tools/deck_corpus.py`
- Test: `tests/test_deckcheck.py`

**Interfaces:**
- Produces: `deckfetch.corpus_path()`, `deckfetch.build_corpus(days) -> dict`

- [ ] **Step 1: Write the corpus builder**

```python
# tools/deck_corpus.py
"""Fetch published decklists as a regression corpus for `legality.yaml`.

    uv run python tools/deck_corpus.py --days 30

FETCHED DATA. It lands under `data/` (gitignored) and never under
`tests/`. The policy gate does not cover `tests/`, so this one is on the
author rather than the checker.

`by_date` returns complete decks - the same keys as the single-deck
endpoint - so this costs one request per day, not one per deck.
"""
import argparse
import datetime as dt
import json

from mc_jarvis import deckfetch, paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--end", default=None,
                        help="last day to fetch (default: yesterday)")
    args = parser.parse_args()

    end = (dt.date.fromisoformat(args.end) if args.end
           else dt.date.today() - dt.timedelta(days=1))
    out = paths.data_dir() / "decks"
    out.mkdir(parents=True, exist_ok=True)

    total = 0
    for offset in range(args.days):
        day = (end - dt.timedelta(days=offset)).isoformat()
        target = out / f"{day}.json"
        if target.exists():
            continue
        decks = deckfetch.fetch_by_date(day)
        target.write_text(json.dumps(decks), encoding="utf-8")
        total += len(decks)
        print(f"{day}: {len(decks)}")
    print(f"{total} decks into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add the corpus reader to `deckfetch.py`**

```python
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
```

- [ ] **Step 3: Fetch the corpus**

```bash
uv run python tools/deck_corpus.py --days 30
```

Expect roughly **25–35 decks per day**, so 750–1,000 decks.

- [ ] **Step 4: Write the gate**

```python
# tests/test_deckcheck.py — append
@pytest.mark.integration
def test_published_decks_are_overwhelmingly_legal(real_index):
    """§10's only mitigation for the highest-risk file in this project.

    Published decks are overwhelmingly legal, so a meaningful rejection
    rate means `legality.yaml` is wrong, not that the decks are.

    DO NOT raise this threshold to make the test pass. Read the
    rejections: the first run's failures are findings. `problem` is not
    exposed on the public endpoint, so this is a statistical signal and
    not per-deck ground truth - which is exactly why the number has to be
    argued for rather than observed.
    """
    from mc_jarvis import deckfetch

    decks = list(deckfetch.corpus())
    if len(decks) < 200:
        pytest.skip("no corpus; run `uv run python tools/deck_corpus.py`")

    checked = rejected = 0
    reasons = {}
    for payload in decks:
        try:
            deck = deckfetch.normalise(real_index, payload, source="corpus")
        except deckfetch.DeckError:
            continue          # a hero marvelsdb does not carry yet
        if deck.unknown:
            continue          # card data behind marvelcdb, not a rules bug
        checked += 1
        for finding in deckcheck.check(real_index, deck):
            if not finding.ok:
                rejected += 1
                reasons[finding.rule] = reasons.get(finding.rule, 0) + 1
                break

    rate = rejected / checked
    assert rate <= 0.05, (
        f"{rejected}/{checked} = {rate:.1%} of published decks rejected, "
        f"by rule: {reasons}. Read them before touching this number.")
```

- [ ] **Step 5: Run the gate and read every rejection**

```bash
uv run pytest tests/test_deckcheck.py -m integration -k published -v
```

**This step is the task.** The first run will reject decks. For each rule in `reasons`, print ten examples and read them:

```bash
uv run python -c "
from mc_jarvis import index, paths, deckfetch, deckcheck
conn = index.connect(paths.db_path())
shown = 0
for payload in deckfetch.corpus():
    try: deck = deckfetch.normalise(conn, payload, source='c')
    except deckfetch.DeckError: continue
    if deck.unknown: continue
    bad = [f for f in deckcheck.check(conn, deck) if not f.ok]
    if bad and shown < 10:
        shown += 1
        print(deck.id, deck.hero_name, deck.aspects,
              [(f.rule, f.detail[:80]) for f in bad])
"
```

**A rejection is a bug in `legality.yaml`, a missing `deckbuilding_overrides` entry, or a `format` you did not filter — until you have read it and shown otherwise.** Do not raise 0.05 to make the suite green. Record what each rejection turned out to be in the spec.

- [ ] **Step 6: Commit**

```bash
git add tools/deck_corpus.py src/mc_jarvis/deckfetch.py tests/test_deckcheck.py
git commit -m "feat: the published-decklist regression corpus for legality.yaml"
```

---

## Task 6: Deck statistics

**Files:**
- Create: `src/mc_jarvis/deckstats.py`
- Test: `tests/test_deckstats.py`

**Interfaces:**
- Consumes: `deckcheck.included`
- Produces: `deckstats.profile(conn, deck) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deckstats.py
import pytest

from mc_jarvis import deckcheck, deckfetch, deckstats, index


def _mkdb(tmp_path, cards, out_of_deck=()):
    """cards: (code, name, type, cost, phys, mental, energy, wild, qty)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, cost, resource_physical, "
        "resource_mental, resource_energy, resource_wild, deck_limit, "
        "quantity, pack_code, canonical_code, is_reprint, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 3, ?, 'core', ?, 0, '{}')",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[0])
         for c in cards])
    conn.executemany(
        "INSERT INTO out_of_deck (code, mechanism, note) VALUES (?, ?, NULL)",
        out_of_deck)
    conn.commit()
    return conn


def _deck(**kw):
    base = {"name": "D", "hero_code": "h1", "hero_name": "H",
            "aspects": ["justice"], "slots": {}}
    base.update(kw)
    return deckfetch.Deck(**base)


def test_the_cost_curve_is_copy_weighted(tmp_path):
    """Three copies of a 1-cost card are three cards at cost 1, not one.
    A curve over distinct rows is not the curve the player draws from."""
    conn = _mkdb(tmp_path, [("a1", "Cheap", "ally", 1, 1, 0, 0, 0, 3),
                            ("a2", "Dear", "ally", 4, 0, 1, 0, 0, 2)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "a2": 2}))
    assert got["cost_curve"] == {1: 3, 4: 2}
    assert round(got["mean_cost"], 2) == round((3 * 1 + 2 * 4) / 5, 2)


def test_a_resource_card_with_no_cost_is_not_cost_zero(tmp_path):
    """A card with a null cost has no cost, which is different from
    costing nothing. Folding it in as 0 drags the mean down."""
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3),
                            ("r1", "Resource", "resource", None,
                             0, 0, 0, 1, 3)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "r1": 3}))
    assert got["cost_curve"] == {2: 3}
    assert got["no_cost"] == 3
    assert round(got["mean_cost"], 2) == 2.0


def test_out_of_deck_cards_do_not_skew_the_curve(tmp_path):
    """§10 says this explicitly: the exclusions apply to `deck stats` as
    well as `deck check`. A permanent upgrade in the curve describes a
    deck the player never shuffles."""
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3),
                            ("p1", "Claws", "upgrade", 0, 0, 0, 0, 0, 1)],
                 out_of_deck=[("p1", "permanent")])
    got = deckstats.profile(conn, _deck(slots={"a1": 3, "p1": 1}))
    assert got["cost_curve"] == {2: 3}
    assert got["size"] == 3


def test_the_resource_mix_is_copy_weighted_too(tmp_path):
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3}))
    assert got["resources"]["physical"] == 3


def test_every_number_names_its_cards(tmp_path):
    conn = _mkdb(tmp_path, [("a1", "Ally", "ally", 2, 1, 0, 0, 0, 3)])
    got = deckstats.profile(conn, _deck(slots={"a1": 3}))
    assert got["by_type"]["ally"]["cards"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_deckstats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.deckstats'`

- [ ] **Step 3: Write `deckstats.py`**

```python
"""Deck shape (spec §10).

Reads `deckcheck.included`, never `deck.slots`. §10 requires it: a
permanent upgrade left in the cost curve describes a deck the player never
shuffles, and the exclusion rules exist precisely so both commands see the
same cards.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .deckcheck import included

RESOURCES = ("physical", "mental", "energy", "wild")


def profile(conn, deck) -> dict:
    cards = included(conn, deck)
    if not cards:
        return {"size": 0, "cost_curve": {}, "mean_cost": 0.0, "no_cost": 0,
                "resources": {}, "by_type": {}, "aspects": deck.aspects}

    marks = ",".join("?" * len(cards))
    rows = [dict(r) for r in conn.execute(
        f"SELECT code, name, type_code, cost, resource_physical, "
        f"resource_mental, resource_energy, resource_wild FROM cards "
        f"WHERE code IN ({marks})", list(cards))]

    curve: Counter = Counter()
    resources: Counter = Counter()
    by_type: dict[str, dict] = defaultdict(
        lambda: {"copies": 0, "cards": []})
    no_cost = cost_total = costed = 0

    for row in rows:
        copies = cards[row["code"]]
        if row["cost"] is None:
            # No cost is not a cost of zero. Resources and some upgrades
            # have none, and folding them in as 0 drags the mean down.
            no_cost += copies
        else:
            curve[row["cost"]] += copies
            cost_total += row["cost"] * copies
            costed += copies
        for name in RESOURCES:
            resources[name] += (row[f"resource_{name}"] or 0) * copies
        entry = by_type[row["type_code"]]
        entry["copies"] += copies
        entry["cards"].append({"code": row["code"], "name": row["name"],
                               "quantity": copies})

    return {
        "aspects": deck.aspects,
        "size": sum(cards.values()),
        "cost_curve": dict(sorted(curve.items())),
        "mean_cost": (cost_total / costed) if costed else 0.0,
        "over": costed,
        "no_cost": no_cost,
        "resources": {k: v for k, v in resources.items() if v},
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_deckstats.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Gate against a real deck**

```bash
uv run python -c "
import json
from mc_jarvis import index, paths, deckfetch, deckstats
conn = index.connect(paths.db_path())
deck = next(iter(deckfetch.corpus()))
d = deckfetch.normalise(conn, deck, source='gate')
p = deckstats.profile(conn, d)
print(d.hero_name, d.aspects, 'size', p['size'])
print('curve', p['cost_curve'], 'mean', round(p['mean_cost'], 2))
print('resources', p['resources'])
"
```

**Gate.** `size` must be **at least 40** for any published deck, and the cost-curve values must sum to `size - no_cost`. A curve that does not reconcile with the size means the exclusion set differs between the two, which is the bug this shared-`included` design exists to prevent.

- [ ] **Step 6: Commit**

```bash
git add src/mc_jarvis/deckstats.py tests/test_deckstats.py
git commit -m "feat: deck cost curve, resource mix and type breakdown"
```

---

## Task 7: The CLI and the skill

**Files:**
- Modify: `src/mc_jarvis/cli.py`, `src/mc_jarvis/deckfetch.py`, `src/mc_jarvis/collection.py`, `skill/mc-jarvis/SKILL.md`
- Test: `tests/test_cli.py`, `tests/test_skill_install.py`

**Interfaces:**
- Produces: `deckfetch.handle(args)`, `collection.handle(args)`

- [ ] **Step 1: Wire the parser**

```python
    deck_p = _leaf(sub, "deck", "import, validate and describe a deck")
    deck_sub = deck_p.add_subparsers(dest="deck_cmd", required=True)
    for verb, help_ in (("fetch", "normalise a deck"),
                        ("check", "legality, rule by rule"),
                        ("stats", "curves, mixes, densities")):
        leaf = _leaf(deck_sub, verb, help_)
        leaf.add_argument("deck",
                          help="a marvelcdb id, a marvelcdb URL, or a file")
```

and in `_dispatch`:

```python
    if name == "deck":
        from . import deckfetch
        return deckfetch.handle(args)
```

- [ ] **Step 2: Write the handler**

```python
def handle(args) -> int:
    from .cards import _open
    from .cli import emit

    conn = _open()
    try:
        deck = fetch(conn, args.deck)
    except DeckError as exc:
        print(f"mc-jarvis deck: {exc}")
        return 1
    except OSError as exc:
        print(f"mc-jarvis deck: cannot reach marvelcdb ({exc}).")
        return 1

    if args.deck_cmd == "fetch":
        payload = {"name": deck.name, "hero": deck.hero_name,
                   "aspects": deck.aspects, "format": deck.deck_format,
                   "slots": deck.slots, "unknown": deck.unknown}
        emit(payload, as_json=args.json)
        return 0

    if args.deck_cmd == "stats":
        from . import deckstats

        emit(deckstats.profile(conn, deck), as_json=args.json)
        return 0

    from . import deckcheck

    findings = deckcheck.check(conn, deck)
    if args.json:
        emit({"deck": deck.name, "hero": deck.hero_name,
              "legal": all(f.ok for f in findings),
              "findings": [vars(f) for f in findings]}, as_json=True)
        return 0 if all(f.ok for f in findings) else 1

    print(f"{deck.name} - {deck.hero_name}, "
          f"{'/'.join(deck.aspects) or 'no aspect declared'}")
    for finding in findings:
        mark = "ok  " if finding.ok else "FAIL"
        print(f"  {mark} {finding.rule}: {finding.detail}")
        if finding.rr_entry:
            print(f"       see: mc-jarvis rules show {finding.rr_entry!r}")
    return 0 if all(f.ok for f in findings) else 1
```

- [ ] **Step 3: Teach the skill**

Add to `SKILL.md`'s command table:

```markdown
| import a deck | `mc-jarvis deck fetch <id-or-url-or-file>` |
| is this deck legal | `mc-jarvis deck check <deck>` |
| what shape is this deck | `mc-jarvis deck stats <deck>` |
| packs you own | `mc-jarvis collection set <pack>...` / `collection show` |
```

and a section:

```markdown
## Decks

`deck check` reports rule by rule, and names the Rules Reference entry
behind each one — run `mc-jarvis rules show <entry>` for the wording,
which comes from the player's own rulebook.

Four things to carry into any answer:

- **A failing size check may not be the player's fault.** If the deck
  names cards this index does not carry, `deck check` says so and calls
  the count a floor. Say that rather than telling them to add cards.
- **Out-of-deck cards are not in the deck.** Permanents, `hero_special`
  decks, and the handful the data does not mark at all — Rogue's Touched,
  Valkyrie's Death-Glow — are excluded from size, limits and every curve.
  A player asking "why does it say 40 when I have 41 cards" is asking
  about this.
- **`--owned` filters over printings, not packs.** Owning any printing of
  a card is owning the card, so a reprint in a pack they own counts.
- **`deck check` reports; it does not coach.** Turning "3 cards over
  curve, 2 answers to Guard" into "cut a Tackle" is your job.
```

- [ ] **Step 4: Run everything**

```bash
uv run pytest -q -m "not integration"
uv run pytest -q -m integration
uv run python -m mc_jarvis.policy
uv run mc-jarvis deck fetch 64331
uv run mc-jarvis deck check 64331
uv run mc-jarvis deck stats 64331
uv run mc-jarvis collection set core
uv run mc-jarvis collection show
```

Expected: the suite passes, the policy check is clean, and deck 64331 (a Nova Justice deck, 40+ cards) fetches, validates and profiles.

- [ ] **Step 5: Commit**

```bash
git add src/mc_jarvis/ skill/ tests/
git commit -m "feat: mc-jarvis deck fetch/check/stats and collection"
```

---

## Done criteria

- [ ] `uv run pytest -q` passes, unit and integration
- [ ] `uv run python -m mc_jarvis.policy` clean — no rulebook prose in the new `deck_rules`
- [ ] `mc-jarvis deck check` on the corpus rejects **≤ 5%** of non-legacy published decks, and every rejection in the first run has been read and explained in the spec
- [ ] Owning every pack selects every card; owning only `core` selects strictly fewer and more than zero
- [ ] A deck naming an unindexed card reports it rather than shrinking
- [ ] Sp//dr passes her own legality check
- [ ] `01043a`–`01043d` count as five cards, not one
- [ ] `git status` clean; `data/decks/` untracked

## Deliberately not in this plan

- **`assess --deck`** (assess spec §9) — consumes `Deck`, lands next.
- **Warlock's `off_aspect_allowance` and Cable's side-scheme allowance** — both are already recorded in `deckbuilding_overrides` with digests, and both need a rule that counts cards by faction against a cap. `equal_aspects` is implemented because Spider-Woman is common in the corpus; if the corpus gate in Task 5 rejects a Warlock or Cable deck, that rejection is the task that adds these.
- **Signature-set auto-inclusion** — marvelcdb decks already carry signature cards in `slots`, so there is nothing to infer. If a deck is ever found missing them, that is a finding and a task, not an assumption to code against now.
- **`ignoreDeckLimitSlots`** — present on every deck and null on all 124 sampled. Parsed and carried; no rule reads it until a deck is found that uses it.
- **Deck coaching** — Phase 2, and a `SKILL.md` recipe rather than a command.
