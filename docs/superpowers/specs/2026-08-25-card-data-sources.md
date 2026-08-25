# Card Data Sources — Decision Note

> **Status: decided, not scheduled.** Written 2026-08-25 after tracing why
> DragnCards can play a scenario mc-jarvis cannot see. No implementation is
> planned yet; this records the measurements and the decision so neither has
> to be rediscovered.
>
> **Parent spec:** `docs/superpowers/specs/2026-08-20-mc-jarvis-design.md`

## The decision

**marvelcdb stays the primary source. Cerebro is a backup and a
cross-check, never the card of record.**

Reached 2026-08-25. The deciding factor is quantity: Cerebro does not
publish copy counts, every mean `assess` reports is quantity-weighted
(assess spec §4.5), and no schema convergence can supply a field the
source does not have.

## What started it

A player reported having played Bullseye as a villain. mc-jarvis had no
such card, and three successive searches said so — each one too narrow,
which is a failure mode this project has now recorded four times.

The card is real. `Fear No Evil` is a **story box** whose own metadata
declares 276 cards; marvelcdb carries **68**, and none of them is a villain
or a main scheme. The entire encounter half is unentered upstream.

| Pack | Type | Declared `size` | Present | Villain sets |
|---|---|---|---|---|
| Age of Apocalypse | story | 271 | 220 | 5 |
| **Fear No Evil** | **story** | **276** | **68** | **0** |
| Jessica Jones | hero | 60 | 43 | 0 |

What *is* entered is exactly the player-facing half: both heroes, their
aspect cards, signature sets, the Sense deck, and both nemesis sets. That
is consistent with how the data gets built — deckbuilders need hero cards
first, and the encounter sets follow later.

## The three sources, measured 2026-08-25

| | marvelcdb repo (ours) | marvelcdb live API | Cerebro |
|---|---|---|---|
| Cards | 4,379 | — | **4,632** |
| Fear No Evil encounter sets | ✗ | ✗ | ✓ |
| **Quantity** | ✓ | ✓ | **✗ — no such field** |
| HTML markup in card text | ✓ | ✓ | ✗ (0 of 4,603) |
| Structured scenario→modular map | ✗ | ✗ | ✓ |

The **live marvelcdb API is not ahead of the GitHub repo** — it returns 66
cards for `fne` with Bullseye still a minion. So switching to the API buys
nothing; the gap is in the data, not in our fetch.

Cerebro has Fear No Evil's real contents: Kingpin, Hammerhead, Purple Man,
Typhoid Mary and Bullseye, five scenarios (Art Museum Heist, The Getaway,
Protection Racket, The Raft Breakout, Stop the Presses!) and six modulars
(Disasters, Cops, Drive, The Owl, Tombstone, Tracksuit Mafia).

## Why Cerebro cannot be primary

**Quantity is absent, and it is not an encoding difference.** `Stampede ×3
boost 1` and `Charge ×2 boost 2` give a quantity-weighted mean of 1.4, not
the row mean of 1.5. The assess spec refuses to offer the unweighted form
because there is no question it answers. A source without copy counts
cannot produce the headline number.

The gap falls in the worst possible place: cards present *only* in Cerebro
are exactly the new releases, which is precisely the content a player wants
assessed.

**What is NOT an obstacle**, contrary to first impressions:

- **Missing markup is an encoding difference, not missing information.**
  Zero of 4,603 Cerebro cards carry HTML, so `BOLD_RE` finds nothing — but
  the triggers are still there in plain text. Measured: a closed-vocabulary
  regex anchored at line start recovers a trigger prefix on **3,004 cards**,
  with the same distribution shape as ours (When Revealed highest, then
  Hero Action, Forced Response). The timing feature would need a second
  reader, not a redesign.
- **Glyphs** are a mapping table — `{s}`/`{i}`/`{b}` against `[star]` and
  `[[trait]]`. We already map the rulebook's private-use codepoints.
- **Identity** is solvable: `Printings[].ArtificialId` carries a
  marvelcdb-style code on **5,036 printings**, so the two databases can be
  joined card-by-card rather than matched on name.

## What Cerebro is worth using for

Three things, none of which require importing a single card:

1. **Coverage detection.** Join on `ArtificialId` and we can say *"Bullseye
   is a villain in Fear No Evil; marvelcdb has 68 of a declared 276 cards
   and has not published its encounter sets"* instead of "villain not
   found". Those are completely different problems for a player, and the
   current message conflates them.
2. **A structured scenario→modular mapping.** `/sets` carries `Requires`,
   `Recommends` and `Modulars` as fields. The assess spec §14.1
   reconstructs exactly that by regexing prose out of main scheme
   `Contents` blocks, including a prescribed-vs-recommended distinction
   drawn from grammar alone. Two independent derivations of the same
   mapping is the pattern this project already uses for Rules Reference
   versions and set-aside groups — a disagreement becomes a signal rather
   than a coin flip.
