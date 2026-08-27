# mc-jarvis

An agent-agnostic assistant for **Marvel Champions: The Card Game**. It
answers card questions, looks up rules with citations, and settles trigger
timing arguments — from a local index, never from a model's memory.

Works with Claude Code, Codex, opencode and pi. One skill file, installed
per workspace.

> **This repository ships code and configuration only.** No card text, no
> rules text, no PDFs, no built index. Everything copyrighted is fetched to
> your machine when you run `mc-jarvis init`, from FFG and from community
> databases. Nothing that belongs to Fantasy Flight Games or Marvel is
> redistributed here.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install mc-jarvis

mkdir ~/marvel-champions && cd ~/marvel-champions
mc-jarvis init            # fetches card data + rulebooks, builds the index
mc-jarvis install-skill   # places the skill for every harness
```

Then open an agent in that folder and ask a Marvel Champions question
without naming a command. If the skill is working, it runs one.

`mc-jarvis doctor` diagnoses a broken environment. `mc-jarvis status`
reports what is indexed, which Rules Reference version, and how stale it is.

## What it does

| Ask | Command |
|---|---|
| find cards | `mc-jarvis card search <query> [--aspect --type --cost --trait --text]` |
| one card in full | `mc-jarvis card show <name-or-code> [--explain]` |
| a hero's kit | `mc-jarvis identity <name>` |
| an encounter set | `mc-jarvis encounter <villain-or-set>` |
| a rules term | `mc-jarvis rules show <term>` |
| a rules question | `mc-jarvis rules search <text>` |
| trigger ordering | `mc-jarvis timing [<trigger>]` |
| the game round | `mc-jarvis timing --round` |
| rulings the rulebook lacks | `mc-jarvis rulings [<text>]` |

Every command takes `--json`.

## Why it exists

A model asked about this game will answer confidently and often wrongly.
The card pool grows with every release, the Rules Reference is revised
roughly twice a year, and trigger ordering has *changed between versions* —
so anything a model remembers is a coin flip on which edition it came from.

So the design rule is: **every factual claim comes from a command, and
every rules answer carries the entry name and page it came from.** An
uncited ruling is worthless in an argument at the table.

The corollary matters more. When the tool cannot answer correctly, it
**refuses** rather than guessing:

- `timing` will not answer if its priority chart does not match the
  rulebook in your index. Trigger order changed between Rules Reference
  1.7 and 1.8 — in 1.7 "When Defeated" sits beside Boost, in 1.8 it is a
  Forced Interrupt two tiers earlier. Answering from the wrong one would
  cite *your* rulebook for a rule it does not contain.
- `rules search` never returns a hit it cannot cite to a page.
- Designer rulings are kept only while the Rules Reference does **not**
  yet cover them; a new rulebook absorbs them and they are dropped.

## How it stays current

`init` fetches card data from
[marvelsdb-json-data](https://github.com/zzorba/marvelsdb-json-data) and
the rulebooks from FFG's own CDN, discovered through an archive.org capture
so no browser is needed. That capture lags, so the Rules Reference version
is cross-checked against a community mirror and the **current** edition is
taken — verified by the document declaring its own version before it is
swapped in.

`mc-jarvis update` refreshes everything, including designer rulings issued
since the rulebook.

### What is derived, and what ships

This repository ships **code and configuration only** — no card text, no
rules text, no rulebooks, no built index. Anything that would otherwise be
someone else's words is *derived at `init`/`update`* from the copy on your
own machine, and the repo carries only a pointer and a fingerprint.

| Thing | Where it comes from | What ships here |
|---|---|---|
| The Rules Reference | fetched from FFG at `init` | nothing |
| Card text | marvelsdb, fetched at `init` | nothing |
| Timing chart | parsed from the RR's `Ability` entry | its shape and a digest |
| Timing tie-breaks | the RR entry each one names | a note and search terms |
| The keyword list | the RR's `Keywords` entry plus its per-keyword entries | the expected list, as a gate |
| Set-aside and scenario data | parsed from card text | reasons and digests |

Two rules follow from that table, for anyone adding to `config/`:

1. **Never paste a sentence you did not write.** If the answer needs FFG's
   wording, store the `rr_entry` it lives in and read the wording from
   `rules_entries` at print time. `config/timing.yaml`'s `tie_breaks` is
   the worked example.
2. **Every derived thing needs a gate.** Deriving means the value can
   change under you, so pin the expectation and report the drift. The
   keyword list is the case that proves it: the hard-coded list it
   replaced had missed `vulnerable` since Agents of S.H.I.E.L.D. and still
   carried `uppercut`, which is in no rulebook and on no card.

### What enforces it

Not this README. `mc_jarvis.policy` compares every tracked file against
the Rules Reference and card text **as they sit in your built index** — if
a phrase in the repository appears verbatim in the corpus, the repository
is shipping that text. No length heuristic can make that call; a
40-character quotation is still a quotation, and a long explanation in
your own words is not.

```bash
uv run python -m mc_jarvis.policy            # exits non-zero on a hit
ln -sf ../../tools/pre-commit .git/hooks/pre-commit   # block it at commit
```

`tests/test_policy.py` runs the same check as part of the integration
suite, asserts that the word-window sits at the bottom of its measured
band, and — because a gate nobody has seen fail is a gate nobody knows
works — asserts that a planted quotation is caught.

The one exemption is the LICENCE's own: software may name part of a
document in order to parse it. Mark such a line `# policy: locator` with
a reason. There is one today, the phrase that finds the timing chart, and
a test keeps the count from growing quietly.

**Two places are knowingly relaxed, and neither is packaged.** Test
fixtures carry real card text, because a parser test with invented input
tests nothing; the design documents under `docs/` quote `Contents` blocks
as the evidence for a measurement, and go away as features settle. Both
are excluded from the built wheel *and* the source distribution — note
that `uv build` builds the wheel **from the sdist**, so an unscoped sdist
is the real deliverable. `tests/test_packaging.py` builds both artifacts
and checks them, in both directions: nothing unshipped leaks in, and
nothing the wheel needs gets trimmed out.

## Development

```bash
uv sync
uv run pytest -q -m "not integration"   # unit tests, no network or index
uv run pytest -q                        # adds real-data gates
```

The test suite is in two tiers because the repository ships no data. Unit
tests run on fixtures shaped from observed data; integration tests run
against a real index and assert numbers measured from it. A gate that
cannot fail is not a gate — thresholds here are measured, and the
measurement is recorded beside them.

Design docs and implementation plans live in `docs/superpowers/`. They
carry the reasoning, including the parts that turned out wrong: several
sections record a conclusion, the data that contradicted it, and the
correction. That history is deliberate — the same mistake was made more
than once, and the notes are what stopped it happening a third time.

## Status

Card lookup, identity grouping, encounter sets, rules lookup and search,
the timing reference, designer rulings, and the skill installer all work.

Deck import, legality validation, deck statistics and collection tracking
are specified but not built. `--owned` parses everywhere and is rejected at
dispatch until the collection lands.

## Licence

MIT — see `LICENSE`. **It covers the software in this repository and
nothing else.**

Marvel Champions: The Card Game, its cards, rules text, artwork and
trademarks belong to Fantasy Flight Games, Asmodee and Marvel. This project
is unaffiliated with and unendorsed by any of them, and distributes none of
their material. What `init` fetches to your machine is governed by its own
publishers' terms, not by this licence.
