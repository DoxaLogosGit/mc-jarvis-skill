# mc-jarvis Phase 1 (Vertical Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runnable spine of mc-jarvis — install, bootstrap from live sources, index into SQLite, and answer card, identity, encounter, and rules questions with citations — so that real data can reveal the gaps this design has not yet found.

**Architecture:** A normal Python package exposing a `mc-jarvis` CLI over a local SQLite+FTS5 index. Copyrighted content is fetched to the user's machine at init time and never committed. Everything deterministic lives below the CLI line; the host model only supplies judgement, via a skill file that teaches it these commands.

**Tech Stack:** Python 3.10+, stdlib `sqlite3` (FTS5), `argparse`, `urllib`, `tarfile`; `pypdf` and `PyYAML` as the only third-party dependencies; `pytest` for tests; `uv` for install and dev.

**Spec:** `docs/superpowers/specs/2026-08-20-mc-jarvis-design.md` — read it alongside this plan. Every task cites the spec section it implements.

**Scope boundary.** This plan is Phase 1's spine only. Deliberately **out of scope**, to be planned after this slice has been exercised against real data: `deck fetch` / `deck check` / `deck stats`, the full `config/legality.yaml`, `collection set/show` and `--owned` filtering, and the decklist regression corpus. This plan ships only the minimal `legality.yaml` the setup audit needs (Task 8). Phase 2 (coaching, `team`, `mcp`) and Phase 3 (`meta`, build-from-scratch) are separate plans.

**First testable checkpoint is Task 5** — after it, `mc-jarvis card search` answers real queries against the whole card corpus. Stop and exercise it before continuing.

**Task 17 is an addition to the spec, not an implementation of it.** The timing reference — trigger ordering and the game round — was requested after the spec was approved. It is placed last because it depends on both the rules index (Task 13) and card-text parsing (Task 9), but it is independent of Tasks 6–12 and could move earlier if it is wanted sooner.

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include this section.

- **Python 3.10+.** `X | Y` type syntax is permitted; nothing newer is used. Do not raise the floor.
- **Exactly two runtime dependencies: `pypdf` and `PyYAML`.** Both are pure-Python wheels. Adding a third requires changing the spec first.
- **HTTP uses stdlib `urllib`.** No `requests`, no `httpx`.
- **No system packages.** `uv tool install mc-jarvis` must be the whole story on Linux, macOS, and Windows. `poppler-utils`, `git`, and `playwright` are optional and every code path must work without them.
- **The repository ships code and configuration only.** No card text, no rules text, no PDFs, no built index, no cached decklists. Never commit anything fetched at runtime. `data/`, `*.sqlite`, and `*.pdf` are gitignored — verify before every commit.
- **Every command supports `--json`** and a compact human-readable default.
- **Every subcommand takes an explicit verb.** No parent command takes a bare positional (`card show Vision` must not parse `show` as a query).
- **Every rules answer cites the entry name and page.**
- **Test fixtures are hand-invented and contain no FFG text.** Tests that need the real corpus are integration tests, skipped when the index is absent.
- **Shape every fixture from observed data, never from an assumption about it.** Before writing a fixture that mimics an external format, look at the real thing and copy its shape. This rule exists because it was broken: the Task 13 `See also` fixture used `See also:` while the Rules Reference prints `See also :` with a space. The test passed and the feature had never worked — a fixture built to match the assumption cannot fail the assumption.
- **A task's real-data check is a gate, not a closing flourish.** Every task whose fixture encodes an assumption about external data ends by running against the real source, with a numeric threshold. "Expected: a small number" is not a threshold. If a check has no number you can fail, it is not checking anything.

## Verified findings this plan adds to the spec

Confirmed by direct inspection on 2026-08-21, while planning. These supersede or sharpen §9, §10 and §16.

**Seven heroes override the normal deckbuilding rules, and nothing structural marks them.** `deck_requirements` is null on every identity, so the only evidence is prose on the alter-ego card. Scanning identity text for composition language (as opposed to the 42 faces that merely *search* the deck) returns exactly seven, verified 2026-08-22:

| Identity | Override |
|---|---|
| Spider-Woman | Two aspects instead of one, in equal numbers |
| Adam Warlock | All four aspects in equal numbers, **and** max 1 copy of any non-signature card |
| Cable | Player side schemes from any aspect |
| Cyclops | X-MEN allies from any aspect |
| Wonder Man | Events with a printed energy icon from any aspect |
| Gamora | Up to 6 attack/thwart events off-aspect (cap on the total, not per trait) |
| Maria Hill | 3 S.H.I.E.L.D. supports off-aspect — the cap is on **distinct titles**, each at full copy count |

Two of these are not simple allowances and the deck validator must not treat them as such: Spider-Woman and Adam Warlock change the *aspect count itself* and impose an equality constraint, and Warlock additionally caps every non-signature card at 1 copy, overriding `deck_limit` downward.

`deckrules.scan` finds them, `config/legality.yaml` encodes what each means, and `deckrules.check` fails the build when a scanned identity has no entry **or** when an entry's quote no longer appears in the card text. Both directions matter: a new release adding an override would otherwise be validated against the wrong rules silently, and a reworded card would leave a stale rule in force. This is the same shape as the setup audit, for the same reason — a hand-maintained list does not converge.

**Copy limits stated in card text: `deck_limit` is authoritative, and scraping the text is the bug.** Measured 2026-08-22:

| Phrase | Cards | What `deck_limit` says |
|---|---|---|
| "Max N per deck" | 255 printings | Agrees with the stated N on **every one** |
| "Max N per player" | 80 cards | **3** — it is an in-play limit, not a deck limit |
| unique (star icon) | 653 | Always 1; zero exceptions |

So the structured fields already carry every deckbuilding limit, and the star icon needs no separate rule. **The danger runs the other way**: a validator that reads "Max 1" out of card text and applies it as a deck limit rejects 80 legal cards, each of which may legitimately appear three times.

`cardtext.build_limits` therefore does two separate things. It **verifies** stated per-deck limits against `deck_limit` and raises `LimitMismatch` on any disagreement — turning a measurement into a standing check, so if the field ever stops being trustworthy the build says so. And it records in-play and use limits in `play_limits`, which `deck check` must never consult: 110 cards are "max 1 per player", 50 "limit once per round", plus scopes for ally, minion, character, enemy and scheme. `card show` prints deck limit and play limits as separate lines for the same reason.

**Unique-matching has four scopes, not one, and the spec only describes the first.** §8 quotes RR p.45's deckbuilding sentence and stops there. Read in full (RR p.45-46, verified 2026-08-22), the rule governs four different situations with different answers:

| Scope | Rule | Effect |
|---|---|---|
| Deckbuilding | No matching cards in one deck, identity included | Enforced |
| Identity selection | "players cannot choose identities that match" at setup | Enforced across players |
| Entering play | "A non-villain card in an out-of-play state that matches a card in play cannot enter play" | Enforced across the **whole table** |
| Scenario choice | "players may choose a scenario even if one or more villains match one or more chosen identities" | **Explicitly permitted** |

Three consequences the deck and team plans must carry:

- **The play scope spans every player.** If the Nebula identity is in play, Gamora's signature Nebula ally cannot enter play — from any deck. `identity.blocks_entering_play` answers this and is what `team` should use.
- **Villains are exempt in both directions.** A Nebula player may face the Nebula villain. Reporting that as an error would be wrong; `identity.villain_matches_identity` exists to surface it as a note.
- **There is a remedy the tool should offer.** RR Appendix I (p.50): a player whose identity-specific card matches another player's chosen identity "may replace the matching card in their deck with a card with the Team-Up keyword that names both their own identity and the other player's identity." So the Gamora/Nebula collision has a legal fix, and `team` should suggest it rather than just reporting a conflict.

**The alter-ego title decides cases that look identical.** Clause one fires only when **both** cards have no subtitle and no alter-ego title. So the Jessica Jones identity matches the Jessica Jones minion (her alter-ego is also Jessica Jones), while the Daredevil identity does **not** match the Daredevil minion (his is Matt Murdock) — same card types, opposite answers. Equally, Daredevil "Matt Murdock" is illegal in a Daredevil deck while the plain Daredevil ally is legal, because nothing on it says Matt Murdock.

**Villains do not thwart, and their printed hit points are not their real hit points.** Task 10's draft schema had no `scheme`, `stage` or `health_per_hero` column, so `encounter` printed `THW None` for every villain. Villains carry `scheme` (Rhino 1 at every stage), `stage` as a roman numeral, and `health_per_hero: true` — the printed 14/15/16 is multiplied by the player count. Reporting the printed number without saying so gives a table the wrong tracker value, so both the encounter listing and `card show` state it.

**Card-text markup has four shapes, not one, and three of them break a naive cost-arrow parse.** Found while implementing Task 9 against real cards:

- The colon usually sits **outside** the bold span — `<b>Interrupt</b>: When …` — not inside it. Leaving it in front of the timing clause blocks the match and reports the whole trigger as a cost. Measured: timing extraction rose from **24 to 281** player clauses once the colon was stripped. Both `<b>Hero Action:</b>` and `<b>Hero Action</b>:` occur, so the parser must handle either.
- A **basic-power qualifier** follows the ability type on 85 clauses — `<b>Hero Interrupt</b> <i>(defense)</i>:` — naming which power the ability attaches to. It appears with the emphasis tags both outside the parentheses and inside them (`(<i>attack</i>)`). It is captured, not discarded: `attack` 47, `thwart` 24, `defense` 11, plus three combined forms.
- Some triggers state **no cost at all**: `<b>Hero Response</b>: After your hero defends … → discard this card.` There is no comma, because there is nothing to pay. Treating the trigger as a cost tells the player to pay for something free.

The fixture originally encoded the colon inside the tag — an assumption, not the data — and the leak test anchored on `cost LIKE 'When %'`, so `": When …"` slipped past both. This is the same failure the Task 13 `See also` bug produced, and the reason for the fixture-shape constraint in Global Constraints.

**"Player-legal" is not `faction_code != 'encounter'`.** That expression counts 2,154 cards; §16's figure is 1,607. The difference is `campaign` (146 cards, 46 arrow clauses), which belongs to a campaign's own pool rather than a constructed deck. `index.PLAYER_FACTIONS` names the seven that are deck-relevant, and the deck plan should use it rather than re-deriving the exclusion.

**Spec §10's Sp//dr ordering constraint does not exist.** §10 states that Sp//dr's hero face and her permanent support share a title, so unique-match "would reject the deck" unless out-of-deck classification runs first. Verified 2026-08-22 on real data: `31001a` carries title *SP//dr Suit* and alter-ego title *Peni Parker*; `31001b` carries the title alone. RR p.45's first clause fires only when **both** cards have no subtitle and no alter-ego title, so **they do not match**. §10's constraint is an artifact of implementing matching as name equality — which §8 warns against three paragraphs earlier. The two sections contradict each other, and implementing the rule correctly dissolves the problem. Exclusion still runs before matching, because deck-size and curve math need it, but that is not what makes Sp//dr legal.

**Coverage in the setup audit must be an explicit acknowledgment, not an inference.** An earlier draft treated "this identity's set contains some `permanent` card" as coverage. A hero with *both* a permanent card and an unmarked set-aside card is then silently passed — and the unmarked one is exactly what the audit exists to catch. Real data hides this, because neither `rogue` nor `valk` contains any permanent card; a fixture built to have both caught it. `legality.yaml` now lists all eight flagged identities explicitly, and each stated reason is re-verified against the data at build time so an acknowledgment cannot outlive the fact it rests on.

**`duplicate_of` is NOT encounter-only, and the spec's reprint model is inverted.** §8 and §16 state that all 342 cards carrying `duplicate_of` are encounter cards, that no player card uses it, and that player-side reprints are "detectable only by name+type+faction". Measured 2026-08-22: **351 cards carry it and 341 resolve to player cards** — 211 to `basic` alone. They are hero-pack reprints of core-set cards, and `duplicate_of` is exactly how player-side reprints are marked.

Each such row is a stub: a code, a pack, a quantity, a position, and nothing else — no name, no text. Every one resolves in a single hop, none chain, and no card carries `duplicate_of` alongside a name of its own. Task 4 fills them in from the card they duplicate, keeping each stub's own code, pack, quantity and position because those belong to the printing rather than the card, and records `canonical_code` so printings can be collapsed. Leaving them unresolved gives 351 nameless rows and breaks collection lookups: owning the Ant-Man pack would not tell you that you own *First Aid*.

**`deck_limit <= quantity` does not hold per printing.** §10 asserts zero violations and concludes that owning any pack containing a card gives you enough copies to play it to its limit. After reprint resolution there are **50 violations** — the Ant-Man pack ships 2 *First Aid* against a limit of 3. What holds with zero violations is the grouped form: every card has *some* printing with at least `deck_limit` copies. Task 4 asserts the per-printing rule on original printings only, and the grouped rule on everything.

The consequence for the collection work in the next plan: ownership is binary per *card*, but only because the printing carrying a full set of copies is usually one a player already owns. It is not a licence to treat every printing as sufficient, and `--owned` must resolve through `canonical_code`.

**The corpus has moved since the spec was written.** It now holds **4,379 cards** (2,154 player-legal after reprint resolution) (§16 says 4,298) across **69 identities** grouped by `set_code` (§16 says 72 heroes). Test tolerances in this plan are ranges, not exact counts, for that reason — do not tighten them to today's numbers.

**The setup audit flags eight identities, not four.** Spec §10's table lists Bobby Drake, Riri Williams, Rogue and Brunnhilde. Running the patterns in this plan's `SETUP_PATTERNS` also returns Matt Murdock, Stephen Strange, Hercules, and Ororo Munroe, all via `begins the game with`. All eight are coverable; see Task 8.

**A `hero_special` set is a different set from its identity's**, so it cannot be found by `set_code` — identity `iceman` pairs with set `iceman_frostbite`. Pack code is the reliable join: verified exact for all six hero_special sets, matching nothing else.

**The Rules Reference has no timing entry.** `Timing` is a redirect pointing at four other entries, and trigger-priority rules are spread across `Forced` (p.20), `Interrupt` (p.25), `Response` (p.38), `First Player` (p.20), `Simultaneous Resolution` (p.40) and three `When …` entries (p.48). The closest thing to a reference table is the **Round Overview on p.4** — ten numbered steps, each naming the glossary entries that govern it, which parses cleanly into a table. Task 17 assembles both.

**`When Revealed`, `When Defeated` and `When Completed` are each defined by the RR as equivalent to a `Forced Interrupt`.** They are aliases, not separate priority tiers — which is why the ladder has six rungs rather than nine.

**A bold prefix is not always a timing trigger, and a trigger is not always the whole prefix.** 112 distinct bold prefixes appear in card text. `Boost` (428 occurrences), `Contents`, `Preparation` and the mode markers are bold text with no trigger semantics, while `Hero Action` (573), `Alter-Ego Action` (151) and `Hero Interrupt` (150) are a **form qualifier plus a trigger** and must be split. `When Revealed (Hero)` puts the qualifier in parentheses instead.

**Appendix VI defines Game Environments** — Current, Legacy and Limited — which is what marvelcdb's `format` field encodes. §10 notes `format: "legacy"` as a corpus-filtering concern; the RR is where the term is defined, and the deck-pipeline plan should read that appendix before encoding aspect and card-pool rules.

**Valkyrie's set code is `valk`, not `valkyrie`.** Touched is `38002` (set `rogue`); Death-Glow is `25002` (set `valk`). Neither carries `permanent`, and neither set contains any permanent card — so nothing but a config entry can cover them.

- **The Rules Reference carries its own index on PDF pages 2–3**, and it is authoritative: 216 entries with page numbers, plus 46 `See …` redirects. This replaces the spec's ALL-CAPS-regex-with-reconciliation approach as the primary entry list. An independent alphabetical-monotonicity filter over the body headers yields ~215 entries, cross-validating the count.
- **All 13 private-use icon codepoints used in the RR body are named by that index** (`Mental Resource (<glyph>)`, `Amplify Icon (<glyph>)`, …), so `config/glyphs.yaml` is **derived and human-reviewed, not hand-authored**. Zero body glyphs are unmapped.
- **The glyph range is U+F520–U+F531, not U+F520–F530** as §9 and §16 state. U+F531 is the Unique icon. U+F523 and U+F529–U+F52C do not appear.
- The naive ALL-CAPS regex yields 386 candidates over 71 pages; the glossary spans PDF pages 4–49 (`ABILITY` … `YOU, YOUR`). Body headers are a **cross-check** on the index, not the source of truth.
- Two known index-parse artifacts to handle: two-column merge can join adjacent entries (`Variable` + `You, Your` → `Variable You, Your`), and the `Unique Icon` entry picks up bleed from its predecessor (`Activation) Unique Icon`).

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, deps, `mc-jarvis` console script |
| `src/mc_jarvis/paths.py` | Data-directory resolution; nothing else |
| `src/mc_jarvis/cli.py` | argparse tree, `--json` emission, dispatch. No logic. |
| `src/mc_jarvis/doctor.py` | Runtime prerequisite checks |
| `src/mc_jarvis/sources.py` | Card-data tarball fetch and extract |
| `src/mc_jarvis/schema.py` | SQL DDL as a single string constant |
| `src/mc_jarvis/index.py` | Index build: load packs, populate tables, assert invariants |
| `src/mc_jarvis/identity.py` | Identity grouping and unique-match key computation |
| `src/mc_jarvis/outofdeck.py` | Out-of-deck classification and the setup audit |
| `src/mc_jarvis/cardtext.py` | Card-text parsing: `[[traits]]`, keywords, cost arrow |
| `src/mc_jarvis/cards.py` | Card, identity, and encounter queries |
| `src/mc_jarvis/manifest.py` | FFG product-page HTML → rules manifest |
| `src/mc_jarvis/pdf.py` | PDF download and text extraction backends |
| `src/mc_jarvis/rules_chunk.py` | RR index parse, glyph mapping, entry and page chunkers |
| `src/mc_jarvis/rules.py` | Rules queries: `show`, `search`, card↔rules links |
| `src/mc_jarvis/init.py` | `init` orchestration |
| `src/mc_jarvis/update.py` | `update` and `status` |
| `src/mc_jarvis/skill_install.py` | `install-skill`: detect, place, report |
| `src/mc_jarvis/timing.py` | Trigger ordering, the round structure, and citation verification |
| `config/legality.yaml` | Minimal: out-of-deck exceptions only (grows in the next plan) |
| `config/timing.yaml` | The trigger ladder, each rung carrying the RR phrase that establishes it |
| `config/glyphs.yaml` | Derived glyph → token mapping |
| `skill/mc-jarvis/SKILL.md` | The agent brief |
| `tests/fixtures/` | Hand-invented cards and rules text; no FFG content |

`cardtext.py` is deliberately separate from `cards.py`: text parsing is build-time enrichment with its own dense test surface, while `cards.py` is query-time. They change for different reasons.

---

## Task 1: Package scaffold, data paths, and the CLI seam

Implements §5, §5.1, §6. This task locks two things that are expensive to retrofit: the `--json` seam and the explicit-verb argparse structure.

**Files:**
- Create: `pyproject.toml`, `src/mc_jarvis/__init__.py`, `src/mc_jarvis/paths.py`, `src/mc_jarvis/cli.py`
- Test: `tests/test_paths.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `paths.data_dir() -> pathlib.Path` — resolves `$MC_JARVIS_DATA` → `$XDG_DATA_HOME/mc-jarvis` → `~/.local/share/mc-jarvis`. Does not create.
  - `paths.ensure_data_dir() -> pathlib.Path` — creates it (with `marvelsdb/`, `rules/pdf/`, `rules/txt/`) and returns it.
  - `paths.db_path() -> pathlib.Path` — `data_dir() / "mc.sqlite"`
  - `cli.build_parser() -> argparse.ArgumentParser`
  - `cli.emit(payload: object, as_json: bool) -> None` — prints JSON when `as_json`, else a human line-oriented rendering
  - `cli.parse_args(argv) -> argparse.Namespace` — parses **and normalises subcommand aliases**; use this rather than `build_parser().parse_args`
  - `cli.main(argv: list[str] | None = None) -> int` — process exit code

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paths.py
import os
from pathlib import Path
from mc_jarvis import paths


def test_explicit_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path / "custom"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.data_dir() == tmp_path / "custom"


def test_xdg_used_when_no_explicit_var(monkeypatch, tmp_path):
    monkeypatch.delenv("MC_JARVIS_DATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.data_dir() == tmp_path / "xdg" / "mc-jarvis"


def test_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("MC_JARVIS_DATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.data_dir() == Path.home() / ".local" / "share" / "mc-jarvis"


def test_ensure_creates_subdirectories(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path / "d"))
    root = paths.ensure_data_dir()
    assert (root / "marvelsdb").is_dir()
    assert (root / "rules" / "pdf").is_dir()
    assert (root / "rules" / "txt").is_dir()
```

```python
# tests/test_cli.py
import json
import pytest
from mc_jarvis import cli


def test_card_show_does_not_swallow_verb_as_query():
    """`card show Vision` must parse `show` as the verb, not as a search query."""
    args = cli.build_parser().parse_args(["card", "show", "Vision"])
    assert args.card_cmd == "show"
    assert args.name == "Vision"


def test_card_search_takes_its_query():
    args = cli.build_parser().parse_args(["card", "search", "web"])
    assert args.card_cmd == "search"
    assert args.query == "web"


def test_json_flag_available_on_every_leaf_command():
    parser = cli.build_parser()
    for argv in (
        ["doctor"],
        ["status"],
        ["card", "search", "x"],
        ["card", "show", "x"],
        ["identity", "x"],
        ["encounter", "x"],
        ["rules", "show", "x"],
        ["rules", "search", "x"],
    ):
        assert parser.parse_args(argv + ["--json"]).json is True, argv


def test_hero_is_an_alias_for_identity():
    args = cli.parse_args(["hero", "Spider-Man"])
    assert args.command == "identity"
    assert args.name == "Spider-Man"


def test_emit_json(capsys):
    cli.emit({"a": 1}, as_json=True)
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_no_args_prints_help_and_fails():
    assert cli.main([]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis'`

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "mc-jarvis"
version = "0.1.0"
description = "An agent-agnostic assistant for Marvel Champions: The Card Game"
requires-python = ">=3.10"
dependencies = ["pypdf>=4.0", "PyYAML>=6.0"]

[project.optional-dependencies]
browser = ["playwright>=1.40"]
dev = ["pytest>=8.0"]

[project.scripts]
mc-jarvis = "mc_jarvis.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mc_jarvis"]

# The skill and config ship inside the wheel so `uv tool install` users,
# who have no checkout, can still run `install-skill` (spec §7). In a
# checkout these paths are symlinks to the repo-root sources (Step 8);
# force-include resolves them to real files at build time.
[tool.hatch.build.targets.wheel.force-include]
"config/legality.yaml" = "src/mc_jarvis/_bundled/legality.yaml"
"config/glyphs.yaml"   = "src/mc_jarvis/_bundled/glyphs.yaml"
"config/timing.yaml"   = "src/mc_jarvis/_bundled/timing.yaml"
"skill"                = "src/mc_jarvis/_bundled/skill"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: requires a built index; skipped when absent"]
```

- [ ] **Step 4: Write `paths.py`**

```python
"""Data directory resolution. Never alongside the package (spec §5)."""
from __future__ import annotations

import os
from pathlib import Path

SUBDIRS = ("marvelsdb", "rules/pdf", "rules/txt", "meta")


def data_dir() -> Path:
    explicit = os.environ.get("MC_JARVIS_DATA")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "mc-jarvis"
    return Path.home() / ".local" / "share" / "mc-jarvis"


def ensure_data_dir() -> Path:
    root = data_dir()
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def db_path() -> Path:
    return data_dir() / "mc.sqlite"
```

- [ ] **Step 5: Write `cli.py`**

Note the `_leaf` helper: it adds `--json` to every leaf parser, which is what keeps the flag from drifting as commands are added in later tasks. Commands not yet implemented raise `SystemExit(3)` with a clear message rather than a traceback.

```python
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    # Subcommands are wired in later tasks; until then fail loudly and
    # legibly rather than with a traceback.
    handler = _HANDLERS.get(args.command)
    if handler is None:
        print(f"mc-jarvis: '{args.command}' is not implemented yet",
              file=sys.stderr)
        return 3
    return handler(args)


_HANDLERS: dict[str, Any] = {}
```

**argparse does *not* normalise a subcommand alias to its canonical name.** Verified 2026-08-22: `hero X` yields `args.command == "hero"`. `main` therefore maps it through an `ALIASES = {"hero": "identity"}` table before dispatch, so there is one name to match on.

**`--owned` is declared but inert in this plan.** The collection lands in the deck-pipeline plan, so the flag exists here only to keep the command surface stable. A flag that silently does nothing is the "did you filter?" bug class spec §13 warns about, so it must refuse rather than be ignored. Add to `_dispatch`, before the handler lookup:

```python
    if getattr(args, "owned", False):
        print("mc-jarvis: --owned needs a collection, which is not built "
              "yet in this version", file=sys.stderr)
        return 3
```

and a test:

```python
def test_owned_refuses_rather_than_silently_ignoring():
    assert cli.main(["card", "search", "web", "--owned"]) == 3
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS, 11 tests

- [ ] **Step 7: Verify the console script installs**

Run: `uv tool install --editable . && mc-jarvis --help && mc-jarvis doctor; echo "exit=$?"`
Expected: help text listing every command; `doctor` prints the not-implemented message and `exit=3`

- [ ] **Step 8: Create the bundled-asset directory**

Three modules resolve paths into `src/mc_jarvis/_bundled/` — `outofdeck.CONFIG_PATH`, `rules_chunk.GLYPHS_PATH`, and `skill_install.SKILL_SOURCE` — and the wheel ships it. Create it now, as scaffolding, so no later task depends on a directory nothing makes.

```bash
mkdir -p src/mc_jarvis/_bundled
# Development: the editable sources live at the repo root; the package
# reads them through links so an edit takes effect without a rebuild.
ln -sfn ../../../config/legality.yaml src/mc_jarvis/_bundled/legality.yaml
ln -sfn ../../../config/glyphs.yaml   src/mc_jarvis/_bundled/glyphs.yaml
ln -sfn ../../../config/timing.yaml   src/mc_jarvis/_bundled/timing.yaml
ln -sfn ../../../skill                src/mc_jarvis/_bundled/skill
printf '*\n!.gitignore\n' > src/mc_jarvis/_bundled/.gitignore
```

The links are gitignored; the `force-include` block already written in Step 3 gives the wheel real files instead. Add the test:

```python
# tests/test_bundled.py
from mc_jarvis import outofdeck, rules_chunk, skill_install


def test_every_bundled_asset_path_resolves():
    """Three modules read from _bundled/. A missing link here surfaces as
    a confusing failure four tasks later."""
    assert outofdeck.CONFIG_PATH.exists(), outofdeck.CONFIG_PATH
    assert rules_chunk.GLYPHS_PATH.exists(), rules_chunk.GLYPHS_PATH
    assert (skill_install.SKILL_SOURCE / "SKILL.md").exists(), \
        skill_install.SKILL_SOURCE
```

