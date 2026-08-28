# mc-jarvis — Design

**Date:** 2026-08-20
**Status:** Approved for planning

## 1. What this is

An agent-agnostic assistant for Marvel Champions: The Card Game players. It answers card
questions, validates and critiques decks, and rules on rules disputes with citations.

The persona is Jarvis — Tony Stark's assistant. Dry, precise, understated. Leads with the
answer, then the reasoning. Never pads. No honorific by default (configurable).

### Goals

- Answer card and encounter questions from a complete, current local index.
- Import a marvelcdb deck, validate its legality, and report its statistical shape.
- Answer rules questions with a Rules Reference entry name and page number.
- Work on Claude Code, Codex, opencode, pi, or any agent that can run a shell command.
- Ship no copyrighted content in the repository.

### Non-goals

- Playing the game for the user, or tracking live game state.
- A knowledge graph. Card data is relational; `graphify` is the wrong tool here and this
  is a deliberate omission, not an oversight.
- A vector store. See §3.
- Hosting anything. Everything runs on the user's machine against their own data.

## 2. The portability contract

There are two kinds of intelligence in this system and they travel differently.

| Capability | Implementation | Portability |
|---|---|---|
| Card/encounter search, legality, deck stats, rules lookup, meta aggregation | Python CLI over SQLite | **Identical on every agent** |
| Deck coaching, cut/add advice, build-from-scratch | Prompt text executed by the host model | Portable in form, variable in quality |

**Stated contract:** mc-jarvis guarantees the same facts and the same rulings on every
agent. Coaching quality tracks the host model.

This has a design consequence that governs every later decision: **push everything
possible below the CLI line.** Curve analysis, resource math, "cards commonly played with
this hero" — all deterministic. Anything a script can compute must not be left to the
model, because that is the part that varies by harness.

## 3. Why there is no RAG layer

