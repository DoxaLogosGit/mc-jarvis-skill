# mc-jarvis — state of play, 2026-08-23

**Phase 1 is complete.** All 17 tasks are committed and green.

    309 tests passing
    4,379 cards · 69 identities · 287 rules entries (216 resolve) · 1,180
    card-rules links · 4,588 timing triggers
    Rules Reference v1.8 · unmapped_glyphs: empty · unclassified prefixes: none

One Done criterion is deliberately unticked, because no test can settle
it: **whether an agent finds and uses the skill without being told to.**
That measures the skill's `description`, and only a real session answers
it. Everything mechanical around it is verified.

## Try it

    uv tool install mc-jarvis
    mkdir ~/marvel-champions && cd ~/marvel-champions
    mc-jarvis init                # card data + rulebooks + index
    mc-jarvis install-skill       # .agents, .claude, .codex

Then open any agent in that folder and ask a Marvel Champions question
without naming a command. That is the last criterion.

    mc-jarvis card search <query> [--aspect --type --cost --trait --text]
    mc-jarvis card show <name-or-code> [--explain]
    mc-jarvis identity <name>           # alias: hero
    mc-jarvis encounter <villain-or-set>
    mc-jarvis rules show <term>
    mc-jarvis rules search <text>
    mc-jarvis timing [<trigger>] [--round]
    mc-jarvis status | doctor | update

All take `--json`.

## What Phase 1 delivers

Card lookup, identity grouping with RR-correct unique matching, encounter
sets, out-of-deck classification, cost-arrow and keyword parsing,
deckbuilding overrides for the seven heroes that have them, full rules
lookup and search with citations, the card-rules link table, the timing
reference, and a skill that installs per-workspace for four harnesses.

Nothing copyrighted is in the repository. `init` fetches card data and
rulebooks to the user's machine.

## What is left

| | |
|---|---|
| Task 18 designer rulings | design only, deliberately unscheduled |
| `assess` (scenario threat profile) | spec written, Part 1 plannable |
| deck pipeline | not specified — `deck` commands do not exist yet |

`--owned` parses on every command and is rejected at dispatch: the
collection lands with the deck pipeline.

## The three bugs this project's own gates caught

Kept because each one is a class, not an incident.

**A confident, cited, wrong ruling.** The development data directory had
been assembled by hand: one rulebook instead of two, and Rules Reference
**v1.8**, while `init` gave every real user **v1.7** from a stale
archive.org capture. The editions disagree on the rules — v1.7 puts "When
Defeated" beside Boost, v1.8 makes it a Forced Interrupt two tiers
earlier — so `timing "When Defeated"` answered from v1.8 **and cited the
user's own rulebook for it**.

`verify_chart` and `verify_citations` caught the mismatch, and `init` and
`status` reported it; `timing` served the answer anyway. Fixed twice over:
`timing` now refuses when its chart does not match the indexed rulebook,
and `init`/`update` take the current edition rather than the archived one.
`check_rr_currency` already existed and **nothing called it** — that was
the whole bug.

**Stored but unfindable.** Learn to Play's 24 pages went into
`rules_entries` and none into the FTS index, because the fill filtered on
`entry_addressable` and page-chunked content is non-addressable by design.
18 of those pages contain "villain" and `rules search` returned none of
them. Addressable-by-name and searchable are two properties; they are two
columns now.

**A filter nobody measured.** `len(prefix) > 40` dropped bold spans
without classifying or counting them. 113 rows sat above the line: 112
prose bolded for emphasis, and one real `Forced Response` on a card whose
markup opens a second `<b>` where it should close the first. The cutoff is
now config, with the gap it sits in measured at both ends.

The common shape: **a filter or a fixture that excludes silently, verified
against data that was not what users get.** The gates work. What nearly
beat them was the reference index being accidental.

## Standing decisions

- **The latest Rules Reference is the authority.** A new release replaces
  the old one. Rulings issued *after* the current RR are the only thing
  that outlives an edition — that is Task 18.
- **The repository ships code and configuration only.** No card text, no
  rules text, no PDFs, no built index.
- **Agent-agnostic.** Four harnesses, one skill, workspace-scoped so it
  never loads globally.
- **Glyph mapping runs after chunking, not before.** Measured: 13 of 217
  entries otherwise stored under a truncated name, with nothing raised.
- **Both PDF backends agree** on the real Rules Reference, so neither is
  pinned.