This test fails until Tasks 8, 13, and 16 create the three sources. That is intentional — mark it `@pytest.mark.xfail(strict=False)` now and remove the marker in Task 16.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/ tests/ .gitignore
git commit -m "feat: package scaffold, data paths, and CLI seam"
```

---

## Task 2: `mc-jarvis doctor`

Implements §6. Requirements are checked at runtime because this runs under agents we do not control, on machines we have never seen.

**Files:**
- Create: `src/mc_jarvis/doctor.py`
- Modify: `src/mc_jarvis/cli.py` (register the handler)
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `paths.data_dir`, `paths.db_path`, `cli.emit`
- Produces:
  - `doctor.Check` — dataclass with fields `name: str`, `ok: bool`, `detail: str`, `hard: bool`
  - `doctor.run_checks(*, network: bool = True) -> list[Check]`
  - `doctor.pdf_backend() -> str` — returns `"pdftotext"`, `"pypdf"`, or `"none"`
  - `doctor.has_fts5() -> bool`
  - `doctor.handle(args) -> int` — 0 when all hard checks pass, 1 otherwise. Reads `args.network` (default True) so tests and offline machines exercise the same path without reaching the network.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor.py
import sqlite3
from mc_jarvis import doctor


def test_fts5_detected_on_this_interpreter():
    # Every supported environment has it; if this fails here, doctor is
    # correctly telling us the environment is unsupported.
    assert doctor.has_fts5() is True


def test_pdf_backend_is_one_of_the_known_values():
    assert doctor.pdf_backend() in {"pdftotext", "pypdf", "none"}


def test_run_checks_offline_reports_no_network_checks():
    names = [c.name for c in doctor.run_checks(network=False)]
    assert "python" in names
    assert "sqlite-fts5" in names
    assert "data-dir" in names
    assert not any(n.startswith("network:") for n in names)


def test_run_checks_marks_missing_index_as_soft(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))
    index_check = next(c for c in doctor.run_checks(network=False)
                       if c.name == "index")
    assert index_check.ok is False
    assert index_check.hard is False   # no index yet is normal before init
    assert "init" in index_check.detail


def test_handle_returns_nonzero_only_on_hard_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))

    class Args:
        json = False
    assert doctor.handle(Args()) == 0    # missing index alone must not fail

    monkeypatch.setattr(doctor, "has_fts5", lambda: False)
    assert doctor.handle(Args()) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_doctor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.doctor'`

- [ ] **Step 3: Write `doctor.py`**

```python
"""Runtime prerequisite checks (spec §6)."""
from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict

from . import paths
from .cli import emit

PYTHON_FLOOR = (3, 10)
UPSTREAMS = {
    "network:card-data": "https://codeload.github.com",
    "network:ffg-cdn": "https://images-cdn.fantasyflightgames.com",
}

INSTALL_HINT = {
    "Linux": "your distribution's package manager, e.g. `sudo dnf install poppler-utils`",
    "Darwin": "`brew install poppler`",
    "Windows": "not required — pypdf is used",
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hard: bool


def has_fts5() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        conn.close()
        return True
    except sqlite3.Error:
        return False


def pdf_backend() -> str:
    if shutil.which("pdftotext"):
        return "pdftotext"
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        return "none"


def _reachable(url: str, timeout: float = 5.0) -> bool:
    req = urllib.request.Request(url, method="HEAD")
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True          # a status code means the host answered
    except Exception:
        return False


def run_checks(*, network: bool = True) -> list[Check]:
    checks: list[Check] = []

    v = sys.version_info
    checks.append(Check(
        "python", v[:2] >= PYTHON_FLOOR,
        f"{v.major}.{v.minor}.{v.micro} (need >= 3.10)", hard=True))

    checks.append(Check(
        "sqlite-fts5", has_fts5(),
        f"SQLite {sqlite3.sqlite_version}"
        + ("" if has_fts5() else " — built without FTS5; a full CPython "
                                "build is required"),
        hard=True))

    backend = pdf_backend()
    checks.append(Check(
        "pdf-backend", backend != "none",
        backend if backend != "none"
        else f"neither pdftotext nor pypdf found; install poppler via "
             f"{INSTALL_HINT.get(platform.system(), 'your package manager')}",
        hard=True))

    root = paths.data_dir()
    writable = os.access(root.parent if not root.exists() else root, os.W_OK)
    checks.append(Check("data-dir", writable, str(root), hard=True))

    db = paths.db_path()
    if db.exists():
        age_days = (time.time() - db.stat().st_mtime) / 86400
        checks.append(Check(
            "index", True,
            f"{db} ({age_days:.0f} days old)"
            + ("  — stale, run `mc-jarvis update`" if age_days > 14 else ""),
            hard=False))
    else:
        checks.append(Check(
            "index", False, "not built — run `mc-jarvis init`", hard=False))

    for optional, present in (
        ("git", shutil.which("git") is not None),
        ("playwright", _playwright_present()),
    ):
        checks.append(Check(
            f"optional:{optional}", present,
            "present" if present else "absent (not required)", hard=False))

    if network:
        for name, url in UPSTREAMS.items():
            ok = _reachable(url)
            checks.append(Check(name, ok, url, hard=False))

    return checks


def _playwright_present() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def handle(args) -> int:
    checks = run_checks()
    if getattr(args, "json", False):
        emit([asdict(c) for c in checks], as_json=True)
    else:
        for c in checks:
            mark = "ok  " if c.ok else ("FAIL" if c.hard else "--  ")
            print(f"{mark} {c.name}: {c.detail}")
    return 1 if any(c.hard and not c.ok for c in checks) else 0
```

- [ ] **Step 4: Register the handler in `cli.py`**

Replace the empty `_HANDLERS` dict at the bottom of `cli.py`. Import inside the function to keep `cli` import-light and avoid a circular import with `doctor`.

```python
def _dispatch(name: str, args) -> int:
    if name == "doctor":
        from . import doctor
        return doctor.handle(args)
    print(f"mc-jarvis: '{name}' is not implemented yet", file=sys.stderr)
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    return _dispatch(args.command, args)
```

Delete the `_HANDLERS` dict and the old handler lookup in `main`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Verify against the real environment**

Run: `mc-jarvis doctor; echo "exit=$?"`
Expected: `python`, `sqlite-fts5`, `pdf-backend`, `data-dir` all `ok`; `index` shows `not built`; `exit=0`

- [ ] **Step 7: Commit**

```bash
git add src/mc_jarvis/doctor.py src/mc_jarvis/cli.py tests/test_doctor.py
git commit -m "feat: mc-jarvis doctor with runtime prerequisite checks"
```

---

## Task 3: Fetch the card data

Implements §6 and §11 step 1. The tarball is 1.5 MB and needs no `git`.

**Files:**
- Create: `src/mc_jarvis/sources.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `paths.ensure_data_dir`
- Produces:
  - `sources.CARD_DATA_URL: str`
  - `sources.fetch_card_data(dest: Path, *, url: str = CARD_DATA_URL) -> FetchReport`
  - `sources.FetchReport` — dataclass with `pack_files: int`, `bytes_downloaded: int`, `dest: Path`

- [ ] **Step 1: Write the failing test**

The test builds its own tarball, so it needs no network and no FFG content.

```python
# tests/test_sources.py
import io
import json
import tarfile
import pytest
from mc_jarvis import sources


def _fake_tarball(tmp_path):
    """A tarball shaped like GitHub's: one top-level prefix directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, body in [
            ("marvelsdb-json-data-master/pack/core.json",
             json.dumps([{"code": "01001a", "name": "Test Hero"}])),
            ("marvelsdb-json-data-master/pack/gmw.json",
             json.dumps([{"code": "02001", "name": "Test Ally"}])),
            ("marvelsdb-json-data-master/packs.json", json.dumps([])),
            ("marvelsdb-json-data-master/sets.json", json.dumps([])),
            ("marvelsdb-json-data-master/README.md", "ignore me"),
        ]:
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_extracts_and_strips_the_github_prefix(tmp_path, monkeypatch):
    blob = _fake_tarball(tmp_path)
    monkeypatch.setattr(sources, "_download", lambda url: blob)
    report = sources.fetch_card_data(tmp_path / "marvelsdb")
    assert (tmp_path / "marvelsdb" / "pack" / "core.json").is_file()
    assert (tmp_path / "marvelsdb" / "packs.json").is_file()
    assert report.pack_files == 2


def test_refuses_path_traversal_members(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"pwned"
        info = tarfile.TarInfo("marvelsdb-json-data-master/../../evil.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(sources, "_download", lambda url: buf.getvalue())
    with pytest.raises(ValueError, match="unsafe path"):
        sources.fetch_card_data(tmp_path / "marvelsdb")
    assert not (tmp_path.parent / "evil.json").exists()


def test_replaces_previous_contents(tmp_path, monkeypatch):
    dest = tmp_path / "marvelsdb"
    (dest / "pack").mkdir(parents=True)
    (dest / "pack" / "stale.json").write_text("[]")
    monkeypatch.setattr(sources, "_download", lambda url: _fake_tarball(tmp_path))
    sources.fetch_card_data(dest)
    assert not (dest / "pack" / "stale.json").exists()


@pytest.mark.integration
def test_real_tarball_has_the_expected_shape(tmp_path):
    report = sources.fetch_card_data(tmp_path / "marvelsdb")
    assert report.pack_files > 100          # 116 at time of writing
    assert report.bytes_downloaded < 5_000_000
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_sources.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.sources'`

- [ ] **Step 3: Write `sources.py`**

`tarfile` extraction of a downloaded archive is the classic path-traversal sink, so members are validated before any write. Python 3.12 has `filter="data"` but the floor is 3.10, so the check is explicit.

```python
"""Card data acquisition (spec §6, §11)."""
from __future__ import annotations

import io
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CARD_DATA_URL = "https://codeload.github.com/zzorba/marvelsdb-json-data/tar.gz/refs/heads/master"
USER_AGENT = "mc-jarvis (+https://github.com/zzorba/marvelsdb-json-data)"


@dataclass
class FetchReport:
    pack_files: int
    bytes_downloaded: int
    dest: Path


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _safe_members(tf: tarfile.TarFile, root: Path):
    for member in tf.getmembers():
        if not member.isfile():
            continue
        # Strip GitHub's top-level "<repo>-<ref>/" prefix.
        parts = Path(member.name).parts
        if len(parts) < 2:
            continue
        rel = Path(*parts[1:])
        target = (root / rel).resolve()
        if not str(target).startswith(str(root.resolve())):
            raise ValueError(f"unsafe path in archive: {member.name}")
        if ".." in rel.parts:
            raise ValueError(f"unsafe path in archive: {member.name}")
        yield member, rel


def fetch_card_data(dest: Path, *, url: str = CARD_DATA_URL) -> FetchReport:
    blob = _download(url)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    pack_files = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member, rel in _safe_members(tf, dest):
            if rel.suffix != ".json":
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            out.write_bytes(src.read())
            if rel.parts[0] == "pack":
                pack_files += 1

    return FetchReport(pack_files=pack_files,
                       bytes_downloaded=len(blob), dest=dest)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources.py -v -m "not integration"`
Expected: PASS, 3 tests

- [ ] **Step 5: Run the integration test against the real upstream**

Run: `uv run pytest tests/test_sources.py -v -m integration`
Expected: PASS — `pack_files` around 116, download under 2 MB

- [ ] **Step 6: Commit**

```bash
git add src/mc_jarvis/sources.py tests/test_sources.py
git commit -m "feat: fetch card data tarball without requiring git"
```

---

## Task 4: Schema and card loader

Implements §8 and the copies rules in §10. The `deck_limit <= quantity` invariant is asserted here so that a future upstream change fails loudly instead of quietly under-counting.

**Files:**
- Create: `src/mc_jarvis/schema.py`, `src/mc_jarvis/index.py`, `tests/fixtures/__init__.py`, `tests/fixtures/cards.py`
- Test: `tests/test_index.py`

**Interfaces:**
- Consumes: `paths.db_path`
- Produces:
  - `schema.SCHEMA: str` — all DDL, idempotent (`IF NOT EXISTS`)
  - `index.connect(db_path: Path) -> sqlite3.Connection` — row factory set to `sqlite3.Row`, foreign keys on
  - `index.load_cards(conn, marvelsdb_dir: Path) -> BuildReport`
  - `index.BuildReport` — dataclass with `cards: int`, `player_cards: int`, `packs: int`, `sets: int`, `warnings: list[str]`
  - `index.InvariantError` — exception
  - `index.resolve_deck_limit(card: dict) -> int` — the `deck_limit: null` → `quantity` fallback

**Fixture contract.** `tests/fixtures/cards.py` exposes `PACK` — a list of hand-invented card dicts in marvelsdb shape containing no FFG text. Later tasks extend it; the traps it must encode are listed in spec §14. This task adds: a `deck_limit: null` card, a normal card, and a card that violates the invariant (used only by the failure test).

- [ ] **Step 1: Write the fixture**

```python
# tests/fixtures/cards.py
"""Hand-invented cards in marvelsdb shape. No FFG text appears here."""

def card(code, name, **kw):
    base = {
        "code": code, "name": name, "type_code": "ally",
        "faction_code": "leadership", "pack_code": "tst",
        "set_code": "tester", "quantity": 3, "deck_limit": 3,
        "cost": 2, "text": "", "traits": "", "is_unique": False,
    }
    base.update(kw)
    return base


PACK = [
    card("tst01a", "Tester", type_code="hero", faction_code="hero",
         deck_limit=None, quantity=1, cost=None, back_link="tst01b",
         hand_size=5, health=10),
    card("tst01b", "Terry Tester", type_code="alter_ego",
         faction_code="hero", deck_limit=None, quantity=1, cost=None,
         hand_size=6, health=10),
    card("tst02", "Ordinary Ally", cost=3, quantity=3, deck_limit=3),
    card("tst03", "Limited Signature", faction_code="hero",
         deck_limit=None, quantity=2),
]

INVARIANT_VIOLATION = card("tst99", "Impossible Card",
                           quantity=1, deck_limit=3)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_index.py
import json
import pytest
from mc_jarvis import index, schema
from tests.fixtures import cards as fx


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.PACK))
    (root / "packs.json").write_text(json.dumps(
        [{"code": "tst", "name": "Tester Pack"}]))
    (root / "sets.json").write_text(json.dumps(
        [{"code": "tester", "name": "Tester Set",
          "card_set_type_code": "hero"}]))
    return root


@pytest.fixture
def conn(tmp_path):
    return index.connect(tmp_path / "mc.sqlite")


def test_loads_every_card(conn, corpus):
    report = index.load_cards(conn, corpus)
    assert report.cards == 4
    assert report.packs == 1
    assert report.sets == 1


def test_null_deck_limit_falls_back_to_quantity(conn, corpus):
    index.load_cards(conn, corpus)
    row = conn.execute(
        "SELECT deck_limit, deck_limit_raw, quantity FROM cards "
        "WHERE code = 'tst03'").fetchone()
    assert row["deck_limit_raw"] is None
    assert row["deck_limit"] == 2      # falls back to quantity, not unlimited
    assert row["quantity"] == 2


def test_deck_limit_never_silently_exceeds_quantity(conn, corpus):
    bad = json.loads((corpus / "pack" / "tst.json").read_text())
    bad.append(fx.INVARIANT_VIOLATION)
    (corpus / "pack" / "tst.json").write_text(json.dumps(bad))
    with pytest.raises(index.InvariantError, match="deck_limit"):
        index.load_cards(conn, corpus)


def test_grouped_invariant_catches_cross_printing_violation(conn, corpus):
    """A card at quantity 1 in every pack breaks the invariant even
    though no single row does (spec §10)."""
    other = dict(fx.card("tst02", "Ordinary Ally"),
                 pack_code="tst2", quantity=1, deck_limit=1)
    (corpus / "pack" / "tst2.json").write_text(json.dumps([other]))
    index.load_cards(conn, corpus)   # 3 in tst, 1 in tst2 -> max 3 <= max 3, ok


def test_reload_is_idempotent(conn, corpus):
    index.load_cards(conn, corpus)
    report = index.load_cards(conn, corpus)
    assert report.cards == 4
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 4


def test_raw_json_is_retained_verbatim(conn, corpus):
    index.load_cards(conn, corpus)
    raw = conn.execute(
        "SELECT raw FROM cards WHERE code = 'tst02'").fetchone()["raw"]
    assert json.loads(raw)["name"] == "Ordinary Ally"


@pytest.mark.integration
def test_real_corpus_counts(real_index):
    n = real_index.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    assert 4000 < n < 6000                      # 4,298 at time of writing
    player = real_index.execute(
        "SELECT COUNT(*) FROM cards WHERE faction_code != 'encounter'"
    ).fetchone()[0]
    assert 1400 < player < 2500                 # 1,607 at time of writing
```

Add the shared integration fixture:

```python
# tests/conftest.py
import pytest
from mc_jarvis import index, paths


@pytest.fixture
def real_index():
    db = paths.db_path()
    if not db.exists():
        pytest.skip("no built index; run `mc-jarvis init`")
    return index.connect(db)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_index.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.schema'`

- [ ] **Step 4: Write `schema.py`**

```python
"""All DDL in one place. Idempotent."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    subname             TEXT,
    type_code           TEXT,
    faction_code        TEXT,
    pack_code           TEXT,
    set_code            TEXT,
    back_link           TEXT,
    double_sided        INTEGER,
    is_unique           INTEGER,
    permanent           INTEGER,
    duplicate_of        TEXT,
    cost                INTEGER,
    quantity            INTEGER,
    deck_limit          INTEGER,   -- resolved: null falls back to quantity
    deck_limit_raw      INTEGER,   -- exactly as printed upstream
    resource_physical   INTEGER,
    resource_mental     INTEGER,
    resource_energy     INTEGER,
    resource_wild       INTEGER,
    attack              INTEGER,
    thwart              INTEGER,
    defense             INTEGER,
    recover             INTEGER,
    health              INTEGER,
    hand_size           INTEGER,
    text                TEXT,
    flavor              TEXT,
    traits              TEXT,
    raw                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cards_name       ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_set        ON cards(set_code);
CREATE INDEX IF NOT EXISTS idx_cards_pack       ON cards(pack_code);
CREATE INDEX IF NOT EXISTS idx_cards_faction    ON cards(faction_code);
CREATE INDEX IF NOT EXISTS idx_cards_type       ON cards(type_code);