The card corpus is 11 MB — 4,298 cards, of which 1,607 are player-legal — across 116 JSON
files. Real card queries are structural ("Justice allies costing 2 or less with a thwart
ability"), and vector similarity is actively bad at those. The answer is SQLite with an
FTS5 index over card text.

The Rules Reference is organised as alphabetical entries by term ("Confused", "Stunned",
"Villain Phase"). Chunked by entry, a rules lookup is a dictionary hit, not a similarity
search. FTS5 covers the residual case where a question does not name its term.

No embeddings, no vector database, no embedding-refresh pipeline. This removes an entire
subsystem and its dependencies.

## 4. Distribution principle

**The repository ships code and configuration only.** No card text, no rules text, no
PDFs, no built index, no cached decklists. `data/` and all fetched artifacts are
gitignored.

Everything copyrighted is fetched to the user's machine at init time from sources they are
entitled to read: the community-maintained card data repository, and FFG's own product
page for the rules PDFs. This is a hard boundary.

A useful side effect: because the rules manifest is discovered at runtime rather than
hardcoded, expansion rulebooks are handled for free as FFG publishes them.

## 5. Architecture

```
mc-jarvis/                      # normal Python package: uv tool install / pipx install
  src/mc_jarvis/
    cli.py                      # argparse entry; every command supports --json
    init.py                     # one-time bootstrap
    update.py                   # refresh sources, rebuild index
    index.py                    # SQLite schema + build
    cards.py                    # card and encounter queries
    deck.py                     # marvelcdb fetch, legality, stats
    rules.py                    # rules entry lookup and full-text search
    pdf.py                      # PDF download, extract, chunk
    collection.py               # owned-pack filtering
    meta.py                     # marvelcdb decklist crawl + aggregation (P3)
  config/
    legality.yaml               # hand-encoded deckbuilding rules
    glyphs.yaml                 # private-use codepoints -> readable tokens
  skill/mc-jarvis/
    SKILL.md                    # the agent brief — single source of truth
    references/                 # on-demand detail (per-harness browser recipes)
  AGENTS.md                     # contributor docs for this repo only (see §7)
  tests/
```

### Data directory

Resolved as `$MC_JARVIS_DATA` -> `$XDG_DATA_HOME/mc-jarvis` -> `~/.local/share/mc-jarvis`.
Never alongside the package.

```
<data>/
  marvelsdb/         # extracted tarball of zzorba/marvelsdb-json-data
  rules/
    manifest.json    # discovered PDF list: title, size, date, url
    pdf/             # downloaded PDFs
    txt/             # extracted text
  mc.sqlite          # the index
  meta/              # cached marvelcdb decklists (P3)
  collection.yaml    # user's owned packs
```

Consequence worth naming: Claude Code, Codex, and opencode on the same machine share one
index and one collection. Build once, use anywhere.

### 5.1 Command surface

This is the contract. `SKILL.md` teaches these and nothing else; every command supports
`--json` for machine consumption and a compact human-readable default. Every command that
returns cards honours `--owned` when a collection exists (Phase 1 — see §13).

Every subcommand takes an explicit verb; no parent command takes a bare positional. This
is not cosmetic: `card <query>` alongside `card show <x>` makes `card show Vision`
ambiguous in argparse, parsing `show` as the query.

| Command | Returns | Phase |
|---|---|---|
| `mc-jarvis init [--from-html F \| --browser]` | Bootstrap summary | 1 |
| `mc-jarvis update` | What changed, what was revised upstream | 1 |
| `mc-jarvis install-skill [--link] [--global]` | Places the skill in the workspace (or globally) | 1 |
| `mc-jarvis doctor` | Prerequisite and environment check; non-zero on hard failure | 1 |
| `mc-jarvis status` | Index age, card/rules counts, staleness warning | 1 |
| `mc-jarvis card search <query> [--aspect --type --cost --trait --text --limit]` | Matching cards | 1 |
| `mc-jarvis card show <name-or-code> [--explain]` | One card, full detail, linked faces; lists candidates when a name is ambiguous; `--explain` expands keywords with rules text and page cites | 1 |
| `mc-jarvis identity <name>` (alias `hero`) | All identity faces and forms, signature set, obligation, nemesis | 1 |
| `mc-jarvis encounter <villain-or-set>` | Villain stats by difficulty, set contents | 1 |
| `mc-jarvis rules show <term>` | RR entry, body, page cite, `See also`, and cards using the keyword | 1 |
| `mc-jarvis rules search <text>` | FTS5 hits ranked, each with page cite | 1 |
| `mc-jarvis deck fetch <id-or-url>` | Normalised deck: hero, aspect(s), resolved slots | 1 |
| `mc-jarvis deck check <deck>` | Legality verdict with per-rule pass/fail | 1 |
| `mc-jarvis deck stats <deck>` | Curves, type mix, resource mix, ability density | 1 |
| `mc-jarvis collection set/show` | Owned packs | 1 |
| `mc-jarvis team <deck>...` | Cross-deck coverage, unique collisions | 2 |
| `mc-jarvis mcp` | stdio MCP server exposing the above | 2 |
| `mc-jarvis meta <hero> [--aspect]` | Ranked card inclusion rates | 3 |

Deck arguments accept a marvelcdb id, a marvelcdb URL, or a local JSON file, so decks
never have to round-trip through the network twice.

Coaching, team advice, and build-from-scratch are **not** commands. They are prompt
recipes in `SKILL.md` that compose these commands and then ask the model to judge. That
boundary is what makes the deterministic half identical across agents (§2).

## 6. Requirements and installation

A player who wants a rules assistant should not have to become a sysadmin first. The
design target is **no system packages and two pure-Python wheels**, so that
`uv tool install mc-jarvis` is the whole story on Linux, macOS, and Windows.

### Required

| Requirement | Why | Notes |
|---|---|---|
| Python 3.10+ | `X | Y` type syntax; nothing newer is used | Floor is 3.10, not 3.11 — the TOML decision above removed the only reason for a higher one. Verified on 3.14.6 |
| `sqlite3` with FTS5 | Card and rules full-text search | Present in stock CPython (verified: SQLite 3.51.2, FTS5 available). Some minimal/distro builds omit FTS5 — `doctor` checks at runtime rather than assuming |
| `pypdf` | Rules PDF text extraction | Pure Python wheel |
| `PyYAML` | Config and collection files | Pure Python wheel; see below |

HTTP uses stdlib `urllib`. Nothing else is required.

**Config format is YAML, not TOML.** TOML would have kept the count at one dependency,
but stdlib `tomllib` is read-only — and `collection.yaml` is written by the tool — while
TOML's nested-table syntax is a poor fit for `legality.yaml`, which holds nested
per-hero exceptions and is the file this design twice names as its highest risk. A
hand-edited config that resists hand-editing is a bad trade. PyYAML is a single pure-
Python wheel with `safe_load`/`safe_dump`; the claim being protected is *no system
packages*, and that survives intact.

### Deliberately *not* required

Each of these was assumed in an earlier draft and then verified away:

- **`git`** — the card data is fetched as a **1.5 MB tarball** from `codeload.github.com`
  and extracted with stdlib `tarfile`. Verified: 200 OK, 601 members, all pack JSON
  present. This is both smaller and faster than the 11 MB shallow clone, and it removes a
  system dependency outright. If `git` is present, `update` may use it for a cheaper
  incremental pull, but it is never required.
- **`poppler-utils` / `pdftotext`** — see below.
- **Playwright / any browser** — `init --from-html` covers the no-browser case (§11).

### Optional, with graceful degradation

| Optional | Buys you | Without it |
|---|---|---|
| `poppler-utils` (`pdftotext`) | Preserves the `»` sub-bullet marker, so nested rules clauses keep one more level of structure | pypdf is used; nesting flattens by one level. No loss of rules content |
| `playwright` (extras) | `init --browser` auto-fetches the FFG page | Use `init --from-html`, the documented default |
| `git` | Incremental card-data pull | Full 1.5 MB tarball each `update` |

### PDF extractor: why pypdf, and why not the others

Tested directly against the v18 Rules Reference, which is two-column:

| Extractor | Column order | Icon glyphs | Verdict |
|---|---|---|---|
| `pypdf` | **Correct** | All 13 PUA codepoints preserved (U+F520–F530) | **Default.** Pure Python, no system package |
| `pdftotext -raw` | **Correct** | Preserved; also keeps `»` | Used automatically when present |
| `pdftotext -layout` | Interleaved, unusable | — | Rejected |
| `pdfplumber` | Interleaved, unusable | — | Rejected |

Both viable extractors produce 71 pages and a workable set of ALL-CAPS entry headers
(356 via `pdftotext -raw`, 390 via pypdf). The extraction layer is written against a
common interface so either backend feeds the same chunker.

### `mc-jarvis doctor`

Because the whole point is running under agents we do not control, on machines we have
never seen, requirements are checked at runtime rather than assumed. `doctor` reports
Python version, FTS5 availability, which PDF backend is active, whether the browser and
`git` extras are present, data directory location and writability, index age, and network
reachability of the two upstreams — and exits non-zero on anything that would break a
Phase 1 command.

`init` runs the same checks first and refuses to start on a hard failure, naming the exact
missing piece and the install command for the user's platform. `SKILL.md` instructs the
agent to run `doctor` and surface its output whenever any command fails unexpectedly, so a
missing prerequisite is diagnosed rather than guessed at.

## 7. Agent integration

**The skill file is the single source of truth**, and it installs *globally* — not into a
project. `skill/mc-jarvis/SKILL.md` carries the Jarvis persona, the command surface,
worked examples, and the browser-fetch recipe for `init --from-html` (§11), which is
load-bearing: without it `init` is broken by default on precisely the non-Claude agents
this design exists to serve.

### Why not AGENTS.md

An earlier draft made repo-root `AGENTS.md` the source of truth. That was wrong, and the
reason matters enough to record so nobody re-promotes it. **AGENTS.md is discovered by
walking up the directory tree from the current working directory** — the nearest file
wins. A player asking "is my Spider-Man deck legal?" is sitting in their home directory,
not inside a checkout of this repository, so a repo-root `AGENTS.md` would never load in
the exact situation the tool exists for. It names a file that cannot reach its reader.

Skills, by contrast, are discovered from user-global directories regardless of cwd. That
is the right mechanism for a tool used from anywhere.

`AGENTS.md` stays in the repo, demoted to what it is actually good at: instructions for
someone working *on* mc-jarvis.

### Agent Skills is an open standard — of format, not of location

The SKILL.md format Anthropic created was released as an open standard, is stewarded at
[agentskills.io](https://agentskills.io), and is supported by 40-plus products including
Claude Code, Codex, opencode, pi, Gemini CLI, Cursor, GitHub Copilot, VS Code, Goose,
Amp, Kiro, and Factory. Writing one skill and having it work everywhere is the explicit
design goal of that standard, so mc-jarvis is a normal skill and gets this for free.

**The specification defines the format and says nothing about install paths.** Discovery
is left to each runtime. This is the single most important fact for this section, because
it means there is no one directory to target — and it is precisely why `install-skill`
detects directories rather than assuming a canonical one.

### Install scope: a workspace, not the whole machine

**The default install is workspace-scoped, not global.** A global skill loads its name and
description into every agent session on the machine, forever, so a Marvel Champions
assistant would announce itself in the middle of unrelated work. The context cost is
small; the judgement is not. A hobby tool should not be present in every dev session.

The resolution is that a player already has a natural workspace — a folder where their
decks and notes live — and that is where the skill belongs. `init` establishes it and
`install-skill` targets it:

```
~/marvel-champions/            # the player's workspace, wherever they choose
  .agents/skills/mc-jarvis/    # pi, opencode
  .claude/skills/mc-jarvis/    # Claude Code
  .codex/skills/mc-jarvis/     # Codex
  decks/
```

The skill activates when the player is working in that directory and is invisible
everywhere else. `--global` remains available for anyone who genuinely wants it
everywhere, and is never the default.

**This does not conflict with the AGENTS.md reasoning above.** That argument was never
"local scoping is wrong" — it was that the *mc-jarvis source repository* is a place the
player never visits. A directory the player deliberately works in is the opposite case.
The rule is: put the instructions where the player actually is.

**The trade being made:** ask a question outside the workspace and Jarvis will not answer,
because nothing is loaded there. That is the cost of not polluting every other session,
and it is the right default for a tool used deliberately rather than ambiently.

### Paths

`.agents/skills/` is the vendor-neutral convention the non-Anthropic tools converged on.
It is a convention, not a spec requirement — hence a small matrix rather than one path.

| Harness | Project paths | Global paths |
|---|---|---|
| pi | `.pi/skills/`, **`.agents/skills/`** (cwd and ancestors) | `~/.pi/agent/skills/`, `~/.agents/skills/` |
| opencode | `.opencode/skills/`, **`.agents/skills/`**, `.claude/skills/` | `~/.config/opencode/skills/`, `~/.agents/skills/`, `~/.claude/skills/` |
| Claude Code | `.claude/skills/` — "this project only" | `~/.claude/skills/` |
| Codex | `.codex/skills/` | `~/.codex/skills/` |

Three workspace directories cover all four harnesses: `.agents/` serves pi and opencode,
and Claude Code and Codex each read only their own vendor path.

Three operational notes, each a way this silently fails if ignored:

- **Trust.** Some harnesses gate project-level skills behind trusting the directory — pi
  loads them "only after the project is trusted." `install-skill` says so explicitly
  rather than leaving the player wondering why nothing activated.
- **Ancestor walking is bounded by the repository root.** Claude Code loads project
  skills from the start directory "and in every parent directory up to the repository
  root"; pi walks up to the git root, or to the filesystem root when not in a repo. Two
  consequences: a workspace at `$HOME` would be effectively global for pi, and a
  workspace nested inside an unrelated repository can be cut off from its own skill.
  `install-skill` therefore refuses `$HOME`, refuses a directory inside another
  repository, and runs `git init` on the workspace so the boundary is well-defined. That
  is worth doing on its own merits — a player's deck collection benefits from history.
- **Symlinks are supported and deduplicated.** Claude Code follows a symlinked skill
  directory and, when the same target is reachable from several locations, loads it once.
  That makes `--link` safe rather than merely convenient, and means the three workspace
  directories can point at one real directory without the skill appearing three times.

### Frontmatter

The spec requires `name` (lowercase, hyphens, must match the directory name) and
`description` (what it does *and* when to use it). It also defines optional `license`,
`compatibility`, `metadata`, and `allowed-tools`.

Two rules for this skill:

- **Use `compatibility`.** It exists to declare environment requirements and this skill
  has real ones — the spec's own example is literally `Requires Python 3.14+ and uv`.
  Ours states the Python floor and that `mc-jarvis` must be on `PATH`. Declaring it in
  the frontmatter is strictly better than letting the first command fail.
- **Do not use `allowed-tools`.** The spec marks it experimental and warns that support
  varies between implementations. A field that behaves differently per harness is exactly
  what breaks a one-file-everywhere design.

### Skill layout

The spec's conventions apply: keep `SKILL.md` under 500 lines and push detail into
`references/`, which agents load only on demand. The per-harness browser recipes for
`init --from-html` (§11) go in `references/` for that reason — every harness would
otherwise pay context for four recipes to use one.

Note what does *not* go in the skill: the spec allows a bundled `scripts/` directory, but
mc-jarvis ships its code as an installed CLI instead. Otherwise the same scripts would be
duplicated into every harness directory and could drift between them, which would break
the §2 guarantee that all agents compute identical answers.

### `mc-jarvis install-skill`

Places the skill under the current workspace for every harness in the matrix above, and
reports what it did and which directories need trusting. `--global` installs to the
user-global paths instead; it is opt-in, never inferred. **Copy by default; `--link` symlinks.** The default is chosen for the player who
installed via `uv tool install` and has no checkout at all — for them the skill ships
inside the wheel, and a symlink would have nothing to point at. `--link` serves the
developer, for whom a live link to the working tree is the point. A symlink into a git
checkout means `git pull` silently changes the installed skill and a moved checkout
breaks it, so that behaviour is opt-in rather than default.

The command is deliberately dumb: detect, place, report. It never rewrites the skill per
harness — the standard already makes one file portable, so per-harness variants would be
solving a problem that does not exist. `cp -r` and `ln -s` are documented as the manual equivalents.

## 8. Data model

### Cards

One row per card, loaded from `marvelsdb/pack/*.json`.

Four facts drive the schema. The first three concern identity — which rows are "the same
card" — and getting them wrong produces wrong deck advice rather than visible errors.

- **`duplicate_of` is an encounter-side field only.** All 342 cards carrying it are
  encounter cards; **zero player cards use it**. An earlier draft built the player-side
  canonical/alias model on this field, which would have done nothing. Player-side
  reprints — 14 of them, matched on name + type + faction across packs — carry no marker
  at all and must be detected structurally.
- **A shared name usually means a different card, not a reprint.** 79 player card names
  appear in more than one pack, but only 14 are true reprints. The dominant case is that
  **60 character names exist both as a hero/alter-ego and as an ally** — Angel, Cyclops,
  Black Panther, Captain Marvel and so on. Collapsing by name would merge a hero into an
  ally. `card show <name>` must therefore disambiguate rather than guess, and the index
  keys on `code`, never on name.
- **Unique-card matching is a graph over three name fields, not string equality.** See
  below; this is the subtlest thing in the data model.
- **Signature sets are keyed by `set_code`, not `card_set_code`.** `deck_requirements` is
  null on all 72 heroes, so hero signature sets are derived by grouping on `set_code`
  (verified: `set_code == "spider_man"` yields the hero, alter-ego, obligation, and all
  nine signature cards).

Aspect is `faction_code`. Values: `aggression`, `justice`, `leadership`, `protection`,
`basic`, `hero`, `pool`, `encounter`, `campaign`. Resource icons are discrete integer
fields (`resource_physical`, `resource_mental`, `resource_energy`, `resource_wild`).

**`pool` is a named exception, not a fifth aspect.** It is 34 Deadpool-specific cards from
the `deadpool` pack, and every one has `set_code: null` — so they are invisible to the
signature-set grouping rule above. Deadpool therefore needs an explicit hero-specific
allowance in `legality.yaml` covering both his signature set and his `pool` card pool.
Recorded here because it is precisely the class of silent error §15 warns about: without
this row, Deadpool decks validate against the wrong rules and nothing complains.

### Identity is the unit, and it is not one row

The Rules Reference is explicit that **identity is a player card type**:

> Identity is a player card type that represents which character a player is playing in
> the game. A player's identity card is a double-sided card that represents their hero on
> one side and their alter-ego on the other.

`hero` and `alter_ego` are *forms* — the faceup side — not separate cards. The marvelsdb
data stores each face as its own row, which is a storage detail, not the game's model.
The index therefore carries an **identity entity** that groups faces, keyed on `set_code`.

**Grouping on `back_link` alone is wrong**, because three shapes exist in the data:

| Shape | Example | Faces |
|---|---|---|
| Standard pair | Black Panther `01040a` / T'Challa `01040b` | 2 |
| Extra hero form | Angel `42001a` / Warren Worthington III `42001b` / **Archangel `42001c`** | 3 |
| Multiple identity cards | Ironheart `29001a/b`, `29002a/b`, `29003a/b` | 6 |

`back_link` points from a hero face to its alter-ego and is null on the extra forms, so
Archangel, Ant-Man's giant form (`12001c`, hand size 4), and Wasp's `13001c` all fall out
of a `back_link`-based grouping. Ironheart is stranger still: three complete identity
cards representing armour progression, which she levels up between during a single game
(hand size 4 → 5 → 6). All six rows are one identity.

Three consequences:

- **Identity faces never count toward deck size.** Counting rows would subtract six from
  an Ironheart deck. marvelcdb agrees — `hero_code` is returned separately and identity
  faces do not appear in `slots`.
- **The unique-match set below is a property of the identity**, not of a face. Every face
  contributes its title to the set.
- **`identity <name>` reports all faces and forms**, since "what are Angel's stats" has a
  different answer in Angel form and Archangel form.

Terminology follows the game throughout: `identity` is the canonical command with `hero`
kept as an alias, because players say "which hero are you playing" even though the card
type is identity.

### Unique-card matching

The Rules Reference (p.45) defines when two unique cards "match", and it is a
deckbuilding constraint, not just a play-time one:

> During deckbuilding, a player cannot include multiple matching cards in their deck. The
> identity is included in this evaluation.

Two unique cards match if either they share a title and both have no subtitle and no
alter-ego title, or the subtitle or alter-ego title of one matches the title, subtitle, or
alter-ego title of the other.

So the match key is the set of **every title in the identity or card — title, subtitle
(`subname`, present on 235 cards), and the titles of all linked faces** (via `back_link` — the local data's linkage field;
`linked_to_code` exists only in the marvelcdb API response), and two cards match when
those sets overlap under the rule above. The RR's own example is present in the data and
is the fixture this must be tested against:

| Code | Name | Subname | Type |
|---|---|---|---|
| `01040a` / `01040b` | Black Panther / T'Challa | — | hero / alter-ego |
| `51002` | T'Challa | — | ally |
| `23012` | Black Panther | T'Challa | ally |

All three match, so a T'Challa player may include none of the allies. **String equality on
`name` gets this wrong in both directions**: it misses `23012` (whose title is "Black
Panther" but matches via its subtitle), and it produces a false positive between the two
distinct Black Panther heroes `01040a` and `51001a`, which do *not* match: their
alter-ego titles are T'Challa and Shuri respectively (verified via `back_link`), so
neither matching clause fires.

This is a named rule in `legality.yaml` and a required check in `deck check`.

FTS5 virtual table over `name`, `text`, `traits`, `flavor`.

### Rules

One row per Rules Reference entry: `term`, `body`, `page`, `source_doc`, plus a
`see_also` edge table parsed from the entry's trailing `See also:` line. FTS5 over `body`.

## 9. Rules pipeline

Extraction runs behind a common interface with two backends — `pypdf` by default,
`pdftotext -raw` when poppler is present (§6). Both were verified against the v18 Rules
Reference; the chunker downstream is identical either way.

The critical property is **column order**. The Rules Reference is two-column, and the
naive extractors (`pdftotext -layout`, `pdfplumber`) interleave the columns into
unreadable text. `pypdf` and `pdftotext -raw` both read it correctly. This is the single
constraint that disqualifies otherwise reasonable libraries.

Verified properties, shared by both backends unless noted:

- 71 pages, with page boundaries recoverable for citations (form feeds under `pdftotext`,
  page index under `pypdf`).
- Entry headers are ALL-CAPS lines; the regex `^[A-Z][A-Z0-9 ,'/&()-]{2,60}$` yields 356
  candidates under `pdftotext -raw` and 390 under `pypdf`. Both avoid the intra-word
  letter-spacing that `-layout` introduced (`AMPLIF Y` for `AMPLIFY`).
- **Backend difference:** `pdftotext -raw` preserves the `»` sub-bullet marker; `pypdf`
  drops it, flattening nested clauses by one level. Content is unaffected, so this is a
  readability preference, not a correctness issue — which is why poppler stays optional.
- Icon glyphs survive as Unicode private-use codepoints under both backends (13 of them,
  U+F520–F530; the amplify icon is U+F521).
  `config/glyphs.yaml` maps these to readable tokens such as `[amplify]` during
  extraction. Unmapped codepoints are preserved verbatim and logged, so gaps are visible
  rather than silent.

Non-RR documents (expansion rulebooks, campaign logs) lack the alphabetical entry
structure. They are chunked by page with their heading text, and are searchable via FTS5
but not entry-addressable. This is a deliberate quality difference and the CLI labels it.

**Every rules answer cites the entry name and page.** An uncited ruling is worthless in an
argument at the table.

## 10. Deck pipeline

Source: `GET https://marvelcdb.com/api/public/decklist/<id>` — returns `hero_code`,
`hero_name`, `slots` (a `card_code -> quantity` map), and `meta`.

Three verified traps the parser must handle:

1. **`meta` is a JSON string on some endpoints and an already-decoded object on others.**
   Parse defensively for both. This field, not card factions, is the authoritative
   declared aspect.
2. **`aspect2` exists.** Dual-aspect decks are real and the validator must support them.
   A `format` key also appears (observed value: `legacy`) and affects legality.
3. **Linked faces must not double-count.** Heroes are `01001a` / `01001b` joined by
   `linked_to_code`, and multi-part cards appear as separate slots (`01043a` through
   `01043d`). Deck-size math counts the deck-legal face only.

### Copies: `quantity`, `deck_limit`, and what the collection actually constrains

`quantity` is how many physical copies a pack contains; `deck_limit` is how many a deck
may contain. They are different numbers and the distinction matters for deckbuilding — but
the relationship between them turns out to collapse the problem.

**Verified across all 1,607 player cards: `deck_limit` never exceeds `quantity` — zero
violations per printing, and zero when grouped across all printings of a card.** The
second check matters: a card printed at 1 copy in every pack it appears in would break
the invariant even though no single row does. FFG prints at least as many copies as a deck is allowed
to use — Spider-Man's set contains 3 Swinging Web Kick because the limit is 3.

The consequence is that **owning a pack is binary, not a count**. If you own any pack
containing a card, you have enough physical copies to play it to its deck limit, so the
collection filter is `WHERE pack_code IN (owned)` and never a sum over printings. Owning
two packs that both contain a card gives more physical copies but changes nothing, since
`deck_limit` binds first. No copy arithmetic anywhere in the system.

This is worth stating explicitly precisely because the intuitive model — "count how many
I own, compare to how many I want" — is the wrong one, and someone will otherwise build
it. If a future release ever breaks the invariant, the index build asserts it and fails
loudly rather than quietly under-counting.

Two related rules:

- **`deck_limit: null` on 120 player cards** (heroes, alter-egos, and 54 signature or
  campaign cards such as the `iron_man_leader` set). Null is not "unlimited": the limit
  falls back to `quantity`. Without this rule the validator has no cap on those cards and
  accepts arbitrary quantities.
- **`is_unique` is consistent with the above** — all 653 unique player cards have
  `deck_limit` 1 or null — so uniqueness is enforced by the matching rule above, not by
  a separate copy count.

### Cards that sit outside the deck

Several heroes have cards that are not part of the constructed deck. The deck-size and
`deck_limit` checks must exclude them, and **the data marks them three different ways —
one of which is no marking at all.**

**1. The `permanent` keyword — structured and reliable.** RR: a permanent card's constant
ability is "Set this card aside during setup," so it never enters the deck. 102 cards
carry `permanent: true` corpus-wide, 25 of them player cards across 13 hero sets. This
single flag covers most of the special cards people think of by name: Wolverine's Claws,
X-23's Claws, Psylocke's Psi-Knife and Psi-Katana, Vision's Intangible, Spectrum's three
forms, and both of Sp//dr's in-play cards.

**2. `hero_special` set type — structured and reliable.** `sets.json` classifies six sets
as `card_set_type_code: hero_special`, the separate decks a hero plays from alongside
their own:

`doctor_strange_invocation_deck`, `storm_weather_deck`, `iceman_frostbite`,
`hercules_labor_deck`, `hercules_gift_deck`, `daredevil_sense_deck`

**3. Nothing at all — and this is the case that matters.** Rogue's *Touched* carries
`deck_limit: 1`, `quantity: 1`, `permanent: null`, in the ordinary `rogue` set;
structurally it is indistinguishable from any other signature upgrade. Valkyrie's
*Death-Glow* is the same. In both cases the only evidence is prose on the identity card:

> **Forced Response**: After the player phase begins, find Touched and set it aside.
> — Rogue

> **Setup:** Set the Death Glow upgrade aside, out of play.
> — Brunnhilde

No query over the structured fields finds these.

#### The setup audit — a detection rule, not a list

Enumerating these by hand does not converge; every hero release can add one. So the index
build runs an audit instead: **scan identity-card text for setup and set-aside language,
and flag any identity whose implied out-of-deck cards are not already covered by
`permanent`, `hero_special`, or an explicit entry in `legality.yaml`.**

Run against the current corpus, that scan returns exactly four identities — and they are
the right four:

| Identity | Implied by text | Already covered? |
|---|---|---|
| Bobby Drake (Iceman) | "begins the game with 6 Frostbite upgrades set aside" | Yes — `hero_special` |
| Riri Williams (Ironheart) | "Begin the game with this card. Set your other identities aside." | Yes — identity grouping (§8) |
| Rogue | "find Touched and set it aside" | **No — needs a config entry** |
| Brunnhilde (Valkyrie) | "Set the Death Glow upgrade aside, out of play" | **No — needs a config entry** |

This turns an unbounded hand-maintained list into a check that fails loudly when a new
release introduces a case nobody has encoded yet.

**The audit flags for human review; it must not auto-resolve.** Brunnhilde's text says
"Death Glow" while the card is named "Death-Glow" — a hyphen apart. Any resolution by
exact name match would silently miss it, which is the failure mode the audit exists to
prevent.

#### Ordering: exclude before matching

Sp//dr forces a constraint on validation order. Her set contains `SP//dr Suit` as a hero
face *and* a second `SP//dr Suit` as a `permanent` support that is in play at the same
time. Those two share a title, so the unique-match rule of §8 would reject the deck —
except that the permanent card was never in the deck to begin with.

**`deck check` must therefore classify and remove out-of-deck cards first, then apply
unique-match to what remains.** Reversing the order makes Sp//dr fail her own legality
check.

These exclusions apply to `deck stats` as well as `deck check`: a permanent upgrade left
in the cost curve skews the curve of a deck it was never part of.

### Card text is a rules source the fields do not capture

Rogue's *Touched* is one instance of a general property: **a card's text box carries rules
interactions that no structured field encodes** — keywords, embedded costs, and
trait-conditional abilities. The index treats text as data to be parsed, not just matched.

Two mechanisms are worth extracting at build time:

- **Trait and keyword markup.** Card text uses `[[...]]` markup — 210 distinct tokens,
  led by `[[Aerial]]` (49 cards), `[[X-MEN]]` (42), `[[S.H.I.E.L.D.]]` (40). This is
  directly parseable into a card-to-trait table, which is what makes "which cards care
  about AERIAL" answerable.
- **Keywords with Rules Reference entries.** Keyword words appear at scale — surge on 267
  cards, toughness 134, retaliate 128, piercing 100, overkill 94 — and nearly all have a
  matching RR entry (verified for overkill, retaliate, piercing, stalwart, surge, guard,
  tough, ranged, steady, permanent; patrol and quickstrike need fuzzy matching because
  their entries are titled differently).

#### The cost arrow

Card text separates a cost from an effect with an arrow, and the Rules Reference defines
it under COST:

> A cost arrow icon (→) in ability text distinguishes a cost from an effect, in a "pay
> cost → resolve effect" format.

**The encoding is clean.** It is a single literal U+2192 character — 607 occurrences
across 594 player cards, with no ASCII `->` variant and no markup wrapper anywhere in the
corpus. 13 cards carry more than one arrow. Extraction is a string split.

**The semantics are not.** The RR adds a qualifier that a naive split gets wrong:

> Text indicating the timing of an interrupt or response trigger that precedes a cost
> arrow is not considered part of the cost.

Measured against the corpus, that qualifier applies to **196 of 607 arrows — roughly a
third**. For example:

> **Interrupt**: When a character would take any amount of damage from an attack, exhaust
> an [[AERIAL]] character you control → prevent up to 3 of that damage

Everything before the arrow splits into a timing clause ("When a character would take any
amount of damage from an attack") that is *not* a cost, and the actual cost ("exhaust an
[[AERIAL]] character you control"). Splitting on the arrow alone reports the timing as
something the player must pay.

So each arrow clause parses into four parts:

| Part | Source | Count |
|---|---|---|
| Ability type | `<b>…</b>` prefix — Hero Action (142), Action (76), Alter-Ego Action (63), Hero Interrupt (61), Interrupt (51), Hero Response (51), Response (50), Resource (31); 53 arrows have no prefix | — |
| Timing | `When`/`After` clause before the arrow | 196 |
| Cost | remainder before the arrow | 607 |
| Effect | everything after the arrow | 607 |

**Six clauses are genuinely ambiguous** and are flagged rather than guessed: they open with
`If …` (for example "If you are in [[Tiny]] hero form, exhaust Army of Ants → deal 1
damage"). The RR exempts *timing* text for interrupts and responses; it says nothing about
a conditional on an Action, so whether the condition is part of the cost is undecided by
the rules text. The parser marks these `ambiguous` and the CLI says so rather than
asserting a split the rules do not support.

**The governing principle: the parse enriches, it never replaces.** The original text is
stored verbatim and is always what gets quoted back. The parsed split powers structured
questions the raw text cannot answer — "which of my cards cost an exhaust", "what can I
trigger without spending resources", "what are my Alter-Ego Actions" — and `card show
--explain` displays the cost/effect division alongside the original wording. If the parse
is wrong on a card, the player still sees the true text and the failure is visible rather
than silent.

The index therefore builds a **card-to-rules link table** joining keyword occurrences in
card text to RR entries. It makes `card show --explain` expand a card's keywords inline
with their rules text and page cites, and lets `rules show <keyword>` list the cards that
use it. Both directions come from the same table, and it is deterministic — so under §2
it belongs in the CLI rather than being left to the model to recall.

### Legality configuration

`deck_requirements` is null throughout the card data, so deckbuilding rules are
hand-encoded in `config/legality.yaml` from the rules PDFs: deck size minimum, aspect
purity and the dual-aspect exception, per-card `deck_limit` enforcement (with the null
fallback above), the unique-match rule from §8, signature-set auto-inclusion, the
out-of-deck exclusions above, the Deadpool `pool` allowance, and basic-card allowances.

**This file is the highest-risk component** — errors in it are invisible and propagate
into every downstream feature.

**Mitigation: published marvelcdb decklists are a regression corpus.** Fetch several
hundred via `by_date` and run the validator over them. Published decks are overwhelmingly
legal, so a meaningful rejection rate means the encoded rules are wrong. This turns an
untestable config file into a tested one. (Note: the `problem` field marvelcdb computes
server-side is not exposed on the public `/decklist/` endpoint, so the corpus provides a
statistical signal rather than per-deck ground truth.)

**The corpus must be filtered by `format`.** Decks tagged `format: "legacy"` were built
under a different rule set. Left in, they inflate the rejection rate with format
mismatches that would be misread as bugs in `legality.yaml` — contaminating the exact
signal the corpus exists to provide. Exclude non-current-format decks, or branch the
validator on `format` and score the two populations separately.

### 10.1 Working-pass corrections, 2026-08-27

Measured against the built index before the deck pipeline was planned.
**Where this subsection and §10 above disagree, this one is right — it has
numbers.**

**Reprints are a player-side reality, and §10's collection filter is too
simple.** 351 cards corpus-wide carry `duplicate_of`, and `is_reprint`
agrees with it exactly — no card is one without the other. **337 of them
are player cards**: `Dum Dum Dugan` is in both Sinister Motives and Agents
of S.H.I.E.L.D., `Nick Fury` in the Core Set and Black Widow, and so on.

Two consequences:

1. `deck fetch` must canonicalise every slot through `canonical_code`. A
   marvelcdb deck may name whichever printing its builder owned.
2. §10 says the collection filter is `WHERE pack_code IN (owned)`. That
   is **wrong for any reprinted card**: owning Agents of S.H.I.E.L.D. lets
   you play Dum Dum Dugan whether or not you own Sinister Motives. The
   filter is over the canonical group — own *any* printing, have the card:

   ```sql
   WHERE canonical_code IN (
       SELECT canonical_code FROM cards WHERE pack_code IN (owned))
   ```

   §10's underlying point survives intact: ownership is still binary, and
   there is still no copy arithmetic anywhere. It is the grouping that was
   wrong, not the principle.

**`01043a`–`01043d` are not one multi-part card.** §10 cites them as
multi-part slots where "deck-size math counts the deck-legal face only."
They are four *resource variants* of Wakanda Forever! — energy, mental,
physical, and wild — each its own row, each separately deck-legal, with
`deck_limit` 1, 1, 1 and 2. **Five copies, not one.** Collapsing them
would undercount a legal Black Panther deck by four cards.

**The discriminator is `back_link`, and it separates the corpus cleanly.**
Of the 24 player-card code stems with `a`/`b`/`c`/`d` siblings:

| Kind | Count | Test | Example |
|---|---|---|---|
| Double-sided faces | 19 | `back_link` is set | Psi-Knife, Odin, the four Basic upgrades |
| Resource variants | 5 | distinct resource icons, no `back_link` | Wakanda Forever!, Firecracker |

No group is ambiguous, so the rule needs no config residue. It is also
the same rule `assess.back_faces()` already applies to encounter cards, so
`deck check` and `deck stats` reuse it rather than growing a parallel one.

**Slots naming a card the index does not carry must be reported, not
dropped.** Coverage is bounded by marvelcdb, exactly as it is for
scenarios (see the Bullseye case in `2026-08-25-card-data-sources.md`).
A slot that resolves to nothing must say so the way `assess.resolve` does;
silently skipping it yields a 37-card deck that fails a deck-size check
for a reason the player cannot see.

**`--owned` is currently on all 14 leaf commands** — `cli._leaf` adds it
unconditionally and dispatch rejects it globally. Un-stubbing it is
therefore a per-command decision, not one switch: it is meaningless on
`doctor`, `status`, `update`, `install-skill`, `timing`, and
`rules search`. That list is part of the collection task's scope.

### 10.2 Campaign-earned cards

Raised 2026-08-27: campaign rewards go into a deck but are not available
in ordinary deckbuilding, and the copy rules looked as though they might
differ. Measured, most of that worry dissolves and one real limit remains.

**There is a structured marker.** `faction_code = 'campaign'` covers
**146 cards across 15 sets** — the Market, the Galaxy's Most Wanted ship
pool, the Mutant Genesis and Age of Apocalypse campaign sets, the
S.H.I.E.L.D. tech upgrades. No hand-maintained list is needed, which is
the opposite of the Rogue's-Touched case in §10.

Of those 146:

| | Count | Already handled by |
|---|---|---|
| Encounter-side (side schemes, minions, obligations, treacheries) | 51 | the type rule |
| Permanent or `hero_special` | 27 | `out_of_deck` |
| **Genuinely enter a player deck** | **68** | nothing yet |

**The copy rules are NOT different, which was the fear.** `deck_limit`
carries the right value on every one — Shawarma 3, Pouches and Desperate
Measures 4, Norn Stone 4, the other 65 at 1 — and **zero campaign cards
violate `deck_limit <= quantity`**, the invariant the whole no-copy-
arithmetic model rests on (§10). `check_copies` therefore needs no
special case.

**What is not determinable is whether the player has EARNED them.** That
lives in the campaign book, not the card data, and marvelcdb does not
record it either — a decklist carries slots, not campaign progress. So
`deck check` **reports** campaign cards and does not judge them:

- Passing silently would imply the tool verified something it cannot see.
- Failing would reject a perfectly legal campaign deck.
- A `--campaign` flag would make the player declare a mode to get a
  verdict the tool still could not actually check.

`--owned` does **not** hide them: they ship in a box the player owns, so
pack ownership answers "do I physically have this card" correctly.
Earned-ness is a separate axis and this project does not model it.

**Frequency, measured:** **0 of 156** published decks sampled across six
`by_date` days contain a single campaign card. So this does not
contaminate the regression corpus's rejection rate, and it is rare in
practice.

### 10.3 What the regression corpus found

1,534 published decks fetched over 40 days; 1,501 checked after excluding
`format: legacy`. **The first run rejected 14.1%.** Every point of the
drop to 4.5% was a real defect, and each is recorded here because §10
calls `legality.yaml` the highest-risk component in the project and a
rejection nobody read is worse than no corpus at all.

**Four bugs the corpus caught:**

| Bug | Rejections |
|---|---|
| `_limit` read `override.get("set_code")`, a key the config never had, so Adam Warlock's "max 1 copy of any non-Warlock card" applied to his own signature cards — `Cosmic Ward` is printed at limit 2 | 18 → 2 |
| Off-aspect allowances were never implemented, though all seven sat in `deckbuilding_overrides` already | part of 165 → 62 |
| Warlock's card wants an equal number from **all four** aspects and marvelcdb records at most two, so his declared aspects cannot judge purity | " |
| Deck size excluded set-aside cards that carry no `permanent` keyword | 17 → 6 |
| Aspect purity was judged against a declaration marvelcdb stores **separately from the cards**, so a rebuilt deck keeps its old one | 62 → 47 |

**And two judgment calls, both recorded rather than assumed:**

- A deck with **no recorded aspect** is a note, not a failure. marvelcdb
  keeps the aspect in `meta`; some decks carry none. That is a gap in what
  was stored, not evidence of an illegal deck.
- `card_traits` records the `[[X-MEN]]` markup a card's text **references**
  — "which cards care about X-Men". The printed trait line is
  `cards.traits`. The allowances read the second. Reaching for the first
  silently matched nothing, because `Blindfold` has no `card_traits` rows
  at all.

#### The residue, read card by card

**5.5% — 82 of 1,501 — and every category was examined.**

- **`unique` (12)** — all verifiably illegal: a Captain America deck
  holding the Captain America ally, a Silk deck holding the Silk ally, two
  different `Angel` allies, `Ant-Man` beside `Yellow Jacket` (one
  character, matched on alter-ego title).
- **`deck_size` (6)** — genuinely short, 31 to 37 cards.
- **`deck_limit` (2)** — one Warlock deck breaking his own copy rule, one
  deck with two `Superpower Training` at `deck_limit` 1.
- **`aspects` (62)** — 47 decks with one or two off-aspect cards, 15 whose
  declared aspect is not even among the deck's dominant factions.

**The distribution is what settles it.** Across 1,478 decks with a
declared aspect:

| Off-aspect cards | Decks | |
|---|---|---|
| 0 | 1,424 | **96.3%** |
| 1 | 23 | 1.6% |
| 2 | 15 | 1.0% |
| 3+ | 16 | 1.1% |

A sharp mode at zero, then a thin scatter — the shape of human
deckbuilding slips. A missing allowance would show as a **spike** at one
hero or one count, and the tail is diffuse instead. marvelcdb computes a
`problem` field server-side but does not expose it publicly, so decks with
problems can be and are published.

**§10 calls `meta.aspect` "the authoritative declared aspect". It is
authoritative for what the player DECLARED, which is not the same as
correct.** On marvelcdb the declaration is a field of its own, set apart
from the deck contents, so a player can rebuild into another aspect — or
never set it — and the declaration stays behind. 15 decks declare an
aspect that is not even their dominant faction; one Cable deck declares
protection while holding 12 leadership cards and 2 protection.

Judging purity against a stale declaration rejects a legal deck **and
names the wrong cards as the problem**, which is worse than saying
nothing. So a deck whose own cards overwhelmingly contradict its
declaration gets a note and no purity verdict.

The threshold sits in a measured empty band. Of 1,478 decks with a
declaration, **1,325 match it completely and 15 match 10% or less**;
between them lie one deck at 30% and two at 40%. The 50–90% band is
mostly legal off-aspect allowances — Cyclops's X-MEN allies — and must
**not** be swept up, which is why the cut is at 20% rather than
somewhere convenient.

**The gate is set at 6%**, above the measured 4.5% with room for corpus
drift as new decks arrive, and tight enough that a regression rejecting a
single hero's decks (~1.3%) still fires it. A second gate asserts at
least 20 rejections, because a rate near zero means the rules stopped
firing and reads identical to everything being fine.

## 11. Init and update

### `mc-jarvis init`

1. **Cards** — fetch the 1.5 MB tarball from `codeload.github.com` and extract into
   `<data>/marvelsdb/` with stdlib `tarfile`. No `git` required (§6).
2. **Rules manifest** — obtain the FFG product page HTML and extract every PDF link with
   its title, size, and revision date into `<data>/rules/manifest.json`. Verified: the
   page carries 91 PDFs, including the Rules Reference (v18, 22 Jul 2026), Learn to Play,
   and every big-box rulebook and campaign log.
3. **Rules PDFs** — user selects which to fetch. Default: Rules Reference and Learn to
   Play. Downloads go over plain HTTP from `images-cdn.fantasyflightgames.com`, which is
   not bot-protected.
4. **Extract** — per §9.
5. **Build** — SQLite index per §8.
6. **Collection** — prompt for owned packs, write `<data>/collection.yaml`.
7. **Workspace** — establish the player's workspace and install the skill into it (§7).
   The index stays in the user-global data directory, so a second workspace costs nothing
   and reuses the same data.

**First run is a shell command, not an agent request**, and it has to be: the skill is
what teaches an agent that `mc-jarvis` exists, so the agent cannot be what installs it.
The README's opening line is `uv tool install mc-jarvis && mc-jarvis init`, run from the
folder the player wants as their workspace. Everything after that — including every use
of the skill — happens through whichever agent they prefer.

### Getting the product page HTML

The FFG product page returns HTTP 403 to plain HTTP clients regardless of headers; it
requires a real browser engine. Three tiers, in documented preference order:

1. **`--from-html <file>`** — the default and the agent-agnostic path. The user's agent
   fetches the page with whatever browser capability it has, or a human uses Save Page As.
   mc-jarvis does the parsing. **This works on an agent with no browser capability at
   all**, which is the strongest portability guarantee available.
2. **`--browser`** — uses Playwright if installed. Verified working (returns all 91 PDFs).
   Ships in optional extras, not core: a ~300 MB Chromium download is disproportionate for
   a tool whose payload is 11 MB of JSON.
3. Agent-native browser tooling, per instructions in `SKILL.md`.

### `mc-jarvis update`

Re-fetches the card data, re-checks the manifest, and rebuilds the index. Diffs the
manifest by revision date to flag rulebooks that FFG has revised since last fetch.

Refresh is **manual with a staleness nudge**: `SKILL.md` instructs the agent to check
index mtime and tell the user when it exceeds 14 days. No background jobs, no network I/O
the user did not ask for.

## 12. Meta comparison (Phase 3)

marvelcdb has **no per-hero decklist route** (verified: `/api/public/decklists/hero/<code>`
returns 404). The only path is crawling `/api/public/decklists/by_date/<YYYY-MM-DD>` and
filtering client-side. Observed volume: 19–34 decks per day, roughly 48 KB per day, with
data reaching back to at least 2023.

**Policy, as a named decision rather than an implementation detail:**

- **180-day window.** Roughly 4,500 decks — ample signal for "cards commonly played with
  this hero" at a tenth the footprint of a two-year crawl.
- Rate-limited with a delay between requests, against a volunteer-run community site.
- Cached to `<data>/meta/`, refreshed only on explicit `update`, never during a query.
- Aggregation (inclusion rate per card per hero) is computed in the CLI and cached, so the
  model receives a ranked table rather than raw decks.

## 13. Phases

**Phase 1 — the spine.** `init` / `update`, card and encounter search, rules lookup with
citations, deck import, legality validation, deck stats (cost curve, resource curve, type
breakdown, thwart/attack/heal density). Collection tracking and `--owned` filtering.
The skill file, `install-skill`, and `doctor`. This is a genuinely useful Jarvis on its
own.

Collection is in Phase 1 deliberately. It is cross-cutting rather than a leaf feature —
once it exists, card search, deckbuilding, and meta comparison all must respect owned
packs. Mechanically it is a pack-code allowlist and a `WHERE pack_code IN (...)`, so
building it in from the start is cheaper than retrofitting `--owned` onto every surface
later, and it removes the "did you filter?" bug class before it can appear.

**Phase 2 — judgment and reach.** Deck coaching (the model reads the deck's card text and
gives opinionated cut/add advice), multiplayer team analysis, and the `mc-jarvis mcp`
stdio server. MCP is deferred to here deliberately: it is the real cross-agent protocol,
but it is a second interface surface that drifts from the CLI, so it lands once the
command set has stopped moving.

**Phase 3 — the crawl.** Meta comparison per §12, and deckbuilding from scratch, which
depends on both a complete legality config and the meta signal.

Build-from-scratch must filter candidates against the identity's unique-match set (§8).
Sixty character names exist as both a hero and an ally, so a naive "pick strong Justice
allies" pass will cheerfully offer the player their own identity — a suggestion that is
illegal and reads as obviously wrong to any player.

## 14. Testing

The distribution principle (§4) creates a problem it must also solve: the repository ships
no data, so nothing can be tested against real cards or real rules text. Two tiers.

**Synthetic fixtures — committed, and the default for CI.** A small set of hand-invented
cards written by us, conforming to the marvelsdb schema but containing no FFG text. They
must be constructed to exercise the specific traps this design identified:

- a `duplicate_of` reprint pair, for canonical-search and alias-resolution
- a two-face identity, a three-face identity with an extra hero form, and a multi-card
  identity in the Ironheart shape — the three groupings in §8 — plus a multi-part card,
  for deck-size counting and identity resolution
- a signature set grouped by `set_code`, plus a `set_code: null` card, for the Deadpool case
- a unique-match family mirroring the Black Panther / T'Challa case in §8 — a linked
  hero/alter-ego, a same-title ally, a different-title ally matching via `subname`, and a
  second hero sharing a title but *not* matching — since this rule fails in both
  directions and string equality passes a naive test
- a card with `deck_limit: null`, to pin the fallback to `quantity`
- one card of each out-of-deck kind — a `permanent` card, a `hero_special` set member, and
  a text-only exclusion in the Rogue/Touched shape — since deck-size math must skip all
  three and only two are findable structurally
- a card whose text carries `[[Trait]]` markup and a keyword with an RR entry, for the
  card-to-rules link table
- three cost-arrow cards — a plain `cost → effect`, an interrupt whose timing clause must
  be excluded from the cost, and an `If …` clause that must come back flagged as ambiguous
  rather than split
- a Sp//dr-shaped set: an identity face and a `permanent` card sharing a title, which must
  pass `deck check` and fails if exclusion runs after unique-match
- an identity whose text implies an out-of-deck card under a near-miss name, pinning that
  the setup audit flags for review rather than silently resolving
- a spread of costs and resource icons, for curve and resource math
- decks that violate each rule in `legality.yaml`, one per rule

`install-skill` gets its own tests, because its guard rails are the kind that fail
silently: a workspace at `$HOME`, a workspace nested inside another repository, and the
directory matrix in §7 all need asserting rather than trusting.

For rules, a hand-written text fixture shaped like real `pdftotext -raw` output — ALL-CAPS
entry headers, form feeds, a private-use glyph codepoint, a `See also:` line — exercising
the chunker, page-cite extraction, and glyph mapping without shipping a PDF.

**Integration tests — gated on a real built index, skipped when absent.** These confirm
the real corpus still matches expectations: field presence, card counts within tolerance,
successful RR entry extraction. They are how upstream schema drift gets caught.

Without this split every test would need a five-minute `init` and CI could not run at all.

## 15. Risks

| Risk | Mitigation |
|---|---|
| `legality.yaml` encodes a rule wrongly, invisibly | Validate against a corpus of published decklists (§10) |
| Identity treated as one row, or grouped on `back_link` | Loses Archangel, Ant-Man's giant form, and five of Ironheart's six faces; grouping is on `set_code` and asserted by the §14 fixtures |
| An out-of-deck card counted in deck size or the cost curve | Three exclusion mechanisms in §10, two structured and one hand-encoded; fixtures in §14 cover all three |
| A new hero release adds an unmarked out-of-deck card nobody encodes | The setup audit (§10) scans identity text at index build and fails loudly on an uncovered case, instead of relying on a hand-maintained list |
| Unique-match applied before out-of-deck exclusion | Rejects Sp//dr's own legal deck; ordering is fixed in §10 and pinned by a fixture |
| Cost arrow split naively, reporting timing text as a cost | Affects ~196 of 607 arrows (§10); the parser strips timing per the RR and flags the 6 undecidable `If …` clauses; original text is always shown |
| Unique-match implemented as name equality | Fails in both directions (§8); the fixture family in §14 pins both the false negative and the false positive |
| Upstream breaks the `deck_limit <= quantity` invariant | Index build asserts it and fails loudly rather than under-counting (§10) |
| FFG changes the product page markup, breaking manifest extraction | Parsing is one function over `a[href$=".pdf"]`; failure is loud, and `--from-html` keeps a manual path open |
| marvelcdb rate-limits or blocks the meta crawl | 180-day window, request delay, disk cache, explicit-refresh-only |
| Card data schema changes upstream | Index build validates expected fields and fails loudly rather than silently dropping cards |
| Unmapped icon codepoints degrade rules text | Preserved verbatim and logged, never silently stripped |
| A harness diverges from the standard, breaking the portable file | Frontmatter stays within the published spec and avoids the experimental `allowed-tools` (§7); `install-skill` reports where it placed the skill so a miss is visible |
| A `--link` install breaks when the checkout moves or `git pull` lands | Copy is the default; `--link` is opt-in and documented as developer-only (§7) |
| Player asks a question outside the workspace and nothing responds | Accepted trade for not polluting every session (§7); `status` and the README name the workspace, and `--global` is available |
| A user's Python lacks FTS5, or is below 3.10 | `doctor` checks at runtime and `init` refuses to start, naming the missing piece and the platform install command (§6) |
| pypdf changes its text-extraction behaviour across versions | Extraction is behind a common interface with a `pdftotext` backend; rules fixtures (§14) catch drift |

## 16. Verified findings

Everything below was confirmed on 2026-08-20 — by direct inspection for the data and
tooling claims, and from vendor documentation for the skill-discovery paths. None of it
is assumed.

- Card corpus: 11 MB, 4,298 cards, 1,607 player-legal, 116 pack files, 61 packs, 72 heroes.
- 342 cards carry `duplicate_of`; `deck_requirements` is null on every hero.
- Signature sets group on `set_code`.
- `pdftotext -raw` reads the two-column Rules Reference correctly; `-layout` does not.
- Form feeds preserved (71 pages); 356 ALL-CAPS entry-header candidates; amplify icon is
  U+F521.
- marvelcdb `/api/public/decklist/<id>` returns hero code and slots; `meta` appears both as
  a JSON string and as an object; `aspect2` and `format` keys exist.
- `pool` is 34 Deadpool cards from the `deadpool` pack, all with `set_code: null`.
- `deck_limit` never exceeds `quantity` in a card's own pack — 0 violations across 1,607
  player cards — so collection ownership is binary and needs no copy arithmetic.
- `duplicate_of` is set on 342 cards, **all of them encounter cards**; no player card uses
  it. True player-side reprints number 14, detectable only by name+type+faction.
- 79 player card names appear in more than one pack; 60 character names exist as both a
  hero/alter-ego and an ally, so name is not an identity key.
- RR: identity is a player card type; hero and alter-ego are its two forms. Identities do
  not group cleanly on `back_link` — Angel, Ant-Man and Wasp each have a third face with
  `back_link: null`, and Ironheart has three complete identity cards (`29001`–`29003`).
  `set_code` is the correct grouping key.
- Hero/alter-ego linkage in the local data is `back_link` (`01040a` → `01040b`); the
  marvelcdb API calls it `linked_to_code`. `back_name` is null throughout the local data.
- Three separate out-of-deck mechanisms: `permanent: true` (102 corpus-wide, 25 player
  cards over 13 sets — covers Wolverine's and X-23's Claws, Psi-Knife/Psi-Katana,
  Vision's Intangible, Spectrum's forms, both Sp//dr in-play cards);
  `card_set_type_code: hero_special` (6 sets — Doctor Strange Invocation, Storm Weather,
  Iceman Frostbite, Hercules Labor and Gift, Daredevil Sense); and unmarked cards —
  Rogue's *Touched* and Valkyrie's *Death-Glow* — identifiable only from identity prose.
- Scanning identity text for setup/set-aside language returns exactly four identities
  (Bobby Drake, Riri Williams, Rogue, Brunnhilde), two of which no structured flag covers.
  A derivable audit, not a hand-maintained list.
- Brunnhilde's text references "Death Glow"; the card is named "Death-Glow", so prose-to-
  card resolution cannot be exact-match.
- Exactly one player card has `double_sided: true`: Vision's Intangible, `back_name`
  "Dense". Iceman's `deck_limit: 6` Frostbite is the quantity-6 outlier and matches his
  identity text ("6 Frostbite upgrades set aside").
- Sp//dr has `SP//dr Suit` as both a hero face and a separate `permanent` support, so
  out-of-deck classification must run before the unique-match check.
- The cost arrow is a single literal U+2192 — 607 occurrences over 594 player cards, no
  ASCII `->` variant anywhere, 13 cards with more than one. RR defines it under COST and
  excludes interrupt/response timing text from the cost, which applies to 196 of the 607.
  Six `If …` clauses are undecided by the rules text.
- Card text carries 210 distinct `[[...]]` trait/keyword markup tokens; keyword usage is
  heavy (surge 267 cards, toughness 134, retaliate 128, piercing 100, overkill 94) and
  nearly every keyword has a matching RR entry.
- 120 player cards have `deck_limit: null`; 235 cards carry a `subname`; all 653 unique
  player cards have `deck_limit` of 1 or null.
- RR p.45 makes unique-card matching a deckbuilding constraint over title, subtitle, and
  alter-ego title. The Black Panther / T'Challa family in the data is the RR's own worked
  example.
- Agent Skills is an open standard at agentskills.io (originally Anthropic), supported by
  40+ products. It standardises the **format only** — the specification defines no
  install path, leaving discovery to each runtime.
- Claude Code supports project-level skills at `.claude/skills/<name>/SKILL.md` scoped to
  "this project only", loaded from the start directory and every parent up to the
  repository root. It follows symlinked skill directories and loads a target reachable
  from multiple locations exactly once.
- Global skill paths, from vendor docs: pi reads `~/.pi/agent/skills/` and
  `~/.agents/skills/`; opencode reads `~/.config/opencode/skills/`, `~/.agents/skills/`,
  and `~/.claude/skills/`; Claude Code reads `~/.claude/skills/`; Codex reads
  `~/.codex/skills/`. `~/.agents/skills/` is the vendor-neutral convention.
- Spec frontmatter: `name` and `description` required; `license`, `compatibility`, and
  `metadata` optional; `allowed-tools` optional but marked experimental with support
  varying between implementations.
- AGENTS.md is directory-scoped: agents read the nearest file walking up from cwd.
- Stock CPython 3.14.6 has FTS5 (SQLite 3.51.2).
- `pypdf` reads the two-column Rules Reference in correct order and preserves all 13
  private-use icon codepoints (U+F520–F530); it drops only the `»` sub-bullet marker.
  `pdfplumber` interleaves the columns and is unusable.
- The card data tarball from `codeload.github.com` is 1.5 MB and contains all pack JSON,
  so `git` is not a requirement.
- `/api/public/decklists/hero/<code>` returns 404; `by_date` works and reaches back to at
  least 2023.
- FFG product page returns 403 to `curl` with browser headers; returns all 91 PDF links
  under both Claude-in-Chrome and Playwright.