3. **`CanSimulate`.** Cerebro's own flag for whether a set is buildable.
   Every Fear No Evil villain set carries `CanSimulate: false` while its
   modular sets are `true` — Cerebro saying it knows the data is not
   deck-ready. That is precisely the "is this scenario assessable" gate the
   assess plan needs.

Even the cheapest of these — a declared-`size` check against cards present
— needs no second source at all, and should be built regardless.

## If a second source is ever imported

Not planned. Recorded because the constraint is easy to forget:

**A `source` column and per-field provenance are non-negotiable.** This
codebase has been bitten four times by two encodings mixed silently —
`boost` null versus 0, `set aside` versus `set-aside`, `entry_addressable`
versus `searchable`, and `permanent` meaning two different things. A merged
card table where a row's origin is not visible would be that same mistake
at maximum scale. A Cerebro-sourced card would silently lack quantities and
timing data, and every average computed over it would be wrong while
looking entirely plausible — the failure the assess spec opens with.

The honest degraded mode is the `timing` refusal: report the profile, state
plainly that it is unweighted because upstream publishes no quantities, and
never print a mean that looks like the others.

## How DragnCards does it

Its plugin (`hone/dragncards-mc-plugin`, Rust) pulls **both**: Cerebro for
card data, marvelcdb for quantity — `marvelcdb.rs` declares
`pub quantity: u32`. A release workflow generates a TSV and ships it as a
GitHub release asset.

`decks.rs` shows two quantity paths: `quantity: card.quantity` where
marvelcdb data exists, and a hard-coded `quantity: 1` in four other places.
Which path a Fear No Evil scenario takes was not established.

**Open, and cheaply settled by observation:** load the prebuilt Bullseye
villain and look for duplicate cards in the encounter deck. Duplicates mean
real copy counts exist somewhere not yet found. Exactly one of each means
the plugin falls back to `quantity: 1` — consistent with Cerebro's own
`CanSimulate: false`, and confirming the counts are simply unpublished.

Incidentally, `decks.rs` hard-codes special handling for the Infinity
Gauntlet, Invocation, Sense, Ship Command, Weather, Labor and Gift sets —
independent confirmation of the separate-deck and set-aside findings in
assess spec §14.5 and §14.8, arrived at from card text alone.

## Revisiting this

The decision turns on one fact — Cerebro publishes no copy counts — so it
is revisitable, and cheaply. Both maintainers are reachable on the
DragnCards Discord.

**For the Cerebro maintainer.** Only the first can change the decision; the
rest shape how an adoption would work.

1. **Are copy counts available anywhere** — an undocumented field, another
   endpoint, or planned? This is the entire blocker. Everything else about
   Cerebro is better than what we use.
2. **What does `CanSimulate` mean exactly?** We read it as "deck-buildable",
   because every Fear No Evil villain set is `false` while its modular sets
   are `true`. If that is right it is the "is this scenario assessable"
   gate the assess spec needs, and worth using whatever else we decide.
3. **Is `Printings[].ArtificialId` a contract?** We would join on it. If it
   is a convenience field that may drift from marvelcdb codes, the join
   needs a different key.
4. **Is bulk fetching acceptable, and is there a rate limit or a
   conditional-request path?** `/cards` is 4.5 MB. If we adopt it we should
   fetch politely and cache, the way `init` already does for the rulebooks.

**For the plugin maintainer (`hone`).** One question, and it answers the
open item below:

5. **Where do copy counts come from for sets marvelcdb has not entered?**
   `decks.rs` shows both `quantity: card.quantity` and a hard-coded
   `quantity: 1`. If the answer is "it falls back to 1", the counts are
   genuinely unpublished and this decision stands until someone enters
   them. If there is a third source, that changes everything.

**What a "yes" to (1) would mean.** Cerebro becomes viable as primary: it
has more cards, a structured modular mapping, and an assessability flag we
would otherwise derive by regexing prose. The work would be a second
adapter into the existing `cards` table — plus a plain-text trigger reader,
a glyph map, and the provenance discipline below. Substantial, but bounded,
and none of it is speculative: every piece was measured on 2026-08-25.

## Method note

Four searches in this investigation returned a false negative because they
were too narrow: `set aside` without the hyphenated form, `<b>Setup</b>`
without the bare `Setup.`, a `sets` join that silently dropped 26 cards
with no `set_code`, and a pack query that missed a separate
`*_encounter.json` file. Each was reported as a finding before being
corrected.

**A negative result about this corpus is only as strong as the variants
tried, and must be reported with the variants listed.** The same standard
assess spec §4.3 already applies to `boost: null`.