CREATE TABLE IF NOT EXISTS packs (
    code TEXT PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS sets (
    code               TEXT PRIMARY KEY,
    name               TEXT,
    card_set_type_code TEXT
);

CREATE TABLE IF NOT EXISTS build_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""
```

- [ ] **Step 5: Write `index.py`**

```python
"""SQLite index build (spec §8, §10)."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import schema


class InvariantError(RuntimeError):
    """An upstream assumption this design relies on no longer holds."""


@dataclass
class BuildReport:
    cards: int = 0
    player_cards: int = 0
    packs: int = 0
    sets: int = 0
    warnings: list[str] = field(default_factory=list)


COLUMNS = (
    "code name subname type_code faction_code pack_code set_code back_link "
    "double_sided is_unique permanent duplicate_of cost quantity "
    "resource_physical resource_mental resource_energy resource_wild "
    "attack thwart defense recover health hand_size text flavor traits"
).split()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema.SCHEMA)
    return conn


def resolve_deck_limit(card: dict) -> int | None:
    """`deck_limit: null` is not unlimited — it falls back to `quantity`
    (spec §10). 120 player cards depend on this."""
    limit = card.get("deck_limit")
    if limit is None:
        return card.get("quantity")
    return limit


def _assert_copy_invariant(rows: list[dict]) -> None:
    """`deck_limit` must never exceed `quantity`, per printing and grouped
    across printings (spec §10). Collection ownership being binary depends
    on this holding."""
    for c in rows:
        raw = c.get("deck_limit")
        qty = c.get("quantity")
        if raw is not None and qty is not None and raw > qty:
            raise InvariantError(
                f"deck_limit {raw} exceeds quantity {qty} for "
                f"{c['code']} ({c.get('name')}); collection logic assumes "
                f"this cannot happen (spec §10)")

    by_name = defaultdict(lambda: {"limit": 0, "qty": 0})
    for c in rows:
        key = (c.get("name"), c.get("type_code"), c.get("faction_code"))
        agg = by_name[key]
        agg["limit"] = max(agg["limit"], resolve_deck_limit(c) or 0)
        agg["qty"] = max(agg["qty"], c.get("quantity") or 0)
    for key, agg in by_name.items():
        if agg["limit"] > agg["qty"]:
            raise InvariantError(
                f"grouped deck_limit {agg['limit']} exceeds max quantity "
                f"{agg['qty']} for {key} (spec §10)")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_cards(conn: sqlite3.Connection, marvelsdb_dir: Path) -> BuildReport:
    report = BuildReport()

    pack_dir = marvelsdb_dir / "pack"
    if not pack_dir.is_dir():
        raise InvariantError(f"no pack/ directory under {marvelsdb_dir}")

    rows: list[dict] = []
    for path in sorted(pack_dir.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, list):
            report.warnings.append(f"{path.name}: not a list, skipped")
            continue
        rows.extend(payload)

    if not rows:
        raise InvariantError(f"no cards found under {pack_dir}")

    _assert_copy_invariant(rows)

    conn.execute("DELETE FROM cards")
    conn.executemany(
        f"INSERT OR REPLACE INTO cards ({', '.join(COLUMNS)}, "
        f"deck_limit, deck_limit_raw, raw) VALUES "
        f"({', '.join('?' * len(COLUMNS))}, ?, ?, ?)",
        [
            tuple(c.get(col) for col in COLUMNS)
            + (resolve_deck_limit(c), c.get("deck_limit"),
               json.dumps(c, ensure_ascii=False))
            for c in rows
        ],
    )
    report.cards = len(rows)
    report.player_cards = sum(
        1 for c in rows if c.get("faction_code") != "encounter")

    for name, table, cols in (
        ("packs.json", "packs", ("code", "name")),
        ("sets.json", "sets", ("code", "name", "card_set_type_code")),
    ):
        path = marvelsdb_dir / name
        if not path.exists():
            report.warnings.append(f"{name} missing")
            continue
        payload = _read_json(path)
        conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            [tuple(item.get(c) for c in cols) for item in payload])
        setattr(report, table, len(payload))

    conn.commit()
    return report
```

Note `sqlite3` stores Python `bool` as 0/1 and `None` as NULL, so `is_unique` and `permanent` need no conversion.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_index.py -v -m "not integration"`
Expected: PASS, 6 tests

- [ ] **Step 7: Build against the real corpus by hand**

```bash
uv run python -c "
from pathlib import Path
from mc_jarvis import index, sources, paths
root = paths.ensure_data_dir()
print(sources.fetch_card_data(root / 'marvelsdb'))
conn = index.connect(paths.db_path())
print(index.load_cards(conn, root / 'marvelsdb'))
"
```
Expected: around 4,298 cards, 1,607 player cards, 61 packs, no `InvariantError`

- [ ] **Step 8: Run the integration tests**

Run: `uv run pytest tests/ -v -m integration`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/mc_jarvis/schema.py src/mc_jarvis/index.py tests/
git commit -m "feat: SQLite schema and card loader with copy invariants"
```

---

## Task 5: FTS5 and `card search` — FIRST TESTABLE CHECKPOINT

Implements §3 and §5.1. After this task the tool answers real questions. **Stop here and exercise it against the real corpus before continuing** — this is the point of the slice.

**Files:**
- Create: `src/mc_jarvis/cards.py`
- Modify: `src/mc_jarvis/schema.py` (add FTS table), `src/mc_jarvis/index.py` (populate it), `src/mc_jarvis/cli.py` (dispatch)
- Test: `tests/test_cards_search.py`

**Interfaces:**
- Consumes: `index.connect`, `cli.emit`
- Produces:
  - `cards.search(conn, query: str | None = None, *, aspect=None, type=None, cost=None, trait=None, text=None, limit=20) -> list[dict]`
  - `cards.handle_search(args) -> int`
  - `index.build_fts(conn) -> int` — rebuilds the FTS table, returns row count

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cards_search.py
import json
import pytest
from mc_jarvis import cards, index
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    pack = fx.PACK + [
        fx.card("tst10", "Web Shooter", type_code="upgrade",
                faction_code="hero", text="Exhaust to web an enemy.",
                traits="Tech.", cost=1),
        fx.card("tst11", "Aerial Strike", type_code="event",
                faction_code="aggression", text="Deal 3 damage.",
                traits="Attack.", cost=2),
    ]
    (root / "pack" / "tst.json").write_text(json.dumps(pack))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    return c


def test_full_text_matches_card_text(conn):
    hits = cards.search(conn, "web")
    names = {h["name"] for h in hits}
    assert "Web Shooter" in names


def test_filters_compose_with_the_query(conn):
    assert cards.search(conn, "damage", aspect="aggression")
    assert cards.search(conn, "damage", aspect="protection") == []


def test_filter_only_search_needs_no_query(conn):
    hits = cards.search(conn, None, type="upgrade")
    assert [h["code"] for h in hits] == ["tst10"]


def test_cost_filter_accepts_comparisons(conn):
    assert {h["code"] for h in cards.search(conn, None, cost="<=1")} == {"tst10"}
    assert {h["code"] for h in cards.search(conn, None, cost="2")} >= {"tst11"}


def test_limit_is_honoured(conn):
    assert len(cards.search(conn, None, limit=2)) == 2


def test_fts_special_characters_do_not_raise(conn):
    """A user query is not FTS5 syntax; `Sp//dr` and quotes must not
    become a syntax error."""
    for q in ["Sp//dr", 'a "quoted" thing', "AND", "foo*bar", "-"]:
        cards.search(conn, q)


@pytest.mark.integration
def test_real_corpus_structural_query(real_index):
    hits = cards.search(real_index, None, aspect="justice", type="ally",
                        cost="<=2", limit=100)
    assert len(hits) > 5
    assert all(h["faction_code"] == "justice" for h in hits)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cards_search.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.cards'`

- [ ] **Step 3: Add the FTS table to `schema.py`**

Append to `SCHEMA`:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, subname, text, traits, flavor,
    content='cards', content_rowid='rowid'
);
```

External-content FTS5 keeps no second copy of the text; `build_fts` repopulates it explicitly rather than via triggers, because the index is rebuilt wholesale rather than edited.

- [ ] **Step 4: Add `build_fts` to `index.py`**

```python
def build_fts(conn: sqlite3.Connection) -> int:
    conn.execute("INSERT INTO cards_fts(cards_fts) VALUES('delete-all')")
    conn.execute(
        "INSERT INTO cards_fts(rowid, name, subname, text, traits, flavor) "
        "SELECT rowid, name, subname, text, traits, flavor FROM cards")
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM cards_fts").fetchone()[0]
```

- [ ] **Step 5: Write `cards.py`**

`_fts_query` is load-bearing: a player's words are not FTS5 syntax, and card names contain `//`, `-`, and quotes. Every term is quoted so it is treated as a literal.

```python
"""Card queries (spec §5.1)."""
from __future__ import annotations

import re
import sqlite3

from . import index, paths
from .cli import emit

SUMMARY = ("code", "name", "subname", "type_code", "faction_code",
           "cost", "pack_code", "traits", "text")

_COST = re.compile(r"^(<=|>=|<|>|=)?\s*(\d+)$")


def _fts_query(raw: str) -> str:
    """Turn a human phrase into a safe FTS5 MATCH expression.

    Every token is double-quoted, so FTS5 operators and punctuation in
    card names (Sp//dr, Alter-Ego) are literals rather than syntax.
    """
    tokens = re.findall(r"[\w'/-]+", raw)
    if not tokens:
        return ""
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def search(conn, query=None, *, aspect=None, type=None, cost=None,
           trait=None, text=None, limit=20) -> list[dict]:
    where, params = [], []
    joins = ""

    if query:
        expr = _fts_query(query)
        if expr:
            joins = ("JOIN cards_fts ON cards_fts.rowid = cards.rowid "
                     "AND cards_fts MATCH ?")
            params.append(expr)

    if aspect:
        where.append("cards.faction_code = ?")
        params.append(aspect)
    if type:
        where.append("cards.type_code = ?")
        params.append(type)
    if trait:
        where.append("cards.traits LIKE ?")
        params.append(f"%{trait}%")
    if text:
        where.append("cards.text LIKE ?")
        params.append(f"%{text}%")
    if cost:
        m = _COST.match(str(cost).strip())
        if not m:
            raise ValueError(f"unparseable cost filter: {cost!r} "
                             f"(try 2, <=3, >1)")
        op = m.group(1) or "="
        where.append(f"cards.cost {op} ?")
        params.append(int(m.group(2)))

    sql = (f"SELECT {', '.join('cards.' + c for c in SUMMARY)} "
           f"FROM cards {joins}")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY cards.code LIMIT ?"
    params.append(limit)

    return [dict(r) for r in conn.execute(sql, params)]


def _open():
    db = paths.db_path()
    if not db.exists():
        raise SystemExit("no index found — run `mc-jarvis init` first")
    return index.connect(db)


def handle_search(args) -> int:
    conn = _open()
    hits = search(conn, args.query, aspect=args.aspect, type=args.type,
                  cost=args.cost, trait=args.trait, text=args.text,
                  limit=args.limit)
    if args.json:
        emit(hits, as_json=True)
    else:
        if not hits:
            print("no matches")
        for h in hits:
            cost = "-" if h["cost"] is None else h["cost"]
            print(f"{h['code']:<8} {h['name']:<32} "
                  f"{h['faction_code']:<12} {h['type_code']:<10} {cost}")
    return 0
```

- [ ] **Step 6: Dispatch it from `cli.py`**

In `_dispatch`, add:

```python
    if name == "card":
        from . import cards
        if args.card_cmd == "search":
            return cards.handle_search(args)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 8: Rebuild the real index and exercise it**

```bash
uv run python -c "
from mc_jarvis import index, paths
conn = index.connect(paths.db_path())
print('fts rows:', index.build_fts(conn))
"
mc-jarvis card search "web" --limit 5
mc-jarvis card search --aspect justice --type ally --cost "<=2" --limit 10
mc-jarvis card search "Sp//dr"
mc-jarvis card search --trait Aerial --limit 5 --json
```
Expected: real cards in every case; no FTS5 syntax errors; `--json` is valid JSON

- [ ] **Step 9: Commit**

```bash
git add src/mc_jarvis/cards.py src/mc_jarvis/schema.py src/mc_jarvis/index.py src/mc_jarvis/cli.py tests/
git commit -m "feat: FTS5 index and card search"
```

**CHECKPOINT — hand the tool to the user here.** Real queries against the real corpus are what this slice exists to enable. Gaps found now are cheaper than gaps found after the deck pipeline is built on top.

---

## Task 6: `card show` and name disambiguation

Implements §8. 79 player names appear in more than one pack and 60 character names exist as both an identity face and an ally, so this command **disambiguates rather than guesses**.

**Files:**
- Modify: `src/mc_jarvis/cards.py`, `src/mc_jarvis/cli.py`
- Test: `tests/test_cards_show.py`

**Interfaces:**
- Produces:
  - `cards.show(conn, ident: str) -> dict` — either `{"card": {...}, "faces": [...]}` or `{"ambiguous": [...]}`
  - `cards.handle_show(args) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cards_show.py
import json
import pytest
from mc_jarvis import cards, index
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    pack = fx.PACK + [
        # The trap: one name, two genuinely different cards.
        fx.card("tst20", "Tester", type_code="ally",
                faction_code="leadership", cost=3),
    ]
    (root / "pack" / "tst.json").write_text(json.dumps(pack))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    return c


def test_lookup_by_code_is_exact(conn):
    result = cards.show(conn, "tst02")
    assert result["card"]["name"] == "Ordinary Ally"


def test_unambiguous_name_resolves(conn):
    assert cards.show(conn, "Ordinary Ally")["card"]["code"] == "tst02"


def test_name_shared_by_a_hero_and_an_ally_is_ambiguous(conn):
    result = cards.show(conn, "Tester")
    assert "card" not in result
    codes = {c["code"] for c in result["ambiguous"]}
    assert codes == {"tst01a", "tst20"}


def test_name_match_is_case_insensitive(conn):
    assert cards.show(conn, "ordinary ally")["card"]["code"] == "tst02"


def test_linked_faces_are_returned_together(conn):
    result = cards.show(conn, "tst01a")
    assert [f["code"] for f in result["faces"]] == ["tst01a", "tst01b"]


def test_unknown_name_returns_no_match(conn):
    assert cards.show(conn, "Nonexistent")["ambiguous"] == []


@pytest.mark.integration
def test_real_black_panther_is_ambiguous(real_index):
    """Two distinct heroes plus an ally share this title (spec §8)."""
    result = real_index and cards.show(real_index, "Black Panther")
    assert "card" not in result
    assert len(result["ambiguous"]) >= 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cards_show.py -v -m "not integration"`
Expected: FAIL — `AttributeError: module 'mc_jarvis.cards' has no attribute 'show'`

- [ ] **Step 3: Implement `show` in `cards.py`**

```python
FULL = SUMMARY + ("set_code", "back_link", "is_unique", "permanent",
                  "deck_limit", "quantity", "attack", "thwart", "defense",
                  "recover", "health", "hand_size", "resource_physical",
                  "resource_mental", "resource_energy", "resource_wild",
                  "flavor")


def _row(conn, code) -> dict | None:
    r = conn.execute(
        f"SELECT {', '.join(FULL)} FROM cards WHERE code = ?",
        (code,)).fetchone()
    return dict(r) if r else None


def _faces(conn, card: dict) -> list[dict]:
    """A card and everything linked to it, in code order. `back_link`
    points hero -> alter-ego and is null on extra forms (spec §8)."""
    seen, queue, out = set(), [card["code"]], []
    while queue:
        code = queue.pop()
        if code in seen:
            continue
        seen.add(code)
        row = _row(conn, code)
        if not row:
            continue
        out.append(row)
        if row.get("back_link"):
            queue.append(row["back_link"])
        for other in conn.execute(
                "SELECT code FROM cards WHERE back_link = ?", (code,)):
            queue.append(other["code"])
    return sorted(out, key=lambda r: r["code"])


def show(conn, ident: str) -> dict:
    exact = _row(conn, ident)
    if exact:
        return {"card": exact, "faces": _faces(conn, exact)}

    matches = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(SUMMARY)} FROM cards "
        f"WHERE lower(name) = lower(?) ORDER BY code", (ident,))]

    if len(matches) == 1:
        card = _row(conn, matches[0]["code"])
        return {"card": card, "faces": _faces(conn, card)}

    # Zero or many: never guess. 60 character names exist as both an
    # identity face and an ally (spec §8).
    return {"ambiguous": matches}


def handle_show(args) -> int:
    conn = _open()
    result = show(conn, args.name)
    if getattr(args, "explain", False) and "card" in result:
        from . import rules
        result["keywords"] = rules.explain(conn, result["card"]["code"])
    if args.json:
        emit(result, as_json=True)
        return 0 if "card" in result else 1
    if "card" in result:
        for face in result["faces"]:
            _print_card(face)
        for kw in result.get("keywords", []):
            print(f"\n  {kw['term']} (p.{kw['page']}) — {kw['body']}")
        return 0
    if not result["ambiguous"]:
        print(f"no card named {args.name!r}")
        return 1
    print(f"{args.name!r} matches several cards — pick one by code:")
    for c in result["ambiguous"]:
        print(f"  {c['code']:<8} {c['name']:<28} "
              f"{c['type_code']:<10} {c['faction_code']}")
    return 1


def _print_card(c: dict) -> None:
    title = c["name"] + (f" — {c['subname']}" if c.get("subname") else "")
    print(f"\n{title}  [{c['code']}]")
    print(f"  {c['faction_code']} {c['type_code']}"
          + (f", cost {c['cost']}" if c["cost"] is not None else ""))
    if c.get("traits"):
        print(f"  {c['traits']}")
    if c.get("text"):
        print(f"  {c['text']}")
```

`handle_show` references `rules.explain`, which Task 14 provides. Until then, `--explain` is the only flag that fails; leave the import inside the branch so nothing else breaks.

- [ ] **Step 4: Dispatch it** — in `cli.py` `_dispatch`, under the `card` branch add `if args.card_cmd == "show": return cards.handle_show(args)`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 6: Exercise against real data**

```bash
mc-jarvis card show "Black Panther"      # must list candidates, exit 1
mc-jarvis card show 01040a               # must show hero and alter-ego faces
mc-jarvis card show "Swinging Web Kick"
```

- [ ] **Step 7: Commit**

```bash
git add src/mc_jarvis/cards.py src/mc_jarvis/cli.py tests/test_cards_show.py
git commit -m "feat: card show with name disambiguation and linked faces"
```

---

## Task 7: Identity grouping and unique-match

Implements §8 — the subtlest part of the data model. Two separate rules, both of which naive implementations get wrong:

1. **Identities group on `set_code`, not `back_link`.** Angel, Ant-Man, and Wasp each have a third face with `back_link: null`; Ironheart has three complete identity cards.
2. **Unique-match is a graph over three name fields, not string equality.** It misses `23012` (matches via `subname`) and falsely matches the two Black Panther heroes (whose alter-egos are T'Challa and Shuri).

**Files:**
- Create: `src/mc_jarvis/identity.py`
- Modify: `src/mc_jarvis/schema.py`, `src/mc_jarvis/index.py`, `src/mc_jarvis/cards.py`, `src/mc_jarvis/cli.py`, `tests/fixtures/cards.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Produces:
  - `identity.build(conn) -> int` — populates `identities`, `identity_faces`, `match_titles`; returns identity count
  - `identity.titles_for(conn, code: str) -> set[str]` — every title, subtitle, and linked-face title, normalised
  - `identity.matches(conn, code_a: str, code_b: str) -> bool` — RR p.45
  - `cards.identity(conn, name: str) -> dict`
  - `cards.handle_identity(args) -> int`

- [ ] **Step 1: Extend the fixture**

Append to `tests/fixtures/cards.py` — this mirrors the Black Panther family's shape without using its text:

```python
# The RR p.45 unique-match family, invented. Four cards:
#   - a linked hero/alter-ego pair
#   - an ally sharing the hero's title
#   - an ally matching via subname, not name
#   - a second hero sharing the title but NOT matching (different alter-ego)
MATCH_FAMILY = [
    card("mtc01a", "Nightjar", type_code="hero", faction_code="hero",
         set_code="nightjar", is_unique=True, back_link="mtc01b",
         deck_limit=None, quantity=1),
    card("mtc01b", "Ada Vance", type_code="alter_ego", faction_code="hero",
         set_code="nightjar", is_unique=True, deck_limit=None, quantity=1),
    card("mtc02", "Ada Vance", type_code="ally", is_unique=True,
         deck_limit=1, quantity=1, set_code=None),
    card("mtc03", "Nightjar", subname="Ada Vance", type_code="ally",
         is_unique=True, deck_limit=1, quantity=1, set_code=None),
    card("mtc04a", "Nightjar", type_code="hero", faction_code="hero",
         set_code="nightjar2", is_unique=True, back_link="mtc04b",
         deck_limit=None, quantity=1),
    card("mtc04b", "Jo Reyes", type_code="alter_ego", faction_code="hero",
         set_code="nightjar2", is_unique=True, deck_limit=None, quantity=1),
]

# Extra hero form with back_link None (the Archangel shape), and a
# multi-card identity (the Ironheart shape).
EXTRA_FORMS = [
    card("frm01a", "Skyward", type_code="hero", faction_code="hero",
         set_code="skyward", back_link="frm01b", deck_limit=None,
         quantity=1, hand_size=5),
    card("frm01b", "Nell Cross", type_code="alter_ego", faction_code="hero",
         set_code="skyward", deck_limit=None, quantity=1, hand_size=6),
    card("frm01c", "Skyward Ascendant", type_code="hero",
         faction_code="hero", set_code="skyward", back_link=None,
         deck_limit=None, quantity=1, hand_size=4),
]

MULTI_IDENTITY = [
    c for i in (1, 2, 3) for c in (
        card(f"mid0{i}a", f"Cascade Mk{i}", type_code="hero",
             faction_code="hero", set_code="cascade", back_link=f"mid0{i}b",
             deck_limit=None, quantity=1, hand_size=3 + i),
        card(f"mid0{i}b", "Wren Bell", type_code="alter_ego",
             faction_code="hero", set_code="cascade", deck_limit=None,
             quantity=1, hand_size=6),
    )
]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_identity.py
import json
import pytest
from mc_jarvis import cards, identity, index
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(
        fx.PACK + fx.MATCH_FAMILY + fx.EXTRA_FORMS + fx.MULTI_IDENTITY))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    identity.build(c)
    return c


def test_extra_hero_form_is_part_of_the_identity(conn):
    """frm01c has back_link None; grouping on back_link would drop it."""
    faces = conn.execute(
        "SELECT code FROM identity_faces WHERE identity_key = 'skyward' "
        "ORDER BY code").fetchall()
    assert [f["code"] for f in faces] == ["frm01a", "frm01b", "frm01c"]


def test_multi_card_identity_is_one_identity(conn):
    """The Ironheart shape: three identity cards, six faces, one identity."""
    n = conn.execute(
        "SELECT COUNT(*) FROM identity_faces WHERE identity_key = 'cascade'"
    ).fetchone()[0]
    assert n == 6
    assert conn.execute(
        "SELECT COUNT(*) FROM identities WHERE identity_key = 'cascade'"
    ).fetchone()[0] == 1


def test_titles_include_every_linked_face(conn):
    assert identity.titles_for(conn, "mtc01a") == {"nightjar", "ada vance"}


def test_subname_participates_in_matching(conn):
    """mtc03's title differs from mtc02's; they match via subname."""
    assert identity.matches(conn, "mtc03", "mtc02") is True
    assert identity.matches(conn, "mtc01a", "mtc03") is True


def test_same_title_different_alter_ego_does_not_match(conn):
    """The false positive string equality produces: two heroes share the
    title 'Nightjar' but their alter-egos differ (spec §8)."""
    assert identity.matches(conn, "mtc01a", "mtc04a") is False


def test_non_unique_cards_never_match(conn):
    assert identity.matches(conn, "tst02", "tst02") is False


def test_identity_command_returns_all_faces(conn):
    result = cards.identity(conn, "Skyward")
    assert len(result["faces"]) == 3
    assert {f["hand_size"] for f in result["faces"]} == {4, 5, 6}


@pytest.mark.integration
def test_real_ironheart_has_six_faces(real_index):
    result = cards.identity(real_index, "Ironheart")
    assert len(result["faces"]) == 6


@pytest.mark.integration
def test_real_black_panther_heroes_do_not_match(real_index):
    assert identity.matches(real_index, "01040a", "51001a") is False
    assert identity.matches(real_index, "01040a", "23012") is True
    assert identity.matches(real_index, "01040a", "51002") is True
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_identity.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.identity'`

- [ ] **Step 4: Add tables to `schema.py`**

```sql
CREATE TABLE IF NOT EXISTS identities (
    identity_key TEXT PRIMARY KEY,   -- the set_code
    name         TEXT NOT NULL       -- the primary hero face's name
);

CREATE TABLE IF NOT EXISTS identity_faces (
    identity_key TEXT NOT NULL REFERENCES identities(identity_key),
    code         TEXT NOT NULL REFERENCES cards(code),
    PRIMARY KEY (identity_key, code)
);

-- Every title a card contributes to unique-matching: its name, its
-- subname, and the names of all its linked faces (spec §8, RR p.45).
CREATE TABLE IF NOT EXISTS match_titles (
    code  TEXT NOT NULL REFERENCES cards(code),
    title TEXT NOT NULL,             -- lowercased
    PRIMARY KEY (code, title)
);
CREATE INDEX IF NOT EXISTS idx_match_titles_title ON match_titles(title);
```

- [ ] **Step 5: Write `identity.py`**

```python
"""Identity grouping and RR p.45 unique-card matching (spec §8)."""
from __future__ import annotations

import sqlite3

IDENTITY_TYPES = ("hero", "alter_ego")


def _norm(title: str | None) -> str | None:
    return title.strip().lower() if title else None


def build(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM identity_faces")
    conn.execute("DELETE FROM identities")
    conn.execute("DELETE FROM match_titles")

    # Identities group on set_code. back_link is null on extra hero forms
    # (Archangel, Ant-Man's giant form, Wasp), so it cannot be the key.
    rows = conn.execute(
        "SELECT code, name, set_code, type_code FROM cards "
        "WHERE type_code IN (?, ?) AND set_code IS NOT NULL "
        "ORDER BY code", IDENTITY_TYPES).fetchall()

    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["set_code"], []).append(r)

    for key, faces in groups.items():
        primary = next((f for f in faces if f["type_code"] == "hero"), faces[0])
        conn.execute("INSERT INTO identities (identity_key, name) VALUES (?, ?)",
                     (key, primary["name"]))
        conn.executemany(
            "INSERT INTO identity_faces (identity_key, code) VALUES (?, ?)",
            [(key, f["code"]) for f in faces])

    _build_match_titles(conn)
    conn.commit()
    return len(groups)


def _build_match_titles(conn: sqlite3.Connection) -> None:
    """A card's match set is its own titles plus those of every face it is
    linked to. Only unique cards participate (all 653 unique player cards
    have deck_limit 1 or null, so uniqueness is the right gate)."""
    linked: dict[str, set[str]] = {}
    for r in conn.execute(
            "SELECT code, back_link FROM cards WHERE back_link IS NOT NULL"):
        linked.setdefault(r["code"], set()).add(r["back_link"])
        linked.setdefault(r["back_link"], set()).add(r["code"])

    # Faces of the same identity are linked for matching purposes.
    for r in conn.execute(
            "SELECT identity_key, code FROM identity_faces"):
        for other in conn.execute(
                "SELECT code FROM identity_faces WHERE identity_key = ?",
                (r["identity_key"],)):
            if other["code"] != r["code"]:
                linked.setdefault(r["code"], set()).add(other["code"])

    names = {r["code"]: (r["name"], r["subname"]) for r in conn.execute(
        "SELECT code, name, subname FROM cards WHERE is_unique = 1")}

    payload = []
    for code in names:
        titles: set[str] = set()
        for related in {code} | linked.get(code, set()):
            pair = names.get(related)
            if pair is None:
                # A linked face may not itself be flagged unique; its
                # title still counts toward the identity's match set.
                row = conn.execute(
                    "SELECT name, subname FROM cards WHERE code = ?",
                    (related,)).fetchone()
                pair = (row["name"], row["subname"]) if row else (None, None)
            for t in pair:
                n = _norm(t)
                if n:
                    titles.add(n)
        payload.extend((code, t) for t in titles)

    conn.executemany(
        "INSERT OR IGNORE INTO match_titles (code, title) VALUES (?, ?)",
        payload)


def titles_for(conn, code: str) -> set[str]:
    return {r["title"] for r in conn.execute(
        "SELECT title FROM match_titles WHERE code = ?", (code,))}


def matches(conn, code_a: str, code_b: str) -> bool:
    """RR p.45. Two unique cards match when their title sets overlap.

    This is why string equality on `name` fails in both directions: an
    ally can match via its subtitle, and two heroes sharing a title do
    not match when their alter-ego titles differ.
    """
    a, b = titles_for(conn, code_a), titles_for(conn, code_b)
    if not a or not b:
        return False          # non-unique cards never match
    return bool(a & b)
```

Note `matches(x, x)` on a non-unique card returns `False` because it has no rows in `match_titles` — which is what `test_non_unique_cards_never_match` asserts.

- [ ] **Step 6: Add `cards.identity`**

```python
def identity(conn, name: str) -> dict:
    row = conn.execute(
        "SELECT identity_key, name FROM identities "
        "WHERE lower(name) = lower(?)", (name,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT i.identity_key, i.name FROM identities i "
            "JOIN identity_faces f ON f.identity_key = i.identity_key "
            "JOIN cards c ON c.code = f.code "
            "WHERE lower(c.name) = lower(?) LIMIT 1", (name,)).fetchone()
    if row is None:
        return {"identity": None, "faces": [], "signature": []}

    key = row["identity_key"]
    faces = [_row(conn, r["code"]) for r in conn.execute(
        "SELECT code FROM identity_faces WHERE identity_key = ? "
        "ORDER BY code", (key,))]
    signature = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(SUMMARY)} FROM cards "
        f"WHERE set_code = ? AND type_code NOT IN ('hero', 'alter_ego') "
        f"ORDER BY code", (key,))]
    return {"identity": row["name"], "identity_key": key,
            "faces": faces, "signature": signature}


def handle_identity(args) -> int:
    conn = _open()
    result = identity(conn, args.name)
    if args.json:
        emit(result, as_json=True)
        return 0 if result["identity"] else 1
    if not result["identity"]:
        print(f"no identity named {args.name!r}")
        return 1
    print(f"{result['identity']}  [{result['identity_key']}]")
    for f in result["faces"]:
        _print_card(f)
    print(f"\nSignature set ({len(result['signature'])} cards):")
    for c in result["signature"]:
        print(f"  {c['code']:<8} {c['name']:<30} {c['type_code']}")
    return 0
```

- [ ] **Step 7: Call `identity.build` from the index build and dispatch the command**

In `index.py`, after `build_fts`, callers run `identity.build(conn)`; Task 15 wires this into `init`. In `cli.py` `_dispatch` add:

```python
    if name == "identity":
        from . import cards
        return cards.handle_identity(args)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 9: Rebuild the real index and check the named cases**

```bash
uv run python -c "
from mc_jarvis import index, identity, paths
conn = index.connect(paths.db_path())
print('identities:', identity.build(conn))
"
mc-jarvis identity Ironheart      # expect 6 faces
mc-jarvis identity Angel          # expect 3 faces including Archangel
mc-jarvis hero Spider-Man         # alias; expect 2 faces + 9 signature cards
uv run pytest tests/test_identity.py -v -m integration
```
Expected: 72 identities; the integration assertions on Black Panther pass

- [ ] **Step 10: Commit**

```bash
git add src/mc_jarvis/identity.py src/mc_jarvis/schema.py src/mc_jarvis/cards.py src/mc_jarvis/cli.py tests/
git commit -m "feat: identity grouping on set_code and RR p.45 unique-match"
```

---

## Task 8: Out-of-deck classification and the setup audit

Implements §10. Three mechanisms mark cards as sitting outside the constructed deck, **one of which is no marking at all**. The audit turns an unbounded hand-maintained list into a check that fails loudly when a new release adds an uncovered case.

**Files:**
- Create: `src/mc_jarvis/outofdeck.py`, `config/legality.yaml`
- Modify: `src/mc_jarvis/schema.py`, `tests/fixtures/cards.py`
- Test: `tests/test_outofdeck.py`

**Interfaces:**
- Produces:
  - `outofdeck.classify(conn, config: dict) -> int` — populates `out_of_deck`; returns row count
  - `outofdeck.setup_audit(conn, config: dict) -> list[AuditFinding]`
  - `outofdeck.AuditFinding` — dataclass `identity_key: str`, `identity_name: str`, `quote: str`, `covered: bool`
  - `outofdeck.AuditError` — raised when a finding is uncovered
  - `outofdeck.load_config(path: Path | None = None) -> dict`

**`config/legality.yaml` scope for this plan.** Only the `out_of_deck` section. Deck size, aspect purity, and the rest are the next plan's work.

- [ ] **Step 1: Write `config/legality.yaml`**

```yaml
# Hand-encoded deckbuilding rules (spec §10).
# THIS PLAN populates only `out_of_deck`. The remaining rules — deck size,
# aspect purity, dual-aspect, basic allowances, the Deadpool `pool`
# exception — are added in the deck-pipeline plan.
#
# Every entry here exists because no structured field marks the card.
# The setup audit fails the build when an identity implies a set-aside
# card that neither `permanent`, `hero_special`, nor this list covers.

version: 1

out_of_deck:
  # Structured mechanisms, listed for documentation. Code reads the data,
  # not these values.
  by_keyword: permanent            # spec §10 mechanism 1
  by_set_type: hero_special        # spec §10 mechanism 2

  # Mechanism 3: unmarked. Prose on the identity card is the only evidence.
  # `identity` is the identity_key (set_code); `cards` are card codes.
  exceptions:
    - identity: rogue
      cards: ["38002"]             # Touched — verify in Task 8 Step 7
      note: >-
        Rogue's identity text instructs the player to find this card and set
        it aside. The card carries deck_limit 1, quantity 1, permanent null,
        in the ordinary set — structurally indistinguishable from a normal
        signature upgrade.
    - identity: valk
      cards: ["25002"]             # Death-Glow — verify in Task 8 Step 7
      note: >-
        Brunnhilde's setup text names "Death Glow"; the card is named
        "Death-Glow". Resolution cannot be by exact name match.
        NOTE the identity key is `valk`, not `valkyrie` — the set code is
        abbreviated, and a wrong key here matches nothing and fails silent.
```

The two `cards: []` lists are filled in during Step 7 from real data, not guessed now — the audit's whole purpose is that these codes are not derivable by exact-match.

- [ ] **Step 2: Extend the fixture**

```python
# Three out-of-deck mechanisms, plus the Sp//dr ordering trap.
OUT_OF_DECK = [
    # 1. permanent
    card("ood01", "Bonded Blade", type_code="upgrade", faction_code="hero",
         set_code="edge", permanent=True, deck_limit=1, quantity=1),
    # 2. hero_special set member
    card("ood02", "Channelled Spark", type_code="event", faction_code="hero",
         set_code="edge_special", deck_limit=1, quantity=1),
    # 3. unmarked; only the identity text implies it
    card("ood03", "Kindling", type_code="upgrade", faction_code="hero",
         set_code="edge", deck_limit=1, quantity=1),
    card("ood00a", "Emberline", type_code="hero", faction_code="hero",
         set_code="edge", back_link="ood00b", deck_limit=None, quantity=1,
         text="Setup: Set the Kindling upgrade aside, out of play."),
    card("ood00b", "Sasha Vane", type_code="alter_ego", faction_code="hero",
         set_code="edge", deck_limit=None, quantity=1),
    # A normal signature card that must NOT be classified out-of-deck.
    card("ood04", "Ordinary Signature", type_code="event",
         faction_code="hero", set_code="edge", deck_limit=3, quantity=3),
]

# The Sp//dr shape: a hero face and a permanent support sharing a title.
SPDR = [
    card("spd01a", "Loomcore Rig", type_code="hero", faction_code="hero",
         set_code="loom", back_link="spd01b", is_unique=True,
         deck_limit=None, quantity=1),
    card("spd01b", "Pilot Wren", type_code="alter_ego", faction_code="hero",
         set_code="loom", is_unique=True, deck_limit=None, quantity=1),
    card("spd02", "Loomcore Rig", type_code="support", faction_code="hero",
         set_code="loom", permanent=True, is_unique=True,
         deck_limit=1, quantity=1),
]

SETS = [
    {"code": "edge", "name": "Edge", "card_set_type_code": "hero"},
    {"code": "edge_special", "name": "Edge Special",
     "card_set_type_code": "hero_special"},
    {"code": "loom", "name": "Loom", "card_set_type_code": "hero"},
]

CONFIG_COVERING_EMBERLINE = {
    "version": 1,
    "out_of_deck": {
        "by_keyword": "permanent",
        "by_set_type": "hero_special",
        "exceptions": [{"identity": "edge", "cards": ["ood03"],
                        "note": "test"}],
    },
}
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_outofdeck.py
import copy
import json
import pytest
from mc_jarvis import identity, index, outofdeck
from tests.fixtures import cards as fx


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(
        fx.PACK + fx.OUT_OF_DECK + fx.SPDR))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text(json.dumps(fx.SETS))
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    identity.build(c)
    return c


def _codes(conn, mechanism=None):
    sql = "SELECT code FROM out_of_deck"
    args = ()
    if mechanism:
        sql += " WHERE mechanism = ?"
        args = (mechanism,)
    return {r["code"] for r in conn.execute(sql, args)}


def test_permanent_cards_are_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood01" in _codes(conn, "permanent")


def test_hero_special_set_members_are_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood02" in _codes(conn, "hero_special")


def test_config_exceptions_are_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood03" in _codes(conn, "config")


def test_ordinary_signature_cards_are_not_excluded(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert "ood04" not in _codes(conn)


def test_identity_faces_are_never_in_the_deck(conn):
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert {"ood00a", "ood00b"} <= _codes(conn, "identity")


def test_audit_flags_an_uncovered_identity(conn):
    bare = copy.deepcopy(fx.CONFIG_COVERING_EMBERLINE)
    bare["out_of_deck"]["exceptions"] = []
    findings = outofdeck.setup_audit(conn, bare)
    uncovered = [f for f in findings if not f.covered]
    assert [f.identity_key for f in uncovered] == ["edge"]
    assert "Kindling" in uncovered[0].quote


def test_audit_passes_once_the_config_covers_it(conn):
    findings = outofdeck.setup_audit(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert all(f.covered for f in findings)


def test_audit_does_not_auto_resolve_by_name(conn):
    """The audit reports the quote for human review; it must not try to
    resolve prose to a card code itself (spec §10, the Death-Glow case)."""
    bare = copy.deepcopy(fx.CONFIG_COVERING_EMBERLINE)
    bare["out_of_deck"]["exceptions"] = []
    finding = outofdeck.setup_audit(conn, bare)[0]
    assert not hasattr(finding, "resolved_code")


def test_classify_raises_when_audit_is_uncovered(conn):
    bare = copy.deepcopy(fx.CONFIG_COVERING_EMBERLINE)
    bare["out_of_deck"]["exceptions"] = []
    with pytest.raises(outofdeck.AuditError, match="edge"):
        outofdeck.classify(conn, bare, strict=True)


def test_spdr_permanent_shares_a_title_with_its_hero_face(conn):
    """Both are unique and share a title, so unique-match would reject the
    deck — unless out-of-deck classification runs first (spec §10)."""
    outofdeck.classify(conn, fx.CONFIG_COVERING_EMBERLINE)
    assert identity.matches(conn, "spd01a", "spd02") is True
    assert "spd02" in _codes(conn)      # so it is removed before matching


@pytest.mark.integration
def test_real_audit_flags_the_known_identities_and_covers_them_all(real_index):
    """Verified 2026-08-21: these patterns flag eight identities, not the
    four spec §10 claims — the spec's scan was narrower. All eight must come
    back covered."""
    config = outofdeck.load_config()
    findings = outofdeck.setup_audit(real_index, config)
    keys = {f.identity_key for f in findings}
    assert {"daredevil", "doctor_strange", "hercules", "iceman",
            "ironheart", "rogue", "storm", "valk"} <= keys
    assert all(f.covered for f in findings), \
        [(f.identity_key, f.quote) for f in findings if not f.covered]


@pytest.mark.integration
def test_extra_hero_forms_are_not_blanket_exempted(real_index):
    """Angel, Ant-Man and Wasp have a third face but one alter-ego. If they
    ever gain set-aside text, the audit must still flag them."""
    for key in ("angel", "ant", "wsp"):
        n = real_index.execute(
            "SELECT COUNT(*) FROM identity_faces f JOIN cards c "
            "ON c.code = f.code WHERE f.identity_key = ? "
            "AND c.type_code = 'alter_ego'", (key,)).fetchone()[0]
        assert n == 1, key
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_outofdeck.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.outofdeck'`

- [ ] **Step 5: Add the table to `schema.py`**

```sql
CREATE TABLE IF NOT EXISTS out_of_deck (
    code      TEXT PRIMARY KEY REFERENCES cards(code),
    mechanism TEXT NOT NULL,   -- permanent | hero_special | config | identity
    note      TEXT
);
```

- [ ] **Step 6: Write `outofdeck.py`**

```python
"""Cards that sit outside the constructed deck, and the audit that keeps
the list honest (spec §10)."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "_bundled" / "legality.yaml"

# Prose on an identity card that implies a card starts outside the deck.
SETUP_PATTERNS = [
    re.compile(r"set\s+(?:it|them|this card|the\s+[^.]{1,40}?)\s+aside", re.I),
    re.compile(r"set\s+aside", re.I),
    re.compile(r"begins?\s+the\s+game\s+with", re.I),
    re.compile(r"begin\s+the\s+game\s+with", re.I),
]


class AuditError(RuntimeError):
    """An identity implies an out-of-deck card that nothing covers."""


@dataclass
class AuditFinding:
    identity_key: str
    identity_name: str
    quote: str
    covered: bool


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def _exception_codes(config: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for entry in config.get("out_of_deck", {}).get("exceptions", []) or []:
        out[entry["identity"]] = list(entry.get("cards") or [])
    return out


def setup_audit(conn: sqlite3.Connection, config: dict) -> list[AuditFinding]:
    """Scan identity text for set-aside language and report identities whose
    implied cards nothing covers.

    Reports for human review. It deliberately does not attempt to resolve
    prose to a card code: Brunnhilde's text says "Death Glow" while the
    card is "Death-Glow", so any exact-match resolution would silently
    miss it — the exact failure this audit exists to prevent.
    """
    exceptions = _exception_codes(config)
    special_type = config["out_of_deck"]["by_set_type"]

    findings: list[AuditFinding] = []
    for row in conn.execute(
        "SELECT f.identity_key, c.code, c.name, c.text "
        "FROM identity_faces f JOIN cards c ON c.code = f.code "
        "WHERE c.text IS NOT NULL AND c.text != '' ORDER BY c.code"
    ):
        for pattern in SETUP_PATTERNS:
            m = pattern.search(row["text"])
            if not m:
                continue
            key = row["identity_key"]
            sentence = _sentence_around(row["text"], m.start())

            covered = bool(exceptions.get(key))

            if not covered:
                # A hero_special set is a DIFFERENT set from the identity's
                # own (identity `iceman` -> set `iceman_frostbite`), so it
                # cannot be found by set_code. It is reliably found by pack:
                # verified 2026-08-21, pack association is exact for all six
                # hero_special sets and matches nothing else.
                covered = conn.execute(
                    "SELECT 1 FROM cards sp "
                    "JOIN sets s ON s.code = sp.set_code "
                    "WHERE s.card_set_type_code = ? AND sp.pack_code IN ("
                    "  SELECT c.pack_code FROM identity_faces f "
                    "  JOIN cards c ON c.code = f.code "
                    "  WHERE f.identity_key = ?) LIMIT 1",
                    (special_type, key)).fetchone() is not None

            if not covered:
                # A permanent card in the identity's own set.
                covered = conn.execute(
                    "SELECT 1 FROM cards WHERE set_code = ? "
                    "AND permanent = 1 LIMIT 1", (key,)).fetchone() is not None

            if not covered:
                # The Ironheart shape: multiple complete identity CARDS, so
                # "set your other identities aside" is already handled by
                # identity grouping. The discriminator is more than one
                # alter-ego face — verified 2026-08-21 to isolate Ironheart
                # alone. Counting faces > 2 instead would blanket-exempt
                # Angel, Ant-Man and Wasp, which have a second *hero* form
                # and must stay auditable.
                covered = conn.execute(
                    "SELECT COUNT(*) FROM identity_faces f "
                    "JOIN cards c ON c.code = f.code "
                    "WHERE f.identity_key = ? AND c.type_code = 'alter_ego'",
                    (key,)).fetchone()[0] > 1

            findings.append(AuditFinding(key, row["name"], sentence, covered))
            break

    return findings


def _sentence_around(text: str, pos: int) -> str:
    start = text.rfind(".", 0, pos) + 1
    end = text.find(".", pos)
    end = len(text) if end == -1 else end + 1
    return text[start:end].strip()


def classify(conn: sqlite3.Connection, config: dict, *,
             strict: bool = False) -> int:
    findings = setup_audit(conn, config)
    uncovered = [f for f in findings if not f.covered]
    if uncovered and strict:
        detail = "; ".join(
            f"{f.identity_name} ({f.identity_key}): {f.quote}"
            for f in uncovered)
        raise AuditError(
            f"{len(uncovered)} identity(ies) imply out-of-deck cards that "
            f"nothing covers — add them to legality.yaml after checking "
            f"the card names by hand: {detail}")

    conn.execute("DELETE FROM out_of_deck")
    rows: list[tuple[str, str, str | None]] = []

    for r in conn.execute("SELECT code FROM cards WHERE permanent = 1"):
        rows.append((r["code"], "permanent", None))

    for r in conn.execute(
        "SELECT c.code FROM cards c JOIN sets s ON s.code = c.set_code "
        "WHERE s.card_set_type_code = ?",
        (config["out_of_deck"]["by_set_type"],)
    ):
        rows.append((r["code"], "hero_special", None))

    # Identity faces never count toward deck size (spec §8).
    for r in conn.execute("SELECT code FROM identity_faces"):
        rows.append((r["code"], "identity", None))

    for entry in config.get("out_of_deck", {}).get("exceptions", []) or []:
        for code in entry.get("cards") or []:
            rows.append((code, "config", entry.get("note")))

    conn.executemany(
        "INSERT OR REPLACE INTO out_of_deck (code, mechanism, note) "
        "VALUES (?, ?, ?)", rows)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM out_of_deck").fetchone()[0]
```

Config ships inside the wheel at `src/mc_jarvis/_bundled/legality.yaml`. Create that directory and make `config/legality.yaml` the editable source, copied there by the build; for development, symlink it.

- [ ] **Step 7: Verify the two hand-encoded card codes against the data**

The codes in `legality.yaml` were read off the corpus on 2026-08-21 (`38002` Touched in set `rogue`; `25002` Death-Glow in set `valk`). Confirm they still hold rather than trusting them — this is the file the design twice names as its highest risk:

```bash
uv run python -c "
from mc_jarvis import index, paths
conn = index.connect(paths.db_path())
for key in ('rogue', 'valk'):
    print('---', key)
    for r in conn.execute(
        'SELECT code, name, type_code, permanent, deck_limit FROM cards '
        'WHERE set_code = ? ORDER BY code', (key,)):
        print(dict(r))
"
```
Read the output and confirm by eye that `38002` is Touched and `25002` is Death-Glow. If either has moved, correct `config/legality.yaml` and record the names you actually saw in the `note`. Note the query uses `valk`, not `valkyrie`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 9: Run the real audit**

```bash
uv run python -c "
from mc_jarvis import index, outofdeck, paths
conn = index.connect(paths.db_path())
cfg = outofdeck.load_config()
for f in outofdeck.setup_audit(conn, cfg):
    print(('OK  ' if f.covered else 'GAP '), f.identity_name, '|', f.quote)
print('classified:', outofdeck.classify(conn, cfg, strict=True))
"
```
Expected: **eight** identities — Matt Murdock, Stephen Strange, Hercules, Bobby Drake, Riri Williams, Rogue, Ororo Munroe, Brunnhilde — every one `OK`. Five are covered by a `hero_special` set found through the shared pack code, one (Ironheart) by identity grouping, and two by the config entries.

Spec §10 says this scan returns exactly four. **It returns eight** — the spec's scan did not include the `begins the game with` pattern. Eight is the correct number for the patterns in `SETUP_PATTERNS`; §10's table is the narrower result. **If any identity comes back `GAP`, that is the audit working: read the quote, find the card by eye, and add a config entry.**

- [ ] **Step 10: Commit**

```bash
git add src/mc_jarvis/outofdeck.py src/mc_jarvis/schema.py config/ tests/
git commit -m "feat: out-of-deck classification and the setup audit"
```

---

## Task 9: Card text parsing — traits, keywords, and the cost arrow

Implements §10's "card text is a rules source the fields do not capture". **The parse enriches, it never replaces:** original text is stored verbatim and is always what gets quoted back.

**Files:**
- Create: `src/mc_jarvis/cardtext.py`
- Modify: `src/mc_jarvis/schema.py`, `tests/fixtures/cards.py`
- Test: `tests/test_cardtext.py`

**Interfaces:**
- Produces:
  - `cardtext.parse_traits(text: str) -> list[str]` — `[[...]]` markup tokens
  - `cardtext.parse_arrow(text: str) -> list[CostClause]`
  - `cardtext.CostClause` — dataclass `ordinal: int`, `ability_type: str | None`, `timing: str | None`, `cost: str`, `effect: str`, `ambiguous: bool`, `raw: str`
  - `cardtext.KEYWORDS: tuple[str, ...]`
  - `cardtext.build(conn) -> dict[str, int]` — populates `card_traits`, `card_keywords`, `cost_clauses`

- [ ] **Step 1: Extend the fixture**

```python
ARROW_CARDS = [
    # Plain cost -> effect.
    card("arw01", "Simple Trade", type_code="event",
         text="<b>Action:</b> Discard a card → draw a card."),
    # Interrupt: the timing clause is NOT part of the cost (RR, spec §10).
    card("arw02", "Timed Guard", type_code="upgrade",
         text="<b>Interrupt:</b> When a character would take damage, "
              "exhaust an [[Aerial]] character you control → prevent 2 "
              "of that damage."),
    # `If ...` — undecided by the rules text; must come back ambiguous.
    card("arw03", "Conditional Swing", type_code="upgrade",
         text="<b>Action:</b> If you are in [[Tiny]] hero form, exhaust "
              "Conditional Swing → deal 1 damage."),
    # Two arrows on one card.
    card("arw04", "Double Deal", type_code="event",
         text="<b>Action:</b> Spend 1 resource → draw a card. "
              "<b>Response:</b> After you draw, discard a card → heal 1."),
    # Keywords and traits, no arrow.
    card("arw05", "Sturdy Wall", type_code="ally", traits="Tech.",
         text="Toughness. Retaliate 1. Protects [[S.H.I.E.L.D.]] allies."),
]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_cardtext.py
import json
import pytest
from mc_jarvis import cardtext, index
from tests.fixtures import cards as fx


def test_traits_come_from_markup():
    assert cardtext.parse_traits(
        "Protects [[S.H.I.E.L.D.]] and [[Aerial]] allies."
    ) == ["S.H.I.E.L.D.", "Aerial"]


def test_plain_cost_and_effect_split():
    c = cardtext.parse_arrow(
        "<b>Action:</b> Discard a card → draw a card.")[0]
    assert c.ability_type == "Action"
    assert c.timing is None
    assert c.cost == "Discard a card"
    assert c.effect == "draw a card."
    assert c.ambiguous is False


def test_interrupt_timing_is_not_part_of_the_cost():
    """Splitting on the arrow alone would report the When-clause as
    something the player must pay (spec §10)."""
    c = cardtext.parse_arrow(fx.ARROW_CARDS[1]["text"])[0]
    assert c.ability_type == "Interrupt"
    assert c.timing == "When a character would take damage"
    assert c.cost == "exhaust an [[Aerial]] character you control"
    assert "When a character" not in c.cost


def test_if_clauses_are_flagged_not_guessed():
    c = cardtext.parse_arrow(fx.ARROW_CARDS[2]["text"])[0]
    assert c.ambiguous is True
    assert c.timing is None


def test_two_arrows_produce_two_clauses():
    clauses = cardtext.parse_arrow(fx.ARROW_CARDS[3]["text"])
    assert [c.ordinal for c in clauses] == [0, 1]
    assert clauses[1].ability_type == "Response"
    assert clauses[1].timing == "After you draw"


def test_no_arrow_produces_no_clauses():
    assert cardtext.parse_arrow("Toughness. Retaliate 1.") == []


def test_raw_text_is_preserved_on_every_clause():
    for c in cardtext.parse_arrow(fx.ARROW_CARDS[3]["text"]):
        assert "→" in c.raw


def test_build_populates_all_three_tables(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.ARROW_CARDS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    conn = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(conn, root)
    counts = cardtext.build(conn)
    assert counts["traits"] >= 3
    assert counts["clauses"] == 5
    kws = {r["keyword"] for r in conn.execute(
        "SELECT keyword FROM card_keywords WHERE code = 'arw05'")}
    assert {"toughness", "retaliate"} <= kws


@pytest.mark.integration
def test_real_corpus_arrow_counts(real_index):
    total = real_index.execute(
        "SELECT COUNT(*) FROM cost_clauses").fetchone()[0]
    timed = real_index.execute(
        "SELECT COUNT(*) FROM cost_clauses WHERE timing IS NOT NULL"
    ).fetchone()[0]
    ambiguous = real_index.execute(
        "SELECT COUNT(*) FROM cost_clauses WHERE ambiguous = 1"
    ).fetchone()[0]
    assert 550 < total < 700          # 607 at time of writing
    assert 150 < timed < 260          # 196 at time of writing
    assert ambiguous < 25             # 6 at time of writing
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cardtext.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.cardtext'`

- [ ] **Step 4: Add tables to `schema.py`**

```sql
CREATE TABLE IF NOT EXISTS card_traits (
    code  TEXT NOT NULL REFERENCES cards(code),
    trait TEXT NOT NULL,
    PRIMARY KEY (code, trait)
);

CREATE TABLE IF NOT EXISTS card_keywords (
    code    TEXT NOT NULL REFERENCES cards(code),
    keyword TEXT NOT NULL,
    PRIMARY KEY (code, keyword)
);

CREATE TABLE IF NOT EXISTS cost_clauses (
    code         TEXT NOT NULL REFERENCES cards(code),
    ordinal      INTEGER NOT NULL,
    ability_type TEXT,
    timing       TEXT,
    cost         TEXT NOT NULL,
    effect       TEXT NOT NULL,
    ambiguous    INTEGER NOT NULL DEFAULT 0,
    raw          TEXT NOT NULL,   -- verbatim; always what gets quoted back
    PRIMARY KEY (code, ordinal)
);
```

- [ ] **Step 5: Write `cardtext.py`**

```python
"""Build-time card-text parsing (spec §10).

The parse enriches, it never replaces. `cards.raw` and `cost_clauses.raw`
hold the original text and are what the CLI quotes back; the split powers
structured questions the raw text cannot answer.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

ARROW = "→"

TRAIT_RE = re.compile(r"\[\[(.+?)\]\]")
BOLD_RE = re.compile(r"<b>(.*?)</b>", re.S)
TAG_RE = re.compile(r"<[^>]+>")

# A clause's timing is a When/After phrase; the RR excludes it from the
# cost for interrupts and responses.
TIMING_RE = re.compile(r"^\s*(When|After)\b(.*?),\s*(.+)$", re.S | re.I)
# `If ...` is undecided by the rules text — flag, do not guess.
CONDITION_RE = re.compile(r"^\s*If\b", re.I)

KEYWORDS = (
    "surge", "toughness", "retaliate", "piercing", "overkill", "guard",
    "stalwart", "steady", "ranged", "permanent", "patrol", "quickstrike",
    "uppercut", "peril", "hinder", "restricted", "incite", "villainous",
)
KEYWORD_RE = {k: re.compile(rf"\b{k}\b", re.I) for k in KEYWORDS}


@dataclass
class CostClause:
    ordinal: int
    ability_type: str | None
    timing: str | None
    cost: str
    effect: str
    ambiguous: bool
    raw: str


def parse_traits(text: str | None) -> list[str]:
    if not text:
        return []
    seen, out = set(), []
    for t in TRAIT_RE.findall(text):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_keywords(text: str | None) -> list[str]:
    if not text:
        return []
    plain = TAG_RE.sub(" ", text)
    return [k for k in KEYWORDS if KEYWORD_RE[k].search(plain)]


def _strip(s: str) -> str:
    return TAG_RE.sub("", s).strip().strip(".").strip()


def parse_arrow(text: str | None) -> list[CostClause]:
    if not text or ARROW not in text:
        return []

    clauses: list[CostClause] = []
    # Split the card into segments, one per arrow, by cutting after each
    # effect at the next ability-type prefix.
    segments = re.split(r"(?=<b>)", text)
    if len(segments) == 1:
        segments = [text]

    ordinal = 0
    for segment in segments:
        if ARROW not in segment:
            continue
        for piece in _split_multiple_arrows(segment):
            before, _, after = piece.partition(ARROW)

            bold = BOLD_RE.search(before)
            ability_type = None
            if bold:
                ability_type = bold.group(1).strip().rstrip(":").strip()
                before = before[bold.end():]

            timing = None
            ambiguous = False
            body = before.strip()

            if CONDITION_RE.match(TAG_RE.sub("", body).strip()):
                # The RR exempts *timing* text for interrupts and
                # responses. It says nothing about a condition on an
                # Action, so this split is undecided by the rules.
                ambiguous = True
            else:
                m = TIMING_RE.match(body)
                if m:
                    timing = _strip(f"{m.group(1)}{m.group(2)}")
                    body = m.group(3)

            clauses.append(CostClause(
                ordinal=ordinal,
                ability_type=ability_type,
                timing=timing,
                cost=_strip(body),
                effect=TAG_RE.sub("", after).strip(),
                ambiguous=ambiguous,
                raw=piece.strip(),
            ))
            ordinal += 1

    return clauses


def _split_multiple_arrows(segment: str) -> list[str]:
    """A segment with N arrows and no <b> boundary between them is treated
    as N clauses split at sentence ends."""
    if segment.count(ARROW) <= 1:
        return [segment]
    parts, buf = [], ""
    for sentence in re.split(r"(?<=\.)\s+", segment):
        buf = f"{buf} {sentence}".strip()
        if ARROW in buf:
            parts.append(buf)
            buf = ""
    if buf and ARROW in buf:
        parts.append(buf)
    return parts or [segment]


def build(conn: sqlite3.Connection) -> dict[str, int]:
    for table in ("card_traits", "card_keywords", "cost_clauses"):
        conn.execute(f"DELETE FROM {table}")

    traits, keywords, clauses = [], [], []
    for row in conn.execute(
            "SELECT code, text FROM cards WHERE text IS NOT NULL"):
        code, text = row["code"], row["text"]
        traits.extend((code, t) for t in parse_traits(text))
        keywords.extend((code, k) for k in parse_keywords(text))
        clauses.extend(
            (code, c.ordinal, c.ability_type, c.timing, c.cost, c.effect,
             int(c.ambiguous), c.raw)
            for c in parse_arrow(text))

    conn.executemany(
        "INSERT OR IGNORE INTO card_traits (code, trait) VALUES (?, ?)",
        traits)
    conn.executemany(
        "INSERT OR IGNORE INTO card_keywords (code, keyword) VALUES (?, ?)",
        keywords)
    conn.executemany(
        "INSERT OR REPLACE INTO cost_clauses "
        "(code, ordinal, ability_type, timing, cost, effect, ambiguous, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", clauses)
    conn.commit()
    return {"traits": len(traits), "keywords": len(keywords),
            "clauses": len(clauses)}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cardtext.py -v -m "not integration"`
Expected: PASS, 8 tests

- [ ] **Step 7: Check the parse against the real corpus and eyeball the ambiguous set**

```bash
uv run python -c "
from mc_jarvis import cardtext, index, paths
conn = index.connect(paths.db_path())
print(cardtext.build(conn))
for r in conn.execute('SELECT code, raw FROM cost_clauses WHERE ambiguous = 1'):
    print('AMBIGUOUS', r['code'], r['raw'][:110])
print()
for r in conn.execute('SELECT code, timing, cost FROM cost_clauses '
                      'WHERE timing IS NOT NULL LIMIT 10'):
    print(r['code'], '| timing:', r['timing'], '| cost:', r['cost'])
"
uv run pytest tests/test_cardtext.py -v -m integration
```
Expected: roughly 607 clauses, ~196 with timing, single-digit ambiguous. **Read the timing/cost pairs.** If a timing clause has leaked into a cost, that is the failure this task exists to prevent — fix and re-run before committing.

- [ ] **Step 8: Commit**

```bash
git add src/mc_jarvis/cardtext.py src/mc_jarvis/schema.py tests/
git commit -m "feat: parse traits, keywords, and cost-arrow clauses from card text"
```

---

## Task 10: `mc-jarvis encounter`

Implements §5.1. Card-data only; no new dependencies.

**Files:**
- Modify: `src/mc_jarvis/cards.py`, `src/mc_jarvis/cli.py`
- Test: `tests/test_encounter.py`

**Interfaces:**
- Produces: `cards.encounter(conn, name: str) -> dict`, `cards.handle_encounter(args) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_encounter.py
import json
import pytest
from mc_jarvis import cards, index
from tests.fixtures import cards as fx

ENCOUNTER = [
    fx.card("enc01", "The Collector", type_code="villain",
            faction_code="encounter", set_code="collector",
            health=12, attack=2, thwart=2, quantity=1, deck_limit=None,
            text="Stage 1."),
    fx.card("enc02", "The Collector", type_code="villain",
            faction_code="encounter", set_code="collector",
            health=16, attack=3, thwart=2, quantity=1, deck_limit=None,
            text="Stage 2."),
    fx.card("enc03", "Gathering Swarm", type_code="minion",
            faction_code="encounter", set_code="collector",
            health=3, attack=1, thwart=1, quantity=3, deck_limit=None),
]


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.PACK + ENCOUNTER))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text(json.dumps(
        [{"code": "collector", "name": "The Collector",
          "card_set_type_code": "villain"}]))
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    return c


def test_villain_stages_are_returned_in_order(conn):
    result = cards.encounter(conn, "The Collector")
    assert [v["health"] for v in result["villain"]] == [12, 16]


def test_set_contents_include_quantities(conn):
    result = cards.encounter(conn, "The Collector")
    swarm = next(c for c in result["contents"]
                 if c["name"] == "Gathering Swarm")
    assert swarm["quantity"] == 3


def test_lookup_by_set_code_works(conn):
    assert cards.encounter(conn, "collector")["set_code"] == "collector"


def test_unknown_set_returns_empty(conn):
    assert cards.encounter(conn, "Nobody")["set_code"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_encounter.py -v`
Expected: FAIL — `AttributeError: module 'mc_jarvis.cards' has no attribute 'encounter'`

- [ ] **Step 3: Implement `encounter` in `cards.py`**

```python
def encounter(conn, name: str) -> dict:
    row = conn.execute(
        "SELECT code, name FROM sets WHERE lower(code) = lower(?) "
        "   OR lower(name) = lower(?)", (name, name)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT s.code, s.name FROM sets s JOIN cards c "
            "  ON c.set_code = s.code "
            "WHERE lower(c.name) = lower(?) AND c.faction_code = 'encounter' "
            "LIMIT 1", (name,)).fetchone()
    if row is None:
        return {"set_code": None, "set_name": None,
                "villain": [], "contents": []}

    contents = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(SUMMARY)}, quantity, health, attack, thwart, "
        f"       defense "
        f"FROM cards WHERE set_code = ? ORDER BY code", (row["code"],))]
    villain = [c for c in contents if c["type_code"] == "villain"]
    return {"set_code": row["code"], "set_name": row["name"],
            "villain": villain, "contents": contents}


def handle_encounter(args) -> int:
    conn = _open()
    result = encounter(conn, args.name)
    if args.json:
        emit(result, as_json=True)
        return 0 if result["set_code"] else 1
    if not result["set_code"]:
        print(f"no encounter set matching {args.name!r}")
        return 1
    print(f"{result['set_name']}  [{result['set_code']}]")
    for v in result["villain"]:
        print(f"  {v['name']:<28} HP {v['health']}  "
              f"ATK {v['attack']}  THW {v['thwart']}")
    print(f"\nSet contents ({len(result['contents'])} cards):")
    for c in result["contents"]:
        print(f"  {c['quantity']}x {c['name']:<30} {c['type_code']}")
    return 0
```

Villain hit points scale by player count at the table rather than living in separate rows, so `--difficulty` is deliberately absent; the printed value is the base. Note this in `SKILL.md` (Task 16).

- [ ] **Step 4: Dispatch it** — in `cli.py` `_dispatch`: `if name == "encounter": from . import cards; return cards.handle_encounter(args)`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 6: Exercise against real data**

```bash
mc-jarvis encounter "Rhino"
mc-jarvis encounter "Klaw" --json
```

- [ ] **Step 7: Commit**

```bash
git add src/mc_jarvis/cards.py src/mc_jarvis/cli.py tests/test_encounter.py
git commit -m "feat: encounter set and villain lookup"
```

---

## Task 11: The rules manifest

Implements §11. FFG's product page returns HTTP 403 to plain HTTP clients regardless of headers, so **`--from-html` is the default path**, not a fallback: it is the only one that works on an agent with no browser capability at all.

> **This is the least-verified component in the plan.** Every other data-shaped task was checked against real data while planning; the FFG page was not, because it returns 403 to plain HTTP clients and no saved copy was available. `tests/fixtures/ffg_page.html` is therefore built from an *assumption* about the page's markup — precisely the shape that produced the `See also` failure in Task 13.
>
> **Do Step 6 before Step 1.** Save the real page first, look at how the title, size, and date actually sit relative to the anchor, and shape the fixture from what you see. If `_Collector` as written does not fit that markup, rewrite it — it is a guess, not a finding.

**Files:**
- Create: `src/mc_jarvis/manifest.py`
- Test: `tests/fixtures/ffg_page.html`, `tests/test_manifest.py`

**Interfaces:**
- Produces:
  - `manifest.parse(html: str) -> list[RuleDoc]`
  - `manifest.RuleDoc` — dataclass `title: str`, `url: str`, `size: str | None`, `date: str | None`, `slug: str`
  - `manifest.write(docs: list[RuleDoc], path: Path) -> None`
  - `manifest.read(path: Path) -> list[RuleDoc]`
  - `manifest.diff(old: list[RuleDoc], new: list[RuleDoc]) -> list[tuple[str, str]]` — `(slug, reason)` for added or revised documents
  - `manifest.DEFAULT_SLUGS: tuple[str, ...]` — Rules Reference and Learn to Play
  - `manifest.fetch_with_browser() -> str` — Playwright; raises `RuntimeError` when the extra is absent

- [ ] **Step 1: Write the fixture**

Hand-written, mimicking the page's structure without reproducing FFG's page. Save as `tests/fixtures/ffg_page.html`:

```html
<html><body>
<div class="product-support">
  <a href="https://images-cdn.example.invalid/filer_public/aa/bb/rules_ref_v18.pdf">
     Rules Reference</a>
  <span class="size">(3.4 MB)</span><span class="date">Updated 22 Jul 2026</span>
  <a href="https://images-cdn.example.invalid/filer_public/cc/dd/learn_to_play.pdf">
     Learn to Play</a>
  <span class="size">(2.1 MB)</span><span class="date">Updated 01 Oct 2019</span>
  <a href="https://images-cdn.example.invalid/filer_public/ee/ff/galaxy_rules.pdf">
     Galaxy&rsquo;s Most Wanted Rules</a>
  <span class="size">(1.2 MB)</span><span class="date">Updated 03 Mar 2020</span>
  <a href="/en/products/marvel-champions/">Not a PDF</a>
</div>
</body></html>
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_manifest.py
import json
from pathlib import Path
import pytest
from mc_jarvis import manifest

FIXTURE = Path(__file__).parent / "fixtures" / "ffg_page.html"


@pytest.fixture
def docs():
    return manifest.parse(FIXTURE.read_text())


def test_only_pdf_links_are_collected(docs):
    assert len(docs) == 3
    assert all(d.url.endswith(".pdf") for d in docs)


def test_titles_are_cleaned(docs):
    assert docs[0].title == "Rules Reference"
    assert "Galaxy" in docs[2].title


def test_slugs_are_stable_and_filesystem_safe(docs):
    assert docs[0].slug == "rules-reference"
    assert "/" not in docs[2].slug and " " not in docs[2].slug


def test_default_slugs_are_present_in_a_realistic_page(docs):
    slugs = {d.slug for d in docs}
    assert set(manifest.DEFAULT_SLUGS) <= slugs


def test_roundtrip_through_disk(tmp_path, docs):
    path = tmp_path / "manifest.json"
    manifest.write(docs, path)
    assert manifest.read(path) == docs


def test_diff_reports_a_revised_document(docs):
    newer = [manifest.RuleDoc(**{**d.__dict__}) for d in docs]
    newer[0].date = "Updated 01 Jan 2027"
    changes = dict(manifest.diff(docs, newer))
    assert changes["rules-reference"] == "revised"


def test_diff_reports_an_added_document(docs):
    changes = dict(manifest.diff(docs[:2], docs))
    assert changes["galaxys-most-wanted-rules"] == "added"


def test_diff_is_empty_when_nothing_changed(docs):
    assert manifest.diff(docs, docs) == []
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.manifest'`

- [ ] **Step 4: Write `manifest.py`**

`html.parser` from the stdlib is used rather than a dependency; the parse is one pass over anchors.

```python
"""FFG product page -> rules manifest (spec §11)."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path

PRODUCT_PAGE = ("https://www.fantasyflightgames.com/en/products/"
                "marvel-champions-the-card-game/")
DEFAULT_SLUGS = ("rules-reference", "learn-to-play")

SIZE_RE = re.compile(r"\(([\d.]+\s*[KMG]B)\)", re.I)
DATE_RE = re.compile(r"(Updated\s+.+?\d{4})", re.I)


@dataclass
class RuleDoc:
    title: str
    url: str
    size: str | None = None
    date: str | None = None
    slug: str = ""


def slugify(title: str) -> str:
    norm = unicodedata.normalize("NFKD", title)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = re.sub(r"[^\w\s-]", "", norm).strip().lower()
    return re.sub(r"[\s_]+", "-", norm)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.docs: list[RuleDoc] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._tail: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        self._flush()
        href = dict(attrs).get("href", "")
        self._href = href if href.lower().endswith(".pdf") else None
        self._text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            title = " ".join("".join(self._text).split())
            self.docs.append(RuleDoc(title=title, url=self._href,
                                     slug=slugify(title)))
            self._href = None
            self._tail = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
        elif self.docs:
            self._tail.append(data)
            self._apply_tail()

    def _apply_tail(self) -> None:
        blob = " ".join(self._tail)
        doc = self.docs[-1]
        if doc.size is None:
            m = SIZE_RE.search(blob)
            if m:
                doc.size = m.group(1)
        if doc.date is None:
            m = DATE_RE.search(blob)
            if m:
                doc.date = m.group(1).strip()

    def _flush(self) -> None:
        self._tail = []


def parse(html: str) -> list[RuleDoc]:
    c = _Collector()
    c.feed(html)
    seen, out = set(), []
    for doc in c.docs:
        if doc.url in seen:
            continue
        seen.add(doc.url)
        out.append(doc)
    return out


def write(docs: list[RuleDoc], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(d) for d in docs], indent=2),
                    encoding="utf-8")


def read(path: Path) -> list[RuleDoc]:
    if not path.exists():
        return []
    return [RuleDoc(**d) for d in json.loads(path.read_text(encoding="utf-8"))]


def diff(old: list[RuleDoc], new: list[RuleDoc]) -> list[tuple[str, str]]:
    by_slug = {d.slug: d for d in old}
    changes = []
    for doc in new:
        prev = by_slug.get(doc.slug)
        if prev is None:
            changes.append((doc.slug, "added"))
        elif prev.date != doc.date or prev.url != doc.url:
            changes.append((doc.slug, "revised"))
    return changes


def fetch_with_browser() -> str:
    """`init --browser`. The FFG page requires a real browser engine; a
    plain urllib request returns 403 whatever headers are sent."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "the browser extra is not installed. Either run\n"
            "  uv tool install 'mc-jarvis[browser]' && playwright install chromium\n"
            "or use the default path: save the product page as HTML and run\n"
            f"  mc-jarvis init --from-html page.html\n"
            f"The page is at {PRODUCT_PAGE}") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(PRODUCT_PAGE, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: PASS, 8 tests

- [ ] **Step 6: Verify against the real page**

Save the real product page to `/tmp/ffg.html` using any browser (or an agent's browser tool), then:

```bash
uv run python -c "
from pathlib import Path
from mc_jarvis import manifest
docs = manifest.parse(Path('/tmp/ffg.html').read_text())
print(len(docs), 'PDFs')
for d in docs[:8]: print(' ', d.slug, '|', d.title, '|', d.size, '|', d.date)
print('defaults present:',
      set(manifest.DEFAULT_SLUGS) <= {d.slug for d in docs})
"
```
Expected: around 91 PDFs; both default slugs present, **each with a non-null `date`**.

Two ways this fails quietly, both worth checking here rather than later:

- If `rules-reference` is not among the slugs, the page title differs from the assumption — fix `DEFAULT_SLUGS`, not the slugifier.
- If `date` is `None`, `manifest.diff` can never report `revised`, and `update`'s only rules-staleness signal is dead. `_Collector` reads size and date from text *following* the anchor; if the real page puts them before it, move the capture rather than shipping the feature inert.

```bash
uv run python -c "
from pathlib import Path
from mc_jarvis import manifest
docs = {d.slug: d for d in manifest.parse(Path('/tmp/ffg.html').read_text())}
for slug in manifest.DEFAULT_SLUGS:
    d = docs.get(slug)
    assert d, f'missing slug: {slug}'
    assert d.date, f'{slug} has no date — manifest.diff cannot detect revisions'
    print(slug, '|', d.date, '|', d.size)
print('OK')
"
```

- [ ] **Step 7: Commit**

```bash
git add src/mc_jarvis/manifest.py tests/
git commit -m "feat: parse the FFG product page into a rules manifest"
```

---

## Task 12: PDF download and text extraction

Implements §9 and §6. Two backends behind one interface: `pypdf` by default, `pdftotext -raw` when poppler is present. **Column order is the constraint that disqualifies otherwise reasonable libraries** — do not substitute `pdfplumber` or `pdftotext -layout`.

**Files:**
- Create: `src/mc_jarvis/pdf.py`
- Test: `tests/test_pdf.py`

**Interfaces:**
- Produces:
  - `pdf.download(url: str, dest: Path) -> Path`
  - `pdf.extract_pages(path: Path, *, backend: str | None = None) -> list[str]` — one string per page, 1-indexed by list position
  - `pdf.available_backends() -> list[str]`
  - `pdf.PdfError` — exception

- [ ] **Step 1: Write the failing test**

The test generates its own two-column PDF so no FFG content is committed and column order is genuinely exercised.

```python
# tests/test_pdf.py
import pytest
from mc_jarvis import pdf


@pytest.fixture
def two_column_pdf(tmp_path):
    """A real two-column PDF, written with pypdf's own writer so the test
    needs no external tooling."""
    from pypdf import PdfWriter
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed; run with --with reportlab")
    path = tmp_path / "two_col.pdf"
    c = canvas.Canvas(str(path))
    for line, y in enumerate(range(700, 500, -20)):
        c.drawString(60, y, f"LEFT{line}")
        c.drawString(330, y, f"RIGHT{line}")
    c.showPage()
    c.drawString(60, 700, "PAGE2")
    c.save()
    return path


def test_pages_are_returned_one_per_page(two_column_pdf):
    pages = pdf.extract_pages(two_column_pdf)
    assert len(pages) == 2
    assert "PAGE2" in pages[1]


def test_columns_are_not_interleaved(two_column_pdf):
    """The failure this guards: LEFT0 RIGHT0 LEFT1 RIGHT1 ... instead of
    the whole left column then the whole right (spec §9)."""
    text = pdf.extract_pages(two_column_pdf)[0]
    assert text.index("LEFT0") < text.index("LEFT9")
    assert text.index("LEFT9") < text.index("RIGHT0")


def test_unknown_backend_is_rejected(two_column_pdf):
    with pytest.raises(pdf.PdfError, match="unknown backend"):
        pdf.extract_pages(two_column_pdf, backend="pdfplumber")


def test_available_backends_always_includes_pypdf():
    assert "pypdf" in pdf.available_backends()


def test_missing_file_raises_clearly(tmp_path):
    with pytest.raises(pdf.PdfError, match="not found"):
        pdf.extract_pages(tmp_path / "nope.pdf")
```

Add `reportlab` to the dev extra in `pyproject.toml` (`dev = ["pytest>=8.0", "reportlab>=4.0"]`). It is a **test-only** dependency and must not appear in `dependencies`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_pdf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.pdf'`

- [ ] **Step 3: Write `pdf.py`**

```python
"""PDF acquisition and text extraction (spec §6, §9).

Only two extractors read the two-column Rules Reference in the correct
column order: pypdf, and `pdftotext -raw`. `pdftotext -layout` and
pdfplumber interleave the columns into unusable text — do not add them.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path

PAGE_BREAK = "\f"
USER_AGENT = "mc-jarvis"


class PdfError(RuntimeError):
    pass


def available_backends() -> list[str]:
    backends = []
    if shutil.which("pdftotext"):
        backends.append("pdftotext")
    try:
        import pypdf  # noqa: F401
        backends.append("pypdf")
    except ImportError:
        pass
    return backends


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
    except Exception as exc:
        raise PdfError(f"could not download {url}: {exc}") from exc
    return dest


def extract_pages(path: Path, *, backend: str | None = None) -> list[str]:
    path = Path(path)
    if not path.exists():
        raise PdfError(f"PDF not found: {path}")

    if backend is None:
        backend = "pdftotext" if shutil.which("pdftotext") else "pypdf"
    if backend not in ("pdftotext", "pypdf"):
        raise PdfError(
            f"unknown backend {backend!r}; only 'pypdf' and 'pdftotext' "
            f"read the two-column Rules Reference in the correct order "
            f"(spec §9)")

    if backend == "pdftotext":
        return _extract_pdftotext(path)
    return _extract_pypdf(path)


def _extract_pdftotext(path: Path) -> list[str]:
    # -raw preserves reading order and the >> sub-bullet marker.
    proc = subprocess.run(
        ["pdftotext", "-raw", str(path), "-"],
        capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise PdfError(f"pdftotext failed: {proc.stderr.decode()[:400]}")
    text = proc.stdout.decode("utf-8", errors="replace")
    pages = text.split(PAGE_BREAK)
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _extract_pypdf(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfError("pypdf is not installed") from exc
    reader = PdfReader(str(path))
    return [(page.extract_text() or "") for page in reader.pages]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_pdf.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Verify both backends agree on the real Rules Reference**

```bash
uv run python -c "
from pathlib import Path
from mc_jarvis import pdf
p = Path('/tmp/rr.pdf')
pdf.download('<the Rules Reference URL from your manifest>', p)
for backend in pdf.available_backends():
    pages = pdf.extract_pages(p, backend=backend)
    print(backend, len(pages), 'pages;',
          'index on p2:', 'INDEX' in pages[1])
"
```
Expected: 71 pages from each backend; `INDEX` present on page 2 for both. **If the page count differs between backends, stop — the chunker in Task 13 assumes page indices are comparable.**

- [ ] **Step 6: Commit**

```bash
git add src/mc_jarvis/pdf.py tests/test_pdf.py pyproject.toml
git commit -m "feat: PDF download and two-backend text extraction"
```

---

## Task 13: Rules chunking — the RR index, glyphs, and entry bodies

Implements §9, **with a correction to it**. The spec proposed finding entries with an ALL-CAPS regex over the body. Verified on 2026-08-21: **the Rules Reference carries its own index on PDF pages 2–3**, listing 216 entries with page numbers plus 46 `See …` redirects. That index is authoritative and is now the primary source; the ALL-CAPS scan is demoted to a cross-check.

The same index also names every icon, so **`config/glyphs.yaml` is derived and reviewed rather than hand-authored** — all 13 private-use codepoints used in the body are covered, none unmapped.

**Files:**
- Create: `src/mc_jarvis/rules_chunk.py`, `config/glyphs.yaml`
- Modify: `src/mc_jarvis/schema.py`
- Test: `tests/fixtures/rr_like.txt`, `tests/test_rules_chunk.py`

**Interfaces:**
- Produces:
  - `rules_chunk.parse_index(pages: list[str]) -> IndexResult`
  - `rules_chunk.IndexResult` — dataclass `entries: list[tuple[str, int]]`, `redirects: list[tuple[str, str]]`, `glyphs: dict[str, str]`
  - `rules_chunk.chunk_entries(pages, index: IndexResult, *, source_doc: str) -> list[Entry]`
  - `rules_chunk.chunk_pages(pages, *, source_doc: str) -> list[Entry]` — for non-RR documents
  - `rules_chunk.Entry` — dataclass `term: str`, `body: str`, `page: int`, `source_doc: str`, `entry_addressable: bool`, `see_also: list[str]`
  - `rules_chunk.apply_glyphs(text: str, mapping: dict[str, str]) -> tuple[str, set[str]]` — returns text and the set of unmapped codepoints
  - `rules_chunk.load_glyphs(path=None) -> dict[str, str]`
  - `rules_chunk.store(conn, entries: list[Entry]) -> int`

- [ ] **Step 1: Write the text fixture**

`tests/fixtures/rr_like.txt` — shaped like real extractor output, invented content, one private-use codepoint (U+F521) and one unmapped one (U+F5FF). Pages separated by form feeds:

```
COVER PAGE
\f
INDEXINDEX
Aether Surge ....................................3
Amplify Icon (\uf521) ...........................3
"Bolstered" ............. See Aether Surge
Cascade .............................................4
Warding ..............................................4
\f
GLOSSARYGLOSSARY
AETHER SURGE
When a card instructs you to surge aether, add one
token to the pool.
See also : Cascade, Warding
AMPLIFY ICON (\uf521)
The \uf521 icon marks an amplified effect. Unknown
glyph follows: \uf5ff
\f
CASCADE
A cascade resolves each effect in turn.
WARDING
Warding prevents the next point of damage.
```

Write it with a short script so the escapes become real codepoints:

```bash
uv run python - <<'PY'
from pathlib import Path
p = Path("tests/fixtures/rr_like.txt")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(RAW.replace("\\uf521", "\uf521").replace("\\uf5ff", "\uf5ff")
             .replace("\\f", "\f"), encoding="utf-8")
PY
```
(Set `RAW` to the block above.)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_rules_chunk.py
from pathlib import Path
import pytest
from mc_jarvis import index, rules_chunk

FIXTURE = Path(__file__).parent / "fixtures" / "rr_like.txt"


@pytest.fixture
def pages():
    return FIXTURE.read_text(encoding="utf-8").split("\f")


def test_index_yields_entries_with_pages(pages):
    result = rules_chunk.parse_index(pages)
    assert ("Aether Surge", 3) in result.entries
    assert ("Warding", 4) in result.entries


def test_index_separates_redirects_from_entries(pages):
    result = rules_chunk.parse_index(pages)
    assert ("“Bolstered”", "Aether Surge") in result.redirects or \
           ('"Bolstered"', "Aether Surge") in result.redirects
    assert not any(t == "Bolstered" for t, _ in result.entries)


def test_glyph_names_are_derived_from_the_index(pages):
    result = rules_chunk.parse_index(pages)
    assert result.glyphs["\uf521"] == "Amplify Icon"


def test_entries_carry_body_and_page(pages):
    result = rules_chunk.parse_index(pages)
    entries = rules_chunk.chunk_entries(pages, result, source_doc="rr")
    surge = next(e for e in entries if e.term == "Aether Surge")
    assert "add one" in surge.body
    assert surge.page == 3
    assert surge.entry_addressable is True


def test_see_also_is_extracted(pages):
    """The RR prints "See also :" with a space before the colon and wraps
    the list over several lines. A regex tuned to "See also:" matches
    nothing in real output, and the failure is silent."""
    result = rules_chunk.parse_index(pages)
    entries = rules_chunk.chunk_entries(pages, result, source_doc="rr")
    surge = next(e for e in entries if e.term == "Aether Surge")
    assert surge.see_also == ["Cascade", "Warding"]
    assert "See also" not in surge.body


def test_see_also_survives_line_wrapping():
    body = ("Some rules text.\n"
            "See also : Action, Alteration Effect, Cancel,\n"
            "Delayed Effect, Forced")
    m = rules_chunk.SEE_ALSO_RE.search(body)
    assert m
    targets = [s.strip() for s in m.group(1).replace("\n", " ").split(",")]
    assert "Delayed Effect" in targets
    assert "Forced" in targets


def test_mapped_glyphs_become_readable_tokens():
    out, unmapped = rules_chunk.apply_glyphs(
        "The \uf521 icon", {"\uf521": "amplify"})
    assert out == "The [amplify] icon"
    assert unmapped == set()


def test_unmapped_glyphs_are_preserved_and_reported():
    out, unmapped = rules_chunk.apply_glyphs("x \uf5ff y", {})
    assert "\uf5ff" in out          # preserved verbatim, never stripped
    assert unmapped == {"\uf5ff"}


def test_quoted_and_icon_headers_are_not_rejected():
    """Requiring ^[A-Z] silently dropped 36 of 216 entries: every quoted
    term and every icon entry."""
    for header in ('\u201cAFTER\u201d', '\u201cAND\u201d', "ACCELERATION ICON ( )",
                   "COST ARROW ICON ( \u2192)", "ALTER-EGO, ALTER-EGO FORM"):
        assert rules_chunk.HEADER_RE.match(header), header


def test_match_key_bridges_index_and_body_spellings():
    k = rules_chunk.match_key
    assert k("Delayed Effects") == k("DELAYED EFFECT")
    assert k("Boost, Boost Icon (\uf520)") == k("BOOST")
    assert k("Alter-Ego, Alter-Ego Form") == k("ALTER-EGO, ALTER-EGO FORM")
    assert k("Golden Rules") == k("THE GOLDEN RULES")
    assert k("Ability") != k("Abilities Reference")


def test_bodies_do_not_overlap(pages):
    """The earlier locator produced 106% coverage - entries running past
    their end into the next one. A partition cannot."""
    result = rules_chunk.parse_index(pages)
    entries = [e for e in rules_chunk.chunk_entries(
        pages, result, source_doc="rr") if e.page is not None and e.body]
    joined = "".join(e.body for e in entries)
    glossary = "".join(pages[2:])
    assert len(joined.replace(" ", "")) <= len(glossary.replace(" ", ""))


def test_extraction_report_names_what_it_could_not_resolve(pages):
    result = rules_chunk.parse_index(pages)
    rep = rules_chunk.extraction_report(pages, result)
    assert rep["resolved"] + len(rep["unresolved"]) == rep["index_entries"]


def test_an_entry_continues_across_a_page_break(pages):
    """ABILITY starts on p.4 and its timing chart is on p.5. Stopping at
    the page boundary would drop the chart without any error."""
    spanning = ["", "INDEXINDEX\nAbility ....1\nZulu ....2",
                "ABILITY\nFirst part.", "Second part.\nZULU\nUnrelated."]
    idx = rules_chunk.parse_index(spanning, scan_pages=2)
    entries = rules_chunk.chunk_entries(spanning, idx, source_doc="rr")
    body = next(e for e in entries if e.term == "Ability").body
    assert "First part." in body
    assert "Second part." in body
    assert "Unrelated." not in body


def test_non_rr_documents_chunk_by_page(pages):
    entries = rules_chunk.chunk_pages(pages, source_doc="ltp")
    assert all(e.entry_addressable is False for e in entries)
    assert entries[0].page == 1


def test_store_is_idempotent(tmp_path, pages):
    conn = index.connect(tmp_path / "mc.sqlite")
    result = rules_chunk.parse_index(pages)
    entries = rules_chunk.chunk_entries(pages, result, source_doc="rr")
    rules_chunk.store(conn, entries)
    n = rules_chunk.store(conn, entries)
    assert n == len(entries)


@pytest.mark.integration
def test_real_extraction_resolves_almost_every_entry(real_index):
    """The gate from Task 13 Step 8, enforced. Measured 2026-08-21:
    207 of 216 resolved at 91% coverage."""
    row = real_index.execute(
        "SELECT value FROM build_meta WHERE key = 'extraction_report'"
    ).fetchone()
    assert row is not None, "init did not write the extraction report"
    import json as _j
    rep = _j.loads(row["value"])
    assert rep["resolved"] >= 205, rep["unresolved"]
    assert rep["coverage"] >= 0.88, rep["coverage"]


@pytest.mark.integration
def test_real_rules_reference_index(real_index):
    n = real_index.execute(
        "SELECT COUNT(*) FROM rules_entries WHERE source_doc = "
        "'rules-reference' AND entry_addressable = 1").fetchone()[0]
    assert 190 < n < 240              # 216 at time of writing


@pytest.mark.integration
def test_no_unmapped_glyphs_in_the_real_rules(real_index):
    row = real_index.execute(
        "SELECT value FROM build_meta WHERE key = 'unmapped_glyphs'"
    ).fetchone()
    assert row is None or row["value"] == "", \
        f"unmapped glyph codepoints: {row['value']}"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rules_chunk.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.rules_chunk'`

- [ ] **Step 4: Add tables to `schema.py`**

```sql
CREATE TABLE IF NOT EXISTS rules_entries (
    id                INTEGER PRIMARY KEY,
    term              TEXT NOT NULL,
    body              TEXT NOT NULL,
    page              INTEGER,
    source_doc        TEXT NOT NULL,
    entry_addressable INTEGER NOT NULL DEFAULT 1,
    UNIQUE (source_doc, term, page)
);
CREATE INDEX IF NOT EXISTS idx_rules_term ON rules_entries(lower(term));

CREATE TABLE IF NOT EXISTS rules_see_also (
    term       TEXT NOT NULL,
    target     TEXT NOT NULL,
    source_doc TEXT NOT NULL,
    PRIMARY KEY (source_doc, term, target)
);

CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(
    term, body, content='rules_entries', content_rowid='id'
);
```

- [ ] **Step 5: Write `rules_chunk.py`**

```python
"""Rules Reference chunking (spec §9, as corrected).

The RR carries its own index on PDF pages 2-3: 216 entries with page
numbers and 46 `See ...` redirects. That is the authoritative entry list.
The ALL-CAPS body scan is a cross-check, not the source of truth, because
a candidate is not an entry — the naive regex yields 386 candidates over
71 pages, and the surplus are diagram labels and worked examples.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

GLYPHS_PATH = Path(__file__).parent / "_bundled" / "glyphs.yaml"
PUA = re.compile(r"[\ue000-\uf8ff]")

# "Term ......... 14"  (leaders may be spaced)
ENTRY_RE = re.compile(r"^(.*?)[\s.]*\.{2,}[\s.]*(\d{1,3})$")
# "Term ..... See Other Term"
REDIRECT_RE = re.compile(r"^(.*?)\.*\s*See\s+(.+)$")
# "Amplify Icon ()" — the glyph sits between the parentheses
GLYPH_NAME_RE = re.compile(r"^(.*?)\s*\(([\ue000-\uf8ff])\s*\)$")
# The RR prints "See also :" with a space before the colon, and the list
# wraps over several lines to the end of the entry. Verified 2026-08-21:
# the tighter `See also:\s*(.+)$` matched nothing in the real document.
SEE_ALSO_RE = re.compile(r"^[ \t]*See\s+also\s*:\s*(.+)\Z", re.M | re.S)
HEADER_RE = re.compile(
    r"^[\u201c\"']?[A-Z][A-Z0-9 ,\u2019'\u201c\u201d/&()\u2192.\u2013\u2014-]{2,60}$")


@dataclass
class IndexResult:
    entries: list[tuple[str, int]] = field(default_factory=list)
    redirects: list[tuple[str, str]] = field(default_factory=list)
    glyphs: dict[str, str] = field(default_factory=dict)


@dataclass
class Entry:
    term: str
    body: str
    page: int | None
    source_doc: str
    entry_addressable: bool = True
    see_also: list[str] = field(default_factory=list)


def parse_index(pages: list[str], *, scan_pages: int = 3) -> IndexResult:
    result = IndexResult()
    blob = "\n".join(pages[1:scan_pages])
    buf = ""
    for line in (l.rstrip() for l in blob.split("\n")):
        if not line.strip() or line.strip().upper().startswith("INDEX"):
            continue
        buf = f"{buf} {line}".strip() if buf else line.strip()

        m = ENTRY_RE.match(buf)
        if m:
            term = m.group(1).strip().strip(".").strip()
            if term:
                result.entries.append((term, int(m.group(2))))
            buf = ""
            continue

        m = REDIRECT_RE.match(buf)
        if m and not buf.rstrip().endswith(","):
            result.redirects.append(
                (m.group(1).strip().strip(".").strip(), m.group(2).strip()))
            buf = ""

    for term, _ in result.entries + [(t, None) for t, _ in result.redirects]:
        m = GLYPH_NAME_RE.match(term)
        if m:
            result.glyphs[m.group(2)] = m.group(1).strip()

    return result


def _headers(pages: list[str], first: int = 3, last: int = 49
             ) -> list[tuple[int, int, str]]:
    """Every ALL-CAPS entry header in the glossary span, in document order.

    HEADER_RE must admit a leading curly quote and glyphs inside the
    header. Verified 2026-08-21: requiring `^[A-Z]` silently rejects
    "AFTER", "AND", "CANNOT" and every icon entry such as
    "ACCELERATION ICON ( )" - 36 of 216 entries lost with no error.
    """
    out = []
    for pi in range(first, min(last, len(pages))):
        for li, line in enumerate(pages[pi].split("\n")):
            s = line.strip()
            if HEADER_RE.match(s) and not re.match(r"^RU ?L ?E ?S", s, re.I):
                out.append((pi, li, s))
    return out


def _body_between(pages: list[str], heads: list[tuple[int, int, str]],
                  i: int) -> str:
    """One entry's body: from its header to the next header.

    Partitioning the document this way makes overlap impossible. The
    earlier approach - locating each index term independently and reading
    until any header - produced 106% coverage, meaning entries ran past
    their end into their neighbour while others came back empty.
    """
    pi, li, _ = heads[i]
    nxt = heads[i + 1] if i + 1 < len(heads) else (len(pages), 0, None)
    out: list[str] = []
    for page_no in range(pi, min(nxt[0], len(pages) - 1) + 1):
        lines = pages[page_no].split("\n")
        start = li + 1 if page_no == pi else 0
        stop = nxt[1] if page_no == nxt[0] else len(lines)
        out += lines[start:stop]
    return "\n".join(out).strip()


def match_key(term: str) -> str:
    """Normalise an index term or a body header to a comparable key.

    The two spellings differ in ways that are invisible until they cost
    you an entry: the index writes "Delayed Effects" where the body writes
    "DELAYED EFFECT", "Boost, Boost Icon ( )" where the body writes
    "BOOST", and icon glyphs appear in one and not the other.
    """
    s = PUA.sub("", term).replace("\u2192", "")
    s = s.split(",")[0]                    # RR alphabetises before the comma
    s = re.sub(r"\(.*?\)", "", s)          # "(Card Title)", "(Trait)"
    s = re.sub(r"^the\s+", "", s.strip(), flags=re.I)
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return re.sub(r"s$", "", s)            # singular/plural


def chunk_entries(pages: list[str], index: IndexResult, *,
                  source_doc: str) -> list[Entry]:
    heads = _headers(pages)
    bodies: dict[str, tuple[str, str]] = {}
    for i, (_, _, header) in enumerate(heads):
        bodies.setdefault(match_key(header),
                          (header, _body_between(pages, heads, i)))

    entries = []
    for term, page in index.entries:
        found = bodies.get(match_key(term))
        body = found[1] if found else ""
        see_also: list[str] = []
        m = SEE_ALSO_RE.search(body)
        if m:
            tail = " ".join(m.group(1).split())
            see_also = [s.strip() for s in tail.split(",") if s.strip()]
            body = body[:m.start()].strip()
        entries.append(Entry(term=term, body=body, page=page,
                             source_doc=source_doc, entry_addressable=True,
                             see_also=see_also))
    for term, target in index.redirects:
        entries.append(Entry(term=term, body=f"See {target}.", page=None,
                             source_doc=source_doc, entry_addressable=True,
                             see_also=[target]))
    return entries


def extraction_report(pages: list[str], index: IndexResult) -> dict:
    """What the chunker captured, and what it did not.

    This exists because a rules index that silently drops entries is worse
    than one that fails: every downstream answer stays confidently wrong.
    `init` writes this to disk so a human can read the unresolved list.
    """
    entries = chunk_entries(pages, index, source_doc="_audit")
    unresolved = [e.term for e in entries
                  if e.entry_addressable and e.page is not None and not e.body]
    glossary = re.sub(r"\s+", "", "".join(pages[3:49]))
    captured = re.sub(r"\s+", "", "".join(
        e.body for e in entries if e.page is not None))
    return {
        "index_entries": len(index.entries),
        "resolved": len(index.entries) - len(unresolved),
        "unresolved": unresolved,
        "coverage": round(len(captured) / max(len(glossary), 1), 3),
    }


def chunk_pages(pages: list[str], *, source_doc: str) -> list[Entry]:
    """Non-RR documents lack the alphabetical entry structure, so they are
    chunked by page with their leading heading. Searchable, not
    entry-addressable — and the CLI labels the difference (spec §9)."""
    out = []
    for n, text in enumerate(pages, start=1):
        body = text.strip()
        if not body:
            continue
        first = next((l.strip() for l in body.split("\n") if l.strip()), "")
        out.append(Entry(term=f"{source_doc} p.{n}: {first[:60]}",
                         body=body, page=n, source_doc=source_doc,
                         entry_addressable=False))
    return out


def load_glyphs(path: Path | None = None) -> dict[str, str]:
    p = path or GLYPHS_PATH
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {chr(int(k, 16)) if isinstance(k, str) and k.startswith("U+")
            else k: v for k, v in (raw.get("glyphs") or {}).items()}


def apply_glyphs(text: str, mapping: dict[str, str]) -> tuple[str, set[str]]:
    """Map private-use codepoints to readable tokens. Unmapped codepoints
    are preserved verbatim and reported, never silently stripped."""
    unmapped = {c for c in PUA.findall(text) if c not in mapping}
    for glyph, token in mapping.items():
        text = text.replace(glyph, f"[{token}]")
    return text, unmapped


def store(conn: sqlite3.Connection, entries: list[Entry]) -> int:
    docs = {e.source_doc for e in entries}
    for doc in docs:
        conn.execute("DELETE FROM rules_entries WHERE source_doc = ?", (doc,))
        conn.execute("DELETE FROM rules_see_also WHERE source_doc = ?", (doc,))

    conn.executemany(
        "INSERT OR REPLACE INTO rules_entries "
        "(term, body, page, source_doc, entry_addressable) "
        "VALUES (?, ?, ?, ?, ?)",
        [(e.term, e.body, e.page, e.source_doc, int(e.entry_addressable))
         for e in entries])
    conn.executemany(
        "INSERT OR IGNORE INTO rules_see_also (term, target, source_doc) "
        "VALUES (?, ?, ?)",
        [(e.term, t, e.source_doc) for e in entries for t in e.see_also])

    conn.execute("INSERT INTO rules_fts(rules_fts) VALUES('delete-all')")
    # Redirects ("See Cost Arrow Icon.") carry no page, and a search hit
    # with no page would break the citation guarantee. They stay queryable
    # by name through `rules show`, but out of the full-text index.
    conn.execute(
        "INSERT INTO rules_fts(rowid, term, body) "
        "SELECT id, term, body FROM rules_entries WHERE page IS NOT NULL")
    conn.commit()
    return conn.execute(
        "SELECT COUNT(*) FROM rules_entries").fetchone()[0]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_rules_chunk.py -v -m "not integration"`
Expected: PASS, 9 tests

- [ ] **Step 7: Derive `config/glyphs.yaml` from the real Rules Reference — then read it**

```bash
uv run python -c "
from mc_jarvis import pdf, rules_chunk
import collections
pages = pdf.extract_pages('/tmp/rr.pdf', backend='pypdf')
idx = rules_chunk.parse_index(pages)
print('entries:', len(idx.entries), 'redirects:', len(idx.redirects))
body = ''.join(pages)
used = collections.Counter(c for c in body if 0xE000 <= ord(c) <= 0xF8FF)
print('glyphs:')
for ch, n in sorted(used.items()):
    print(f'  \"U+{ord(ch):04X}\": {idx.glyphs.get(ch, \"** UNMAPPED **\")!r}  # {n} uses')
"
```

Expected: about 216 entries, 46 redirects, and **13 glyphs in U+F520–U+F531, all named**. Two known parse artifacts to correct by hand: two-column merge can join adjacent entries (`Variable` + `You, Your`), and the Unique icon's name picks up bleed from its predecessor (`Activation) Unique Icon` → `Unique Icon`).

Write the reviewed result to `config/glyphs.yaml`:

```yaml
# Private-use icon codepoints -> readable tokens (spec §9).
# DERIVED from the Rules Reference's own index, which names every icon,
# then reviewed by hand. Regenerate with the script in the plan's Task 13
# after an RR revision; do not hand-edit codepoints you have not seen in
# that output.
version: 1
glyphs:
  "U+F520": "boost"
  "U+F521": "amplify"
  "U+F522": "consequential-damage"
  "U+F524": "per-player"
  "U+F525": "wild"
  "U+F526": "physical"
  "U+F527": "mental"
  "U+F528": "energy"
  "U+F52D": "star"
  "U+F52E": "crisis"
  "U+F52F": "hazard"
  "U+F530": "acceleration"
  "U+F531": "unique"
```

**Verify this table against the script's output before committing** — the values above are what was observed on 2026-08-21 and the RR may have been revised since. Note that spec §9 and §16 say the range is U+F520–F530; it is U+F520–**F531**, and U+F523 and U+F529–U+F52C are unused.

- [ ] **Step 8: Run the extraction audit and account for every unresolved entry**

A rules index that silently drops entries is worse than one that fails, because every downstream answer stays confidently wrong. This step is the gate.

```bash
uv run python -c "
import json
from mc_jarvis import pdf, rules_chunk
pages = pdf.extract_pages('/tmp/rr.pdf', backend='pypdf')
idx = rules_chunk.parse_index(pages)
rep = rules_chunk.extraction_report(pages, idx)
print(json.dumps(rep, indent=2, ensure_ascii=False))
"
```

**Acceptance gate — all four must hold:**

| Check | Threshold | Measured 2026-08-21 |
|---|---|---|
| `resolved` / `index_entries` | ≥ 205 of 216 | 207 |
| `coverage` | ≥ 0.88 | 0.91 |
| Body overlap | impossible by construction | partition |
| Every `unresolved` term explained in writing | no exceptions | 9, all classified below |

The nine unresolved entries measured on 2026-08-21, and why each is acceptable:

- `Card Anatomy` — points into Appendix III (p.52), outside the glossary span. Not a glossary entry.
- `Golden Rules`, `Grim Rule`, `In Play`, `Play Restrictions and Permissions` — the index term and the body header are worded differently. `match_key` already strips a leading "the"; extend it if you can do so without collapsing two distinct entries onto one key.
- `Limit …`, `2 Ru l e s R e f eR e n c e Max, Maximum`, `Variable You, Your`, `Activation) Unique Icon` — two-column merge artifacts in `parse_index`, where adjacent index lines joined. Fix in `parse_index`, not here.

**If your run produces a different list, do not widen the thresholds.** Read each entry, classify it, and either fix the matcher or write down why it is acceptable. Commit the classification alongside the code — the next person needs to know these were examined rather than tolerated.

- [ ] **Step 9: Persist the audit so it stays visible**

Have `init` write the report to `<data>/rules/extraction-report.json` and surface `resolved`/`index_entries` in `mc-jarvis status`. A regression after an FFG revision then shows up in a routine `status` rather than in a wrong ruling at a table.

- [ ] **Step 10: Commit**

```bash
git add src/mc_jarvis/rules_chunk.py src/mc_jarvis/schema.py config/glyphs.yaml tests/
git commit -m "feat: chunk the Rules Reference from its own index, with derived glyph mapping"
```

---

## Task 14: `rules show`, `rules search`, and the card↔rules link table

Implements §5.1, §9, §10. **Every rules answer cites the entry name and page** — an uncited ruling is worthless in an argument at the table.

**Files:**
- Create: `src/mc_jarvis/rules.py`
- Modify: `src/mc_jarvis/schema.py`, `src/mc_jarvis/cli.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Produces:
  - `rules.show(conn, term: str) -> dict`
  - `rules.search(conn, text: str, *, limit: int = 10) -> list[dict]`
  - `rules.explain(conn, code: str) -> list[dict]` — keywords on a card, each with rules body and page
  - `rules.build_links(conn) -> int` — populates `card_rules_links`
  - `rules.handle_show(args) -> int`, `rules.handle_search(args) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rules.py
import json
import pytest
from mc_jarvis import cardtext, index, rules, rules_chunk
from tests.fixtures import cards as fx


_ENTRIES = [
    rules_chunk.Entry("Toughness", "A tough status card absorbs "
                      "the next damage.", 41, "rules-reference"),
    rules_chunk.Entry("Retaliate", "After this character defends, "
                      "deal damage to the attacker.", 36, "rules-reference"),
    rules_chunk.Entry("Setup", "Follow these steps in order.", 3,
                      "learn-to-play", entry_addressable=False),
]


@pytest.fixture
def entries():
    return list(_ENTRIES)


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(fx.ARROW_CARDS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    index.build_fts(c)
    cardtext.build(c)
    rules_chunk.store(c, _ENTRIES)
    rules.build_links(c)
    return c


def test_show_returns_body_and_page(conn):
    result = rules.show(conn, "Toughness")
    assert result["page"] == 41
    assert "absorbs" in result["body"]
    assert result["source_doc"] == "rules-reference"


def test_show_is_case_insensitive(conn):
    assert rules.show(conn, "toughness")["term"] == "Toughness"


def test_show_lists_cards_using_the_keyword(conn):
    assert "arw05" in {c["code"] for c in rules.show(conn, "Toughness")["cards"]}


def test_show_of_an_unknown_term_suggests_a_search(conn):
    result = rules.show(conn, "Quantum Flux")
    assert result["term"] is None
    assert result["suggestions"] is not None


def test_search_results_all_carry_a_citation(conn):
    hits = rules.search(conn, "damage")
    assert hits
    for h in hits:
        assert h["source_doc"]
        assert h["page"] is not None


def test_redirects_are_reachable_by_name_but_not_by_search(conn, entries):
    """A redirect has no page, so a search hit on one could not be cited.
    `store` replaces a whole source_doc, so the redirect is added to the
    full set rather than stored on its own."""
    rules_chunk.store(conn, entries + [rules_chunk.Entry(
        "Bolstered", "See Toughness.", None, "rules-reference",
        see_also=["Toughness"])])
    assert rules.show(conn, "Bolstered")["body"] == "See Toughness."
    assert all(h["term"] != "Bolstered"
               for h in rules.search(conn, "Toughness"))


def test_search_labels_non_entry_addressable_sources(conn):
    hits = rules.search(conn, "steps")
    ltp = next(h for h in hits if h["source_doc"] == "learn-to-play")
    assert ltp["entry_addressable"] is False


def test_search_handles_punctuation_without_a_syntax_error(conn):
    for q in ["Sp//dr", 'a "quote"', "AND", "-"]:
        rules.search(conn, q)


def test_explain_expands_a_cards_keywords(conn):
    kws = {k["term"] for k in rules.explain(conn, "arw05")}
    assert {"Toughness", "Retaliate"} <= kws


def test_explain_of_a_keywordless_card_is_empty(conn):
    assert rules.explain(conn, "arw01") == []


@pytest.mark.integration
def test_real_keyword_entries_resolve(real_index):
    for term in ("Overkill", "Retaliate", "Piercing", "Surge", "Guard"):
        result = rules.show(real_index, term)
        assert result["term"] is not None, term
        assert result["page"] is not None, term
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rules.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.rules'`

- [ ] **Step 3: Add the link table to `schema.py`**

```sql
CREATE TABLE IF NOT EXISTS card_rules_links (
    code       TEXT NOT NULL REFERENCES cards(code),
    term       TEXT NOT NULL,
    source_doc TEXT NOT NULL,
    PRIMARY KEY (code, term, source_doc)
);
CREATE INDEX IF NOT EXISTS idx_links_term ON card_rules_links(lower(term));
```

- [ ] **Step 4: Write `rules.py`**

```python
"""Rules queries (spec §5.1, §9). Every answer carries a citation."""
from __future__ import annotations

import sqlite3

from . import index, paths
from .cards import _fts_query, _open
from .cli import emit


def show(conn, term: str) -> dict:
    row = conn.execute(
        "SELECT id, term, body, page, source_doc, entry_addressable "
        "FROM rules_entries WHERE lower(term) = lower(?) "
        "ORDER BY entry_addressable DESC LIMIT 1", (term,)).fetchone()

    if row is None:
        return {"term": None, "suggestions": search(conn, term, limit=5)}

    see_also = [r["target"] for r in conn.execute(
        "SELECT target FROM rules_see_also "
        "WHERE lower(term) = lower(?) AND source_doc = ?",
        (row["term"], row["source_doc"]))]

    cards = [dict(r) for r in conn.execute(
        "SELECT c.code, c.name, c.type_code FROM card_rules_links l "
        "JOIN cards c ON c.code = l.code "
        "WHERE lower(l.term) = lower(?) ORDER BY c.code LIMIT 40",
        (row["term"],))]

    return {"term": row["term"], "body": row["body"], "page": row["page"],
            "source_doc": row["source_doc"],
            "entry_addressable": bool(row["entry_addressable"]),
            "see_also": see_also, "cards": cards}


def search(conn, text: str, *, limit: int = 10) -> list[dict]:
    expr = _fts_query(text)
    if not expr:
        return []
    rows = conn.execute(
        "SELECT e.term, e.body, e.page, e.source_doc, e.entry_addressable "
        "FROM rules_fts f JOIN rules_entries e ON e.id = f.rowid "
        "WHERE rules_fts MATCH ? ORDER BY rank LIMIT ?", (expr, limit))
    return [{**dict(r), "entry_addressable": bool(r["entry_addressable"])}
            for r in rows]


def build_links(conn: sqlite3.Connection) -> int:
    """Join keyword occurrences in card text to Rules Reference entries.
    One table serves both directions: `card show --explain` expands a
    card's keywords, and `rules show` lists the cards that use one."""
    conn.execute("DELETE FROM card_rules_links")
    conn.execute(
        "INSERT OR IGNORE INTO card_rules_links (code, term, source_doc) "
        "SELECT k.code, e.term, e.source_doc "
        "FROM card_keywords k JOIN rules_entries e "
        "  ON lower(e.term) = lower(k.keyword) "
        "WHERE e.entry_addressable = 1")
    conn.commit()
    return conn.execute(
        "SELECT COUNT(*) FROM card_rules_links").fetchone()[0]


def explain(conn, code: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT e.term, e.body, e.page, e.source_doc "
        "FROM card_rules_links l "
        "JOIN rules_entries e ON e.term = l.term "
        "  AND e.source_doc = l.source_doc "
        "WHERE l.code = ? ORDER BY e.term", (code,))]


def _cite(row: dict) -> str:
    label = row["source_doc"]
    page = f"p.{row['page']}" if row.get("page") else "no page"
    suffix = "" if row.get("entry_addressable", True) else "  (page chunk)"
    return f"[{label} {page}]{suffix}"


def handle_show(args) -> int:
    conn = _open()
    result = show(conn, args.term)
    if args.json:
        emit(result, as_json=True)
        return 0 if result["term"] else 1
    if not result["term"]:
        print(f"no rules entry named {args.term!r}")
        if result["suggestions"]:
            print("\nclosest full-text matches:")
            for s in result["suggestions"]:
                print(f"  {s['term']}  {_cite(s)}")
        return 1
    print(f"{result['term']}  {_cite(result)}\n")
    print(result["body"])
    if result["see_also"]:
        print(f"\nSee also: {', '.join(result['see_also'])}")
    if result["cards"]:
        print(f"\nCards using this keyword ({len(result['cards'])}):")
        for c in result["cards"]:
            print(f"  {c['code']:<8} {c['name']}")
    return 0


def handle_search(args) -> int:
    conn = _open()
    hits = search(conn, args.text)
    if args.json:
        emit(hits, as_json=True)
        return 0 if hits else 1
    if not hits:
        print("no matches")
        return 1
    for h in hits:
        body = " ".join(h["body"].split())
        print(f"\n{h['term']}  {_cite(h)}")
        print(f"  {body[:300]}{'...' if len(body) > 300 else ''}")
    return 0
```

- [ ] **Step 5: Dispatch it** — in `cli.py` `_dispatch`:

```python
    if name == "rules":
        from . import rules
        if args.rules_cmd == "show":
            return rules.handle_show(args)
        if args.rules_cmd == "search":
            return rules.handle_search(args)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 7: Exercise against real rules**

```bash
mc-jarvis rules show Overkill
mc-jarvis rules show "Cost Arrow Icon"
mc-jarvis rules search "when does the villain attack"
mc-jarvis card show 01001a --explain
```
Expected: every answer carries an entry name and page; `--explain` lists the card's keywords with rules text

- [ ] **Step 8: Commit**

```bash
git add src/mc_jarvis/rules.py src/mc_jarvis/schema.py src/mc_jarvis/cli.py tests/test_rules.py
git commit -m "feat: rules lookup, full-text search, and the card-rules link table"
```

---

## Task 15: `init`, `update`, and `status`

Implements §11. Ties every preceding task into one bootstrap. **First run is a shell command, not an agent request** — the skill is what teaches an agent that `mc-jarvis` exists, so the agent cannot be what installs it.

**Files:**
- Create: `src/mc_jarvis/init.py`, `src/mc_jarvis/update.py`
- Modify: `src/mc_jarvis/cli.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Produces:
  - `init.rebuild_index(conn, data_root: Path) -> dict[str, int]` — the shared build pipeline
  - `init.run(args) -> int`
  - `update.run(args) -> int`
  - `update.status(args) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_init.py
import json
import pytest
from mc_jarvis import index, init, manifest, outofdeck
from tests.fixtures import cards as fx


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(
        fx.PACK + fx.MATCH_FAMILY + fx.OUT_OF_DECK + fx.ARROW_CARDS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text(json.dumps(fx.SETS))
    return tmp_path


def test_rebuild_runs_every_stage(data_root, monkeypatch):
    monkeypatch.setattr(outofdeck, "load_config",
                        lambda path=None: fx.CONFIG_COVERING_EMBERLINE)
    conn = index.connect(data_root / "mc.sqlite")
    counts = init.rebuild_index(conn, data_root)
    for stage in ("cards", "fts", "identities", "out_of_deck",
                  "traits", "clauses"):
        assert stage in counts, stage
    assert counts["cards"] > 0


def test_rebuild_is_idempotent(data_root, monkeypatch):
    monkeypatch.setattr(outofdeck, "load_config",
                        lambda path=None: fx.CONFIG_COVERING_EMBERLINE)
    conn = index.connect(data_root / "mc.sqlite")
    first = init.rebuild_index(conn, data_root)
    second = init.rebuild_index(conn, data_root)
    assert first == second


def test_rebuild_records_build_metadata(data_root, monkeypatch):
    monkeypatch.setattr(outofdeck, "load_config",
                        lambda path=None: fx.CONFIG_COVERING_EMBERLINE)
    conn = index.connect(data_root / "mc.sqlite")
    init.rebuild_index(conn, data_root)
    keys = {r["key"] for r in conn.execute("SELECT key FROM build_meta")}
    assert {"built_at", "card_count"} <= keys


def test_init_refuses_on_a_hard_doctor_failure(data_root, monkeypatch):
    from mc_jarvis import doctor
    monkeypatch.setattr(doctor, "has_fts5", lambda: False)

    class Args:
        json = False
        from_html = None
        browser = False
    assert init.run(Args()) == 1


def test_status_reports_missing_index(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))
    from mc_jarvis import update

    class Args:
        json = False
    assert update.status(Args()) == 1
    assert "init" in capsys.readouterr().out


def test_update_diff_reports_a_revised_rulebook(tmp_path):
    old = [manifest.RuleDoc("Rules Reference", "u", None, "Jul 2026",
                            "rules-reference")]
    new = [manifest.RuleDoc("Rules Reference", "u", None, "Jan 2027",
                            "rules-reference")]
    assert manifest.diff(old, new) == [("rules-reference", "revised")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_init.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.init'`

- [ ] **Step 3: Write `init.py`**

```python
"""Bootstrap (spec §11)."""
from __future__ import annotations

import datetime as _dt
import sqlite3
import sys
from pathlib import Path

from . import (cardtext, doctor, identity, index, manifest, outofdeck,
               paths, pdf, rules, rules_chunk, sources)


def rebuild_index(conn: sqlite3.Connection, data_root: Path) -> dict[str, int]:
    """The single build pipeline, shared by `init` and `update`.

    Order matters: out-of-deck classification must run after identities
    exist, and the card-rules link table after both card keywords and
    rules entries (spec §8, §10).
    """
    counts: dict[str, int] = {}
    report = index.load_cards(conn, data_root / "marvelsdb")
    counts["cards"] = report.cards
    counts["player_cards"] = report.player_cards
    counts["fts"] = index.build_fts(conn)
    counts["identities"] = identity.build(conn)

    config = outofdeck.load_config()
    counts["out_of_deck"] = outofdeck.classify(conn, config, strict=True)

    text_counts = cardtext.build(conn)
    counts.update(text_counts)

    counts["rules_entries"] = _rebuild_rules(conn, data_root)
    counts["rules_links"] = rules.build_links(conn)

    conn.executemany(
        "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
        [("built_at", _dt.datetime.now(_dt.timezone.utc).isoformat()),
         ("card_count", str(counts["cards"]))])
    conn.commit()
    return counts


def _rebuild_rules(conn, data_root: Path) -> int:
    txt_dir = data_root / "rules" / "txt"
    glyphs = rules_chunk.load_glyphs()
    all_entries, unmapped = [], set()

    for path in sorted(txt_dir.glob("*.txt")):
        slug = path.stem
        pages = path.read_text(encoding="utf-8").split("\f")
        pages = [_apply(p, glyphs, unmapped) for p in pages]
        idx = rules_chunk.parse_index(pages)
        if len(idx.entries) > 50:
            all_entries.extend(rules_chunk.chunk_entries(
                pages, idx, source_doc=slug))
        else:
            # No alphabetical index: chunk by page, searchable but not
            # entry-addressable (spec §9).
            all_entries.extend(rules_chunk.chunk_pages(
                pages, source_doc=slug))

    conn.execute(
        "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
        ("unmapped_glyphs",
         " ".join(sorted(f"U+{ord(c):04X}" for c in unmapped))))
    if not all_entries:
        return 0
    return rules_chunk.store(conn, all_entries)


def _apply(page: str, glyphs, unmapped: set) -> str:
    text, missing = rules_chunk.apply_glyphs(page, glyphs)
    unmapped |= missing
    return text


def run(args) -> int:
    checks = doctor.run_checks(network=False)
    hard = [c for c in checks if c.hard and not c.ok]
    if hard:
        print("mc-jarvis init cannot start:", file=sys.stderr)
        for c in hard:
            print(f"  {c.name}: {c.detail}", file=sys.stderr)
        return 1

    root = paths.ensure_data_dir()
    print(f"data directory: {root}")

    print("fetching card data...")
    fetched = sources.fetch_card_data(root / "marvelsdb")
    print(f"  {fetched.pack_files} pack files "
          f"({fetched.bytes_downloaded / 1e6:.1f} MB)")

    html = _get_page_html(args)
    if html is None:
        print("\nNo rules manifest. Card commands will work; rules "
              "commands will not.\nRe-run with --from-html once you have "
              "saved the product page:\n"
              f"  {manifest.PRODUCT_PAGE}")
        docs = []
    else:
        docs = manifest.parse(html)
        manifest.write(docs, root / "rules" / "manifest.json")
        print(f"  {len(docs)} rulebooks listed")

    for doc in docs:
        if doc.slug not in manifest.DEFAULT_SLUGS:
            continue
        target = root / "rules" / "pdf" / f"{doc.slug}.pdf"
        print(f"downloading {doc.title}...")
        pdf.download(doc.url, target)
        pages = pdf.extract_pages(target)
        (root / "rules" / "txt" / f"{doc.slug}.txt").write_text(
            "\f".join(pages), encoding="utf-8")
        print(f"  {len(pages)} pages")

    print("building index...")
    conn = index.connect(paths.db_path())
    counts = rebuild_index(conn, root)
    for key, value in counts.items():
        print(f"  {key}: {value}")

    print("\nNext:  mc-jarvis install-skill      (in your deck workspace)")
    return 0


def _get_page_html(args) -> str | None:
    if getattr(args, "from_html", None):
        return Path(args.from_html).read_text(encoding="utf-8",
                                              errors="replace")
    if getattr(args, "browser", False):
        try:
            return manifest.fetch_with_browser()
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return None
    return None
```

- [ ] **Step 4: Write `update.py`**

```python
"""Refresh and staleness reporting (spec §11)."""
from __future__ import annotations

import time

from . import index, init, manifest, paths, pdf, sources
from .cli import emit

STALE_DAYS = 14


def run(args) -> int:
    root = paths.ensure_data_dir()
    print("refreshing card data...")
    fetched = sources.fetch_card_data(root / "marvelsdb")
    print(f"  {fetched.pack_files} pack files")

    manifest_path = root / "rules" / "manifest.json"
    old = manifest.read(manifest_path)
    if old:
        print(f"  {len(old)} rulebooks known; re-run `init --from-html` "
              f"to re-check FFG for revisions")

    conn = index.connect(paths.db_path())
    counts = init.rebuild_index(conn, root)
    if args.json:
        emit(counts, as_json=True)
    else:
        for key, value in counts.items():
            print(f"  {key}: {value}")
    return 0


def status(args) -> int:
    db = paths.db_path()
    if not db.exists():
        print("no index — run `mc-jarvis init`")
        return 1

    conn = index.connect(db)
    age_days = (time.time() - db.stat().st_mtime) / 86400
    meta = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM build_meta")}
    payload = {
        "data_dir": str(paths.data_dir()),
        "built_at": meta.get("built_at"),
        "age_days": round(age_days, 1),
        "stale": age_days > STALE_DAYS,
        "cards": conn.execute(
            "SELECT COUNT(*) FROM cards").fetchone()[0],
        "identities": conn.execute(
            "SELECT COUNT(*) FROM identities").fetchone()[0],
        "rules_entries": conn.execute(
            "SELECT COUNT(*) FROM rules_entries").fetchone()[0],
        "unmapped_glyphs": meta.get("unmapped_glyphs", ""),
    }
    if args.json:
        emit(payload, as_json=True)
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
        if payload["stale"]:
            print(f"\nIndex is {payload['age_days']:.0f} days old — "
                  f"run `mc-jarvis update`")
    return 0
```

- [ ] **Step 5: Dispatch them** — in `cli.py` `_dispatch`:

```python
    if name == "init":
        from . import init as init_mod
        return init_mod.run(args)
    if name == "update":
        from . import update
        return update.run(args)
    if name == "status":
        from . import update
        return update.status(args)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 7: Run a real end-to-end init from an empty data directory**

```bash
rm -rf ~/.local/share/mc-jarvis
# Save the FFG product page to /tmp/ffg.html first (see Task 11 Step 6).
mc-jarvis init --from-html /tmp/ffg.html
mc-jarvis status
uv run pytest tests/ -v -m integration
```
Expected: the whole pipeline from nothing to a working index; `status` shows ~4,298 cards, 72 identities, ~216 rules entries, and **`unmapped_glyphs` empty**

- [ ] **Step 8: Commit**

```bash
git add src/mc_jarvis/init.py src/mc_jarvis/update.py src/mc_jarvis/cli.py tests/test_init.py
git commit -m "feat: init, update, and status"
```

---

## Task 16: `SKILL.md` and `install-skill`

Implements §7. The skill file is the single source of truth for the agent. `install-skill`'s guard rails are the kind that fail silently, so they get tests rather than trust.

**Files:**
- Create: `skill/mc-jarvis/SKILL.md`, `skill/mc-jarvis/references/browser-recipes.md`, `src/mc_jarvis/skill_install.py`
- Modify: `src/mc_jarvis/cli.py`
- Test: `tests/test_skill_install.py`

**Interfaces:**
- Produces:
  - `skill_install.HARNESS_DIRS: dict[str, tuple[str, ...]]` — workspace paths
  - `skill_install.GLOBAL_DIRS: dict[str, tuple[str, ...]]`
  - `skill_install.check_workspace(path: Path) -> None` — raises `WorkspaceError`
  - `skill_install.install(workspace: Path, *, link=False, global_=False) -> list[Placement]`
  - `skill_install.Placement` — dataclass `harness: str`, `path: Path`, `mode: str`, `needs_trust: bool`
  - `skill_install.WorkspaceError`
  - `skill_install.run(args) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_install.py
import subprocess
from pathlib import Path
import pytest
from mc_jarvis import skill_install as si


def test_home_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(si.WorkspaceError, match="home directory"):
        si.check_workspace(tmp_path)


def test_directory_inside_another_repository_is_refused(tmp_path):
    outer = tmp_path / "outer"
    (outer / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    with pytest.raises(si.WorkspaceError, match="inside"):
        si.check_workspace(outer / "sub")


def test_a_plain_directory_is_accepted(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    si.check_workspace(ws)


def test_install_places_the_skill_for_every_harness(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    placements = si.install(ws)
    got = {p.path.relative_to(ws).as_posix() for p in placements}
    assert got == {
        ".agents/skills/mc-jarvis",
        ".claude/skills/mc-jarvis",
        ".codex/skills/mc-jarvis",
    }
    for p in placements:
        assert (p.path / "SKILL.md").is_file()


def test_install_copies_by_default(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    for p in si.install(ws):
        assert not p.path.is_symlink()
        assert p.mode == "copy"


def test_link_mode_symlinks(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    for p in si.install(ws, link=True):
        assert p.path.is_symlink()


def test_install_initialises_git_so_the_boundary_is_defined(tmp_path):
    """Ancestor walking is bounded by the repository root; without a git
    root a workspace can be cut off from its own skill (spec §7)."""
    ws = tmp_path / "marvel"
    ws.mkdir()
    si.install(ws)
    assert (ws / ".git").is_dir()


def test_reinstall_replaces_rather_than_nesting(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    si.install(ws)
    si.install(ws)
    target = ws / ".claude" / "skills" / "mc-jarvis"
    assert not (target / "mc-jarvis").exists()


def test_frontmatter_has_the_required_fields_and_no_allowed_tools():
    text = (si.SKILL_SOURCE / "SKILL.md").read_text()
    assert text.startswith("---")
    front = text.split("---")[1]
    assert "name: mc-jarvis" in front
    assert "description:" in front
    assert "compatibility:" in front
    # Marked experimental with support varying between implementations,
    # which is exactly what breaks a one-file-everywhere design (spec §7).
    assert "allowed-tools" not in front


def test_skill_md_stays_under_the_length_limit():
    text = (si.SKILL_SOURCE / "SKILL.md").read_text()
    assert len(text.splitlines()) < 500
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_skill_install.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.skill_install'`

- [ ] **Step 3: Write `skill/mc-jarvis/SKILL.md`**

Keep it under 500 lines; push per-harness browser recipes into `references/`.

```markdown
---
name: mc-jarvis
description: >-
  Marvel Champions LCG assistant. Use when the user asks about Marvel
  Champions cards, heroes, identities, encounter sets, deck legality, deck
  statistics, or rules questions — including "is this legal", "what does
  this keyword do", "which cards have X", and anything about a marvelcdb
  deck.
compatibility: Requires Python 3.10+ and the `mc-jarvis` command on PATH.
license: MIT
---

# mc-jarvis

You are Jarvis. Dry, precise, understated. Lead with the answer, then the
reasoning. Never pad. No honorific unless the user asks for one.

## The one rule

**Every factual claim comes from a command, not from memory.** Card text,
costs, legality, and rules all live in a local index. Your training data on
this game is stale and the card pool changes with each release. Run the
command.

Rules answers must carry the entry name and page the command returned. An
uncited ruling is worthless in an argument at the table.

## Setup check

If any command reports "no index", the user has not run `mc-jarvis init`.
Tell them to run it from the folder they want as their deck workspace:

    uv tool install mc-jarvis && mc-jarvis init

If `init` needs the FFG product page, see `references/browser-recipes.md`.
If any command fails unexpectedly, run `mc-jarvis doctor` and show the
user its output — a missing prerequisite should be diagnosed, not guessed.

## Commands

Every command takes `--json` for machine consumption. Use it when you need
to compute; use the default when you are quoting to the user.

| Ask | Command |
|---|---|
| find cards | `mc-jarvis card search <query> [--aspect --type --cost --trait --limit]` |
| one card in full | `mc-jarvis card show <name-or-code> [--explain]` |
| a hero's kit | `mc-jarvis identity <name>` |
| an encounter set | `mc-jarvis encounter <villain-or-set>` |
| a rules term | `mc-jarvis rules show <term>` |
| a rules question | `mc-jarvis rules search <text>` |
| environment problems | `mc-jarvis doctor` |
| index age and counts | `mc-jarvis status` |

`card show` **lists candidates instead of guessing** when a name is
ambiguous — 60 character names exist as both an identity and an ally, so
"Black Panther" is genuinely three cards. Show the user the candidates and
ask, or pick by code if context makes it obvious.

`--explain` expands a card's keywords with their rules text and page
cites. Use it whenever the user asks what a card actually does.

## Reading the output

- **Identities have more than two faces.** Angel has three; Ironheart has
  six. `identity` returns all of them. Do not assume hero/alter-ego.
- **Some cards sit outside the deck.** Permanent cards, hero-special decks,
  and a few unmarked cards are excluded from deck counts. The index knows
  which; you do not need to.
- **Cost arrows.** `card show --explain` splits `pay cost → resolve effect`.
  Timing text before the arrow is *not* a cost. Some clauses come back
  flagged `ambiguous` — say so rather than asserting a split.
- **Page-chunk sources.** Rules hits labelled `(page chunk)` come from
  documents without an alphabetical index. They are searchable but less
  precise. Say which document you are quoting.

## Staleness

Check `mc-jarvis status`. If the index is more than 14 days old, mention
it once and offer `mc-jarvis update`. Do not nag, and never refresh
without being asked.

## What is not a command

Deck coaching, cut/add advice, and team analysis are your judgement, built
on command output. Gather the facts first — `deck stats`, `identity`,
`card show --explain` — then reason. Never invent a card, a cost, or a
rule to support a recommendation.
```

Also write `skill/mc-jarvis/references/browser-recipes.md` covering, one short section each: Claude Code (`claude-in-chrome` or Playwright MCP), Codex, opencode, pi, and the no-browser path (Save Page As → `--from-html`). Each section ends with the same command: `mc-jarvis init --from-html <file>`.

- [ ] **Step 4: Write `skill_install.py`**

```python
"""Place the skill for every harness (spec §7)."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SKILL_NAME = "mc-jarvis"
SKILL_SOURCE = Path(__file__).parent / "_bundled" / "skill" / SKILL_NAME

# Three workspace directories cover four harnesses: .agents serves pi and
# opencode; Claude Code and Codex each read only their own vendor path.
HARNESS_DIRS = {
    "pi, opencode": (".agents/skills",),
    "Claude Code":  (".claude/skills",),
    "Codex":        (".codex/skills",),
}
GLOBAL_DIRS = {
    "pi, opencode": ("~/.agents/skills",),
    "Claude Code":  ("~/.claude/skills",),
    "Codex":        ("~/.codex/skills",),
}
NEEDS_TRUST = {"pi, opencode"}


class WorkspaceError(RuntimeError):
    pass


@dataclass
class Placement:
    harness: str
    path: Path
    mode: str
    needs_trust: bool


def _git_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 else None


def check_workspace(path: Path) -> None:
    """Ancestor walking is bounded by the repository root, so a workspace
    at $HOME is effectively global for pi, and a workspace nested inside an
    unrelated repository can be cut off from its own skill (spec §7)."""
    path = path.resolve()
    if path == Path.home().resolve():
        raise WorkspaceError(
            "refusing to install into your home directory: pi walks up to "
            "the git root, so a skill here would load in every session. "
            "Make a folder for your decks and run this there, or pass "
            "--global if you genuinely want it everywhere.")
    root = _git_root(path)
    if root is not None and root != path:
        raise WorkspaceError(
            f"{path} is inside the repository at {root}. Harnesses stop "
            f"walking up at the repository root, so the skill may not load "
            f"here. Choose a workspace outside it.")


def install(workspace: Path, *, link: bool = False,
            global_: bool = False) -> list[Placement]:
    if not SKILL_SOURCE.is_dir():
        raise WorkspaceError(f"bundled skill not found at {SKILL_SOURCE}")

    placements: list[Placement] = []
    if global_:
        targets = [(h, Path(d).expanduser()) for h, dirs in GLOBAL_DIRS.items()
                   for d in dirs]
    else:
        workspace = workspace.resolve()
        check_workspace(workspace)
        if not (workspace / ".git").exists():
            subprocess.run(["git", "init", "-q", str(workspace)], check=False)
        targets = [(h, workspace / d) for h, dirs in HARNESS_DIRS.items()
                   for d in dirs]

    for harness, parent in targets:
        parent.mkdir(parents=True, exist_ok=True)
        dest = parent / SKILL_NAME
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        elif dest.is_dir():
            shutil.rmtree(dest)

        if link:
            dest.symlink_to(SKILL_SOURCE, target_is_directory=True)
            mode = "link"
        else:
            shutil.copytree(SKILL_SOURCE, dest)
            mode = "copy"

        placements.append(Placement(harness, dest, mode,
                                    harness in NEEDS_TRUST))
    return placements


def run(args) -> int:
    from .cli import emit
    workspace = Path.cwd()
    try:
        placements = install(workspace, link=args.link, global_=args.global_)
    except WorkspaceError as exc:
        print(f"mc-jarvis install-skill: {exc}")
        return 1

    if args.json:
        emit([{"harness": p.harness, "path": str(p.path), "mode": p.mode,
               "needs_trust": p.needs_trust} for p in placements],
             as_json=True)
        return 0

    for p in placements:
        print(f"{p.mode:<5} {p.harness:<14} {p.path}")
    if any(p.needs_trust for p in placements):
        print("\nSome harnesses load project skills only after you trust "
              "the directory. If nothing activates, trust this folder in "
              "your agent and restart it.")
    print(f"\nAsk your agent a Marvel Champions question from "
          f"{workspace} to check it works.")
    return 0
```

Bundle the skill and configs into the wheel: add a build step (or a symlink for development) placing `skill/` at `src/mc_jarvis/_bundled/skill/`, `config/legality.yaml` at `src/mc_jarvis/_bundled/legality.yaml`, and `config/glyphs.yaml` at `src/mc_jarvis/_bundled/glyphs.yaml`.

- [ ] **Step 5: Dispatch it** — in `cli.py` `_dispatch`: `if name == "install-skill": from . import skill_install; return skill_install.run(args)`

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v -m "not integration"`
Expected: PASS

- [ ] **Step 7: Install into a real workspace and drive it through an agent**

```bash
mkdir -p ~/marvel-champions && cd ~/marvel-champions
mc-jarvis install-skill
ls -R .agents .claude .codex
```
Then open an agent in `~/marvel-champions` and ask, without naming any command: *"What does Overkill do?"*, *"Show me Ironheart's identity cards"*, *"Which Justice allies cost 2 or less?"*

Expected: the agent finds and uses the skill, and the answers carry citations. **This is the real test of Task 16** — if the agent answers from its own memory instead of running a command, the SKILL.md wording is not strong enough.

- [ ] **Step 8: Commit**

```bash
git add skill/ src/mc_jarvis/skill_install.py src/mc_jarvis/cli.py tests/test_skill_install.py
git commit -m "feat: SKILL.md and workspace-scoped install-skill"
```

---

## Task 17: The timing reference

**Not in the original spec — added 2026-08-21.** Trigger ordering is the hardest thing in the game to get right at the table, and it is the one question `rules show <term>` answers badly: the RR has **no single timing entry**. `Timing` is a redirect pointing at four others, and the ordering rules are spread across `Forced` (p.20), `Interrupt` (p.25), `Response` (p.38), `First Player` (p.20), `Simultaneous Resolution` (p.40), and three `When …` entries (p.48). A player mid-game cannot assemble that.

**The RR does have a priority chart, and it is authoritative.** *Simultaneous Timing Priority* sits on **p.5, inside the `ABILITY` entry** — which is why it has no header of its own and does not appear in the index. The v18 change log calls it out: "Page 5: Revised 'Simultaneous Timing Priority' chart." It is a numbered list with lettered sub-tiers, so it is **parsed from the indexed rules, not hand-encoded**:

```
1. Constant abilities, delayed effects, and lasting effects.
2. Interrupts
   a. Status card "Forced Interrupt" abilities.
   b. "Forced Interrupt" abilities.
   c. "Interrupt" abilities.
3. "Boost" and "When Revealed" abilities.
4. Responses
   a. "Forced Response" abilities.
   b. "Response" abilities.
5. Consequential damage.
```

Three things in this chart are easy to get wrong, and an earlier draft of this task got all three wrong:

- **`When Revealed` is rung 3, grouped with `Boost` — it is not a Forced Interrupt.** The RR states the Forced Interrupt equivalence for `When Defeated` and `When Completed` (both p.48) and **not** for `When Revealed`. Generalising from two entries to three puts it a whole tier too early.
- **`Boost` is a timing trigger**, despite appearing on 428 cards in a way that reads like flavour text.
- **Status-card Forced Interrupts outrank ordinary ones** (2a over 2b), consistent with `Status Cards` p.41: "Status card abilities have timing priority over all conflicting triggered abilities."

Because the chart is parsed, `config/timing.yaml` holds only what the chart does not: which printed prefixes map onto which rung, and the qualifier/alias rules. The chart itself is verified against the RR rather than trusted.

**Files:**
- Create: `src/mc_jarvis/timing.py`, `config/timing.yaml`
- Modify: `src/mc_jarvis/schema.py`, `src/mc_jarvis/cardtext.py`, `src/mc_jarvis/init.py`, `src/mc_jarvis/cli.py`, `skill/mc-jarvis/SKILL.md`
- Test: `tests/test_timing.py`

**Interfaces:**
- Consumes: `rules_chunk.store` output (`rules_entries`), `cardtext.build`
- Produces:
  - `timing.load_config(path=None) -> dict`
  - `timing.parse_chart(body: str) -> list[dict]` — the numbered chart with lettered sub-tiers, from the `ABILITY` entry body
  - `timing.chart(conn) -> list[dict]`
  - `timing.verify_chart(conn) -> list[str]` — differences from the chart recorded on 2026-08-21
  - `timing.classify(prefix: str) -> Trigger | None` — splits a bold prefix into qualifier, forced flag, and the chart rung it occupies
  - `timing.Trigger` — dataclass `raw: str`, `qualifier: str | None`, `forced: bool`, `canonical: str`, `rung: int | None`, `sub: str | None`
  - `timing.explain(conn, trigger: str) -> dict`
  - `timing.round_structure(conn) -> list[dict]`
  - `timing.build(conn) -> int` — populates `timing_chart`, `timing_triggers`, and `round_steps`
  - `timing.verify_citations(conn) -> list[str]` — quotes no longer found in the indexed RR
  - `timing.handle(args) -> int`

### Why the config is trustworthy

The chart is **parsed from the rules**, so the ordering is not hand-encoded at all. What remains in config is the prefix-to-rung mapping and the alias rules, and those carry the exact RR phrase that establishes them. Two checks run at build time:

- `verify_chart` compares the parsed chart against the copy recorded on 2026-08-21 and reports any difference.
- `verify_citations` asserts every quote is still present in the indexed rules body.

If FFG revises the chart or rewords an entry, the build says which rung went stale instead of serving a wrong answer. Same move as the setup audit in Task 8 — a checked config, not a trusted one.

- [ ] **Step 1: Write `config/timing.yaml`**

```yaml
# Trigger timing and priority. Added 2026-08-21.
#
# The ordering itself is NOT here. It is the RR's own "Simultaneous Timing
# Priority" chart, parsed from the ABILITY entry (p.5) at build time by
# `timing.parse_chart`. This file holds only what the chart does not say:
# which printed card prefixes map onto which rung, and the qualifier and
# alias rules.
#
# `expected_chart` is what the chart said on 2026-08-21. It is compared
# against the parsed chart at build time, so a revision upstream is
# reported rather than silently changing every answer.

version: 1

chart_source:
  rr_entry: Ability
  rr_page: 5
  quote: >-
    the timing priority of abilities with the same triggering condition

expected_chart:
  - {rung: 1, sub: null, text: "Constant abilities, delayed effects, and lasting effects."}
  - {rung: 2, sub: null, text: "Interrupts"}
  - {rung: 2, sub: "a",  text: "Status card \u201cForced Interrupt\u201d abilities."}
  - {rung: 2, sub: "b",  text: "\u201cForced Interrupt\u201d abilities."}
  - {rung: 2, sub: "c",  text: "\u201cInterrupt\u201d abilities."}
  - {rung: 3, sub: null, text: "\u201cBoost\u201d and \u201cWhen Revealed\u201d abilities."}
  - {rung: 4, sub: null, text: "Responses"}
  - {rung: 4, sub: "a",  text: "\u201cForced Response\u201d abilities."}
  - {rung: 4, sub: "b",  text: "\u201cResponse\u201d abilities."}
  - {rung: 5, sub: null, text: "Consequential damage."}

# Bold prefixes that qualify a trigger without being one. The printed
# prefix is `<qualifier> <trigger>`, e.g. "Hero Action".
qualifiers: ["Hero", "Alter-Ego", "First Player", "Mission"]

# Printed prefix -> the chart rung it occupies.
# `sub` picks the lettered tier where the chart has one.
triggers:
  Forced Interrupt: {rung: 2, sub: "b"}
  Interrupt:        {rung: 2, sub: "c"}
  Boost:            {rung: 3, sub: null}
  When Revealed:    {rung: 3, sub: null}
  Forced Response:  {rung: 4, sub: "a"}
  Response:         {rung: 4, sub: "b"}

# Aliases the RR defines as equivalent to another trigger.
# NOTE: "When Revealed" is deliberately NOT here. The RR states this
# equivalence for When Defeated and When Completed only; the chart puts
# When Revealed on rung 3, a full tier after Forced Interrupts.
aliases:
  When Defeated:
    canonical: Forced Interrupt
    rr_entry: When Defeated Abilities
    rr_page: 48
    quote: >-
      timing trigger is equivalent to the following trigger
  When Completed:
    canonical: Forced Interrupt
    rr_entry: When Completed Abilities
    rr_page: 48
    quote: >-
      timing trigger is equivalent to the following trigger

# Triggers with no rung: they are not tied to a triggering condition, so
# the chart does not order them.
outside_chart:
  Action:   {rr_entry: Forced,                    rr_page: 20}
  Resource: {rr_entry: Resource Ability,          rr_page: 37}
  Special:  {rr_entry: Special,                   rr_page: 40}
  Setup:    {rr_entry: Setup (Triggered Ability), rr_page: 40}

# Bold text that is not a triggered ability at all.
# `Boost` is NOT in this list — the chart makes it rung 3.
not_triggers:
  - Contents
  - Preparation
  - Standard Mode Only.
  - Expert Mode Only.

# Refinements the chart does not carry, each cited.
tie_breaks:
  - rule: >-
      The first player has the first opportunity at each rung; opportunities
      then proceed in player order.
    rr_entry: First Player
    rr_page: 20
    quote: >-
      The first player has the first opportunity to use
  - rule: >-
      If two or more forced abilities would initiate at the same moment,
      the first player chooses the order - regardless of who controls them.
    rr_entry: Forced
    rr_page: 20
    quote: >-
      the first player determines the order in which the abilities initiate
  - rule: >-
      Each forced ability resolves as completely as possible before the
      next forced ability on the same triggering condition initiates.
    rr_entry: Forced
    rr_page: 20
    quote: >-
      must resolve as completely as possible before the next forced ability
  - rule: >-
      If two effects with the same bold trigger would resolve
      simultaneously, the first player chooses the order.
    rr_entry: Simultaneous Resolution
    rr_page: 40
    quote: >-
      the first player determines the order in which the effects resolve
  - rule: >-
      An interrupt using the word "would" resolves before its triggering
      condition initiates, ahead of other interrupts to that condition.
    rr_entry: Interrupt
    rr_page: 25
    quote: >-
      resolve before its triggering condition initiates
  - rule: >-
      One effect causing several triggering conditions lets responses to
      each be resolved in any order.
    rr_entry: Response
    rr_page: 38
    quote: >-
      responses to each of those triggering conditions can be resolved in
      any order
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_timing.py
import pytest
from mc_jarvis import index, rules_chunk, timing

CHART = """Simultaneous Timing Priority - Some abilities have timing
priority over other abilities. In order, the timing priority of abilities
with the same triggering condition is:
1. Constant abilities, delayed effects, and  lasting effects.
2. Interrupts
a. Status card \u201cForced Interrupt \u201d abilities.
b. \u201cForced Interrupt \u201d abilities.
c. \u201cInterrupt \u201d abilities.
3. \u201cBoost\u201d and \u201cWhen Revealed \u201d abilities.
4. Responses
a. \u201cForced Response \u201d abilities.
b. \u201cResponse\u201d abilities.
5. Consequential damage."""


@pytest.fixture
def conn(tmp_path):
    c = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(c, [
        rules_chunk.Entry("Ability", CHART, 5, "rules-reference"),
        rules_chunk.Entry(
            "Forced",
            "For any given triggering condition, forced interrupts take "
            "priority and initiate before non-forced interrupts. If two or "
            "more forced abilities would initiate at the same moment, the "
            "first player determines the order in which the abilities "
            "initiate. Each forced ability must resolve as completely as "
            "possible before the next forced ability may initiate.",
            20, "rules-reference"),
        rules_chunk.Entry(
            "First Player",
            "The first player has the first opportunity to use an "
            "interrupt at each appropriate game moment.", 20,
            "rules-reference"),
        rules_chunk.Entry(
            "Interrupt",
            "Interrupts that use the word \u201cwould\u201d resolve before "
            "its triggering condition initiates.", 25, "rules-reference"),
        rules_chunk.Entry(
            "Response",
            "If single effect causes multiple triggering conditions to "
            "occur, responses to each of those triggering conditions can "
            "be resolved in any order.", 38, "rules-reference"),
        rules_chunk.Entry(
            "Simultaneous Resolution",
            "If two or more effects with the same bold timing trigger "
            "would resolve simultaneously, the first player determines the "
            "order in which the effects resolve.", 40, "rules-reference"),
        rules_chunk.Entry(
            "When Defeated Abilities",
            "The \u201cWhen Defeated\u201d timing trigger is equivalent to "
            "the following trigger: \u201cForced Interrupt: When this card "
            "is defeated...\u201d", 48, "rules-reference"),
        rules_chunk.Entry(
            "When Completed Abilities",
            "The \u201cWhen Completed\u201d timing trigger is equivalent to "
            "the following trigger: \u201cForced Interrupt: When this "
            "scheme is completed...\u201d", 48, "rules-reference"),
    ])
    timing.build(c)
    return c


def test_chart_parses_into_ten_rows(conn):
    rows = timing.chart(conn)
    assert len(rows) == 10
    assert rows[0]["rung"] == 1
    assert rows[-1]["rung"] == 5


def test_chart_captures_lettered_sub_tiers(conn):
    subs = [(r["rung"], r["sub"]) for r in timing.chart(conn) if r["sub"]]
    assert subs == [(2, "a"), (2, "b"), (2, "c"), (4, "a"), (4, "b")]


def test_parsed_chart_matches_the_expected_chart(conn):
    """A revision upstream must be reported, not silently absorbed."""
    assert timing.verify_chart(conn) == []


def test_a_changed_chart_is_reported(conn):
    conn.execute("UPDATE rules_entries SET body = 'Rewritten.' "
                 "WHERE term = 'Ability'")
    conn.commit()
    assert timing.verify_chart(conn)


def test_status_card_forced_interrupts_outrank_ordinary_ones(conn):
    rows = {(r["rung"], r["sub"]): r["text"] for r in timing.chart(conn)}
    assert "Status card" in rows[(2, "a")]
    assert "Status card" not in rows[(2, "b")]


def test_plain_trigger_classifies(conn):
    t = timing.classify("Response")
    assert t.canonical == "Response"
    assert (t.rung, t.sub) == (4, "b")
    assert t.forced is False


def test_forced_response_outranks_response(conn):
    forced, plain = timing.classify("Forced Response"), timing.classify("Response")
    assert forced.forced is True
    assert (forced.rung, forced.sub) < (plain.rung, plain.sub)


def test_all_interrupts_precede_all_responses(conn):
    for i in ("Forced Interrupt", "Interrupt"):
        for r in ("Forced Response", "Response"):
            assert timing.classify(i).rung < timing.classify(r).rung


def test_when_revealed_is_its_own_rung_not_a_forced_interrupt(conn):
    """The chart puts it on rung 3 with Boost. The RR states the Forced
    Interrupt equivalence for When Defeated and When Completed only."""
    wr = timing.classify("When Revealed")
    assert wr.canonical == "When Revealed"
    assert wr.rung == 3
    assert wr.rung > timing.classify("Forced Interrupt").rung


def test_when_defeated_and_completed_are_forced_interrupts(conn):
    for alias in ("When Defeated", "When Completed"):
        c = timing.classify(alias)
        assert c.canonical == "Forced Interrupt", alias
        assert (c.rung, c.sub) == (2, "b"), alias


def test_boost_is_a_trigger_not_flavour_text(conn):
    """Boost is bold on 428 cards; the chart makes it rung 3."""
    assert timing.classify("Boost").rung == 3


def test_form_qualifier_is_split_from_the_trigger(conn):
    t = timing.classify("Hero Action")
    assert t.qualifier == "Hero"
    assert t.canonical == "Action"
    assert t.rung is None      # actions are not on the chart


def test_parenthetical_qualifier_is_handled(conn):
    t = timing.classify("When Revealed (Hero)")
    assert t.canonical == "When Revealed"
    assert t.qualifier == "Hero"


def test_bold_text_that_is_not_a_trigger_is_rejected(conn):
    for s in ("Contents", "Expert Mode Only.", "Nonsense"):
        assert timing.classify(s) is None, s


def test_citations_verify_against_the_indexed_rules(conn):
    assert timing.verify_citations(conn) == []


def test_a_reworded_rules_entry_fails_loudly(conn):
    conn.execute("UPDATE rules_entries SET body = 'Rewritten.' "
                 "WHERE term = 'Forced'")
    conn.commit()
    broken = timing.verify_citations(conn)
    assert any("Forced" in b for b in broken)


def test_explain_reports_what_beats_what(conn):
    result = timing.explain(conn, "Response")
    assert result["rung"] == 4
    befores = [b["text"] for b in result["resolves_after"]]
    assert any("Forced Response" in b for b in befores)


def test_explain_accepts_an_alias(conn):
    assert timing.explain(conn, "When Defeated")["canonical"] \
        == "Forced Interrupt"


def test_unknown_trigger_is_reported_not_guessed(conn):
    assert timing.explain(conn, "Bamf")["canonical"] is None


@pytest.mark.integration
def test_real_corpus_triggers_are_classified(real_index):
    """Every bold prefix on a player card either classifies or is on the
    not_triggers list. A new release adding a trigger fails here."""
    rows = real_index.execute(
        "SELECT DISTINCT raw_prefix FROM timing_triggers "
        "WHERE canonical IS NULL").fetchall()
    assert rows == [], [r["raw_prefix"] for r in rows]


@pytest.mark.integration
def test_real_chart_and_citations_verify(real_index):
    assert timing.verify_chart(real_index) == []
    assert timing.verify_citations(real_index) == []


@pytest.mark.integration
def test_round_structure_has_ten_steps(real_index):
    steps = timing.round_structure(real_index)
    assert len(steps) == 10
    assert steps[0]["step"] == 1
    assert all(s["see"] for s in steps)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_timing.py -v -m "not integration"`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.timing'`

- [ ] **Step 4: Add tables to `schema.py`**

```sql
-- The RR's Simultaneous Timing Priority chart (ABILITY entry, p.5),
-- parsed from the indexed rules rather than transcribed.
CREATE TABLE IF NOT EXISTS timing_chart (
    rung INTEGER NOT NULL,
    sub  TEXT,                  -- lettered sub-tier, or NULL
    text TEXT NOT NULL,
    PRIMARY KEY (rung, COALESCE(sub, ''))
);

CREATE TABLE IF NOT EXISTS timing_triggers (
    code       TEXT NOT NULL REFERENCES cards(code),
    ordinal    INTEGER NOT NULL,
    raw_prefix TEXT NOT NULL,   -- exactly as printed
    qualifier  TEXT,            -- Hero, Alter-Ego, First Player, Mission
    forced     INTEGER NOT NULL DEFAULT 0,
    canonical  TEXT,            -- NULL when unclassifiable: a loud failure
    rung       INTEGER,
    sub        TEXT,
    PRIMARY KEY (code, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_timing_canonical
    ON timing_triggers(canonical);

-- The RR's Round Overview (p.4): ten steps, each naming the glossary
-- entries that govern it. Parsed, not hand-copied.
CREATE TABLE IF NOT EXISTS round_steps (
    step        INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    see         TEXT NOT NULL,   -- comma-separated RR entry names
    source_doc  TEXT NOT NULL
);
```

- [ ] **Step 5: Write `timing.py`**

```python
"""Trigger timing and priority (added 2026-08-21; not in the original spec).

The ordering is the RR's own Simultaneous Timing Priority chart, which sits
inside the ABILITY entry on p.5 and therefore has no header of its own and
no index line. It is parsed from the indexed rules rather than transcribed,
and compared against `expected_chart` so a revision is reported.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "_bundled" / "timing.yaml"
_CONFIG: dict | None = None

PAREN_RE = re.compile(r"^(.*?)\s*\((.*?)\)\s*$")
# The full sentence wraps across two extracted lines, so the anchor is the
# fragment that fits on one: "...the timing / priority of abilities with the
# same triggering condition  is:".
CHART_HEAD_RE = re.compile(
    r"of abilities with the same triggering condition", re.I)
CHART_RUNG_RE = re.compile(r"^(\d)\.\s+(.*)$")
CHART_SUB_RE = re.compile(r"^([a-e])\.\s+(.*)$")
ROUND_STEP_RE = re.compile(
    r"^\s*(\d{1,2})\.\s*(.+?)\.\s*See\s*:\s*(.+?)\s*$", re.I)


@dataclass
class Trigger:
    raw: str
    qualifier: str | None
    forced: bool
    canonical: str
    rung: int | None
    sub: str | None


def load_config(path: Path | None = None) -> dict:
    global _CONFIG
    if path is not None:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    if _CONFIG is None:
        _CONFIG = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return _CONFIG


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip().rstrip(":").strip()


def _canon(s: str) -> str:
    """Compare chart text ignoring the RR's curly quotes and stray spacing
    before a closing quote (`\u201cInterrupt \u201d`)."""
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r'\s+"', '"', s)
    return " ".join(s.split()).strip().lower()


def parse_chart(body: str) -> list[dict]:
    """Extract the numbered chart with its lettered sub-tiers."""
    lines = [" ".join(l.split()) for l in body.split("\n")]
    try:
        first = next(i for i, l in enumerate(lines) if CHART_HEAD_RE.search(l))
    except StopIteration:
        return []

    rows, rung = [], None
    for line in lines[first + 1:]:
        if not line:
            continue
        m = CHART_RUNG_RE.match(line)
        if m:
            rung = int(m.group(1))
            rows.append({"rung": rung, "sub": None, "text": m.group(2).strip()})
            continue
        m = CHART_SUB_RE.match(line)
        if m and rung is not None:
            rows.append({"rung": rung, "sub": m.group(1),
                         "text": m.group(2).strip()})
            continue
        if rows and not line.startswith("See also"):
            # A rung wrapped onto a second line.
            if re.match(r"^[A-Za-z\u201c]", line) and len(rows[-1]["text"]) < 90:
                rows[-1]["text"] = f'{rows[-1]["text"]} {line}'.strip()
                continue
        break
    return rows


def chart(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT rung, sub, text FROM timing_chart "
        "ORDER BY rung, COALESCE(sub, '')")]


def verify_chart(conn) -> list[str]:
    """Compare the parsed chart against the copy recorded on 2026-08-21."""
    config = load_config()
    got = [(r["rung"], r["sub"], _canon(r["text"])) for r in chart(conn)]
    want = [(r["rung"], r["sub"], _canon(r["text"]))
            for r in config["expected_chart"]]
    if got == want:
        return []
    problems = []
    if len(got) != len(want):
        problems.append(f"chart has {len(got)} rows, expected {len(want)}")
    for g, w in zip(got, want):
        if g != w:
            problems.append(f"rung {w[0]}{w[1] or ''}: expected {w[2]!r}, "
                            f"got {g[2]!r}")
    if not problems:
        problems.append("chart differs from expected_chart")
    return problems


def classify(prefix: str) -> Trigger | None:
    """Split a printed bold prefix into qualifier, forced flag, and the
    chart rung it occupies. Returns None for bold text that is not a
    triggered ability."""
    config = load_config()
    raw = _norm(prefix).strip('"').strip("\u201c\u201d")
    if not raw or raw in config["not_triggers"]:
        return None

    qualifier = None
    body = raw
    m = PAREN_RE.match(raw)
    if m and m.group(2) in config["qualifiers"]:
        body, qualifier = m.group(1).strip(), m.group(2)
    elif m:
        return None

    for q in sorted(config["qualifiers"], key=len, reverse=True):
        if body.startswith(q + " "):
            qualifier = qualifier or q
            body = body[len(q) + 1:].strip()
            break

    alias = config["aliases"].get(body)
    canonical = alias["canonical"] if alias else body

    if canonical in config["triggers"]:
        slot = config["triggers"][canonical]
    elif canonical in config["outside_chart"]:
        slot = {"rung": None, "sub": None}
    else:
        return None

    return Trigger(raw=raw, qualifier=qualifier,
                   forced=canonical.startswith("Forced"),
                   canonical=canonical, rung=slot["rung"], sub=slot["sub"])


def explain(conn, trigger: str) -> dict:
    t = classify(trigger)
    if t is None:
        return {"query": trigger, "canonical": None,
                "message": f"{trigger!r} is not a timing trigger this "
                           f"reference knows. Run `mc-jarvis timing` for "
                           f"the chart."}
    config = load_config()
    rows = chart(conn)
    key = (t.rung, t.sub or "")
    before = [r for r in rows if r["rung"] is not None and t.rung is not None
              and (r["rung"], r["sub"] or "") > key and r["sub"]]
    after = [r for r in rows if r["rung"] is not None and t.rung is not None
             and (r["rung"], r["sub"] or "") < key and r["sub"]]
    return {
        "query": trigger,
        "canonical": t.canonical,
        "qualifier": t.qualifier,
        "forced": t.forced,
        "rung": t.rung,
        "sub": t.sub,
        "aliased_from": trigger if _norm(trigger) in config["aliases"] else None,
        "resolves_before": before,
        "resolves_after": after,
        "tie_breaks": config["tie_breaks"],
        "cards": _cards_with(conn, t.canonical) if conn is not None else [],
    }


def _cards_with(conn, canonical: str, limit: int = 15) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT DISTINCT c.code, c.name, t.raw_prefix "
        "FROM timing_triggers t JOIN cards c ON c.code = t.code "
        "WHERE t.canonical = ? ORDER BY c.code LIMIT ?",
        (canonical, limit))]


def verify_citations(conn) -> list[str]:
    """Every quote in timing.yaml must still appear in the indexed RR, so a
    rewording upstream names the stale rule instead of leaving this file
    quietly wrong."""
    config = load_config()
    broken: list[str] = []
    sources: list[tuple[str, dict]] = [("chart_source", config["chart_source"])]
    for name, r in config["aliases"].items():
        sources.append((f"alias:{name}", r))
    for i, r in enumerate(config["tie_breaks"]):
        sources.append((f"tie_break:{i}", r))

    for label, entry in sources:
        quote = entry.get("quote")
        if not quote:
            continue
        row = conn.execute(
            "SELECT body FROM rules_entries WHERE lower(term) = lower(?) "
            "LIMIT 1", (entry["rr_entry"],)).fetchone()
        if row is None:
            broken.append(f"{label}: no RR entry named {entry['rr_entry']!r}")
        elif _canon(quote) not in _canon(row["body"]):
            broken.append(f"{label}: quote no longer found in "
                          f"{entry['rr_entry']!r} (p.{entry['rr_page']})")
    return broken


def build(conn: sqlite3.Connection) -> int:
    from .cardtext import BOLD_RE
    config = load_config()

    conn.execute("DELETE FROM timing_chart")
    row = conn.execute(
        "SELECT body FROM rules_entries WHERE lower(term) = ? LIMIT 1",
        (config["chart_source"]["rr_entry"].lower(),)).fetchone()
    if row is not None:
        conn.executemany(
            "INSERT INTO timing_chart (rung, sub, text) VALUES (?, ?, ?)",
            [(r["rung"], r["sub"], r["text"]) for r in parse_chart(row["body"])])

    conn.execute("DELETE FROM timing_triggers")
    rows = []
    for card in conn.execute(
            "SELECT code, text FROM cards WHERE text IS NOT NULL"):
        for i, prefix in enumerate(BOLD_RE.findall(card["text"] or "")):
            norm = _norm(prefix)
            if not norm or len(norm) > 40 or norm in config["not_triggers"]:
                continue
            t = classify(norm)
            rows.append((card["code"], i, norm,
                         t.qualifier if t else None,
                         int(t.forced) if t else 0,
                         t.canonical if t else None,
                         t.rung if t else None,
                         t.sub if t else None))
    conn.executemany(
        "INSERT OR REPLACE INTO timing_triggers "
        "(code, ordinal, raw_prefix, qualifier, forced, canonical, rung, sub) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    _build_round_steps(conn)
    conn.commit()
    return len(rows)


def _build_round_steps(conn) -> None:
    """Parse the RR's Round Overview (p.4) rather than hand-copying it."""
    row = conn.execute(
        "SELECT body, source_doc FROM rules_entries "
        "WHERE lower(term) = 'round overview' LIMIT 1").fetchone()
    conn.execute("DELETE FROM round_steps")
    if row is None:
        return
    steps = []
    for line in row["body"].split("\n"):
        m = ROUND_STEP_RE.match(" ".join(line.split()))
        if m:
            steps.append((int(m.group(1)), m.group(2).strip(),
                          m.group(3).strip(), row["source_doc"]))
    conn.executemany(
        "INSERT OR REPLACE INTO round_steps "
        "(step, description, see, source_doc) VALUES (?, ?, ?, ?)", steps)


def round_structure(conn) -> list[dict]:
    return [{"step": r["step"], "description": r["description"],
             "see": [s.strip() for s in r["see"].split(",") if s.strip()],
             "source_doc": r["source_doc"]}
            for r in conn.execute(
                "SELECT * FROM round_steps ORDER BY step")]


def handle(args) -> int:
    from .cards import _open
    from .cli import emit
    conn = _open()
    config = load_config()
    cite = (f"[RR {config['chart_source']['rr_entry']} "
            f"p.{config['chart_source']['rr_page']}]")

    if getattr(args, "round", False):
        steps = round_structure(conn)
        if args.json:
            emit(steps, as_json=True)
            return 0 if steps else 1
        if not steps:
            print("round structure not indexed - run `mc-jarvis status`")
            return 1
        for s in steps:
            print(f"{s['step']:>2}. {s['description']}")
            print(f"    see: {', '.join(s['see'])}")
        return 0

    if getattr(args, "trigger", None):
        result = explain(conn, args.trigger)
        if args.json:
            emit(result, as_json=True)
            return 0 if result["canonical"] else 1
        if not result["canonical"]:
            print(result["message"])
            return 1
        slot = (f"rung {result['rung']}{result['sub'] or ''}"
                if result["rung"] else "not on the priority chart")
        print(f"{args.trigger}  ->  {result['canonical']}  ({slot})  {cite}")
        if result["aliased_from"]:
            print(f"  The RR defines this as equivalent to "
                  f"{result['canonical']}.")
        if result["qualifier"]:
            print(f"  Form restriction: {result['qualifier']}")
        for label, rows in (("Resolves after", result["resolves_after"]),
                            ("Resolves before", result["resolves_before"])):
            if rows:
                print(f"  {label}: " + ", ".join(r["text"] for r in rows))
        if result["cards"]:
            print("\n  Example cards:")
            for c in result["cards"][:8]:
                print(f"    {c['code']:<8} {c['name']:<28} {c['raw_prefix']}")
        return 0

    rows = chart(conn)
    if args.json:
        emit({"chart": rows, "tie_breaks": config["tie_breaks"],
              "source": config["chart_source"]}, as_json=True)
        return 0
    if not rows:
        print("timing chart not indexed - run `mc-jarvis status`")
        return 1
    print(f"Simultaneous timing priority, for one triggering condition "
          f"{cite}:\n")
    for r in rows:
        label = f"{r['rung']}{r['sub'] or ''}."
        indent = "   " if r["sub"] else ""
        print(f"  {indent}{label:<4} {r['text']}")
    print("\nTie-breaks and refinements:")
    for tb in config["tie_breaks"]:
        print(f"  - {tb['rule']}")
        print(f"    [RR {tb['rr_entry']} p.{tb['rr_page']}]")
    return 0
```

- [ ] **Step 6: Add the command to `cli.py`**

In `build_parser`, after `encounter`:

```python
    tim = _leaf(sub, "timing", "trigger ordering and the game round")
    tim.add_argument("trigger", nargs="?", default=None,
                     help="a timing trigger, e.g. Response, When Defeated")
    tim.add_argument("--round", action="store_true",
                     help="show the game round structure instead")
```

and in `_dispatch`:

```python
    if name == "timing":
        from . import timing
        return timing.handle(args)
```

- [ ] **Step 7: Wire it into the build**

In `init.rebuild_index`, after `counts["rules_links"] = rules.build_links(conn)`:

```python
    from . import timing
    counts["timing_triggers"] = timing.build(conn)
    broken = timing.verify_chart(conn) + timing.verify_citations(conn)
    if broken:
        # Not fatal: the card index is still correct and useful. But the
        # timing reference is now quoting rules text that no longer says
        # what it claims, so say so rather than serving it silently.
        conn.execute(
            "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
            ("timing_citations_broken", json.dumps(broken)))
        print("WARNING: the timing reference no longer matches the rules "
              "it is built from:")
        for b in broken:
            print(f"  {b}")
```

Add `import json` to `init.py`. Also add `timing_citations_broken` to the `status` payload in `update.py`, alongside `unmapped_glyphs`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_timing.py -v -m "not integration"`
Expected: PASS, 14 tests

- [ ] **Step 9: Verify against the real corpus**

```bash
uv run python -c "
from mc_jarvis import index, paths, timing
conn = index.connect(paths.db_path())
print('triggers indexed:', timing.build(conn))
print('broken citations:', timing.verify_citations(conn) or 'none')
print()
for r in conn.execute('SELECT raw_prefix, COUNT(*) n FROM timing_triggers '
                      'WHERE canonical IS NULL GROUP BY raw_prefix '
                      'ORDER BY n DESC LIMIT 20'):
    print(f'  UNCLASSIFIED  {r[\"raw_prefix\"]:<30} {r[\"n\"]}')
"
mc-jarvis timing
mc-jarvis timing "When Defeated"
mc-jarvis timing "Hero Action"
mc-jarvis timing --round
```

Expected: zero broken citations and zero chart differences; the chart prints ten rows with the `[RR Ability p.5]` cite; `When Defeated` reports itself as a Forced Interrupt on rung 2b, and `When Revealed` reports rung 3.

Verified 2026-08-21 against the real PDF: the page-spanning chunker from Task 13 puts the chart inside the `ABILITY` body (5,453 characters, crossing the p.4/p.5 break), and `parse_chart` returns exactly the ten expected rows.

**Every unclassified prefix is a decision, not a bug to suppress.** Read the list: if it is a real trigger, add it to `ladder` or `outside_ladder`; if it is bold flavour text, add it to `not_triggers`. Encounter-side prefixes (`Contents`, `Preparation`, `Standard Mode Only.`) are the expected bulk. Do not widen `not_triggers` with a wildcard.

- [ ] **Step 10: Teach the skill about it**

Add to `SKILL.md`'s command table:

```markdown
| trigger ordering | `mc-jarvis timing [<trigger>] [--round]` |
```

and a section:

```markdown
## Timing questions

"Does my Response happen before their Forced Response?" is the question
players get wrong most often, and the Rules Reference has no single entry
that answers it — the rules are spread over six entries.

Run `mc-jarvis timing` for the ordering, or `mc-jarvis timing <trigger>`
for one trigger with its citation and example cards. Quote the rung and
the page.

The ordering comes from the RR's own Simultaneous Timing Priority chart
(`ABILITY`, p.5). Cite it.

Three things worth stating whenever they come up, because all three
surprise people:

- **When Defeated and When Completed are Forced Interrupts. When Revealed
  is not.** The RR states that equivalence for the first two only; the
  chart puts When Revealed a full tier later, on rung 3 alongside Boost.
- **Constant abilities, delayed effects and lasting effects sit above
  every trigger**, and status-card Forced Interrupts outrank ordinary ones.
- **Forced beats optional at the same tier**, and the first player breaks
  every remaining tie — including between abilities they do not control.
```

- [ ] **Step 11: Commit**

```bash
git add src/mc_jarvis/timing.py src/mc_jarvis/schema.py src/mc_jarvis/cli.py \
        src/mc_jarvis/init.py src/mc_jarvis/update.py config/timing.yaml \
        skill/ tests/test_timing.py
git commit -m "feat: timing reference with RR-cited trigger ordering"
```

Add the `_bundled` link for the new config, alongside the two from Task 1 Step 8:

```bash
ln -sfn ../../../config/timing.yaml src/mc_jarvis/_bundled/timing.yaml
```

and add `"config/timing.yaml" = "src/mc_jarvis/_bundled/timing.yaml"` to the `force-include` block in `pyproject.toml`.

---

## Done criteria

- [ ] `uv run pytest tests/ -v` — all tests pass, unit and integration
- [ ] `mc-jarvis doctor` exits 0
- [ ] `mc-jarvis status` reports ~4,298 cards, 72 identities, ~216 rules entries, empty `unmapped_glyphs`
- [ ] The setup audit reports exactly four identities, all covered
- [ ] `git status` is clean and no fetched artifact is tracked: `git ls-files | grep -Ei '\.(pdf|sqlite)$|marvelsdb/' ` returns nothing
- [ ] An agent in the workspace answers a card question and a rules question with citations, without being told which command to run
- [ ] `mc-jarvis timing` prints the ladder with a page cite on every rung
- [ ] `timing.verify_citations` returns empty, and no prefix on a player card is unclassified
