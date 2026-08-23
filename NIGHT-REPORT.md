# mc-jarvis — state of play, 2026-08-23

**Phase 1 is complete, and Task 18 has landed on top of it.**

    345 tests passing
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
| `assess` (scenario threat profile) | spec written, Part 1 plannable |
| deck pipeline | not specified — `deck` commands do not exist yet |

`--owned` parses on every command and is rejected at dispatch: the
collection lands with the deck pipeline.

## Task 18: designer rulings

FFG designers answer rules questions between rulebook releases, and some
of those answers say the rulebook is wrong. A citation to superseded text
is still a wrong answer. What keeps it small: **a new Rules Reference
supersedes every ruling published before it**, so the live set is bounded
by one release cycle and is relative to the edition indexed.

    mc-jarvis rulings              # in force under the rulebook you hold
    mc-jarvis rulings <text>       # search them
    mc-jarvis rulings --all        # including superseded, each labelled

`rules show <term>` adds any ruling in force under the rulebook entry,
never in place of it. Superseded rulings are kept and flagged, so "what
happened to that ruling about overkill?" stays answerable.

**Today it reports 31 rulings, 0 in force.** That is the correct steady
state a month after a rulebook release, not a broken feature. Verified by
re-classifying the real corpus against each edition: v1.7 → 31 active,
v1.8 → 0 active, no determinable date → 31 active (fail-safe).

Three things the real data settled against the design:

- **The Rules Reference states no publication date**, and the whole rule
  keys on it. It comes from the PDF's `/ModDate`, cross-checked against
  the manifest — and the manifest is only usable when it describes the
  *same edition*, since `take_current_rr` leaves the archived date behind.
  When sources disagree the earliest wins, because earlier retains more.
- **Linking is quoted terms only.** Every term a ruling merely mentions
  gives 13.8 links each and attaches 17 of 31 to `Ability`. Card-name
  linking was measured and abandoned: one ruling matched 85 cards.
- **The change-log confirmation mechanism does not work.** Free-text
  matching "confirmed" 12 of 31 because `resolve` is both a change-log
  term and ordinary rules vocabulary; page-number matching claimed 2, both
  coincidental page-sharing. Strict quoting confirms 0. Page 1 summarises
  *notable* changes, not every incorporation — so supersession really is a
  presumption, and every row says `presumed`.

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
