# Scenario Assessment — Design

> **Status: captured, not yet detailed.** Written 2026-08-22 to record the
> idea and the data findings behind it before they were lost. Revisit after
> Phase 1 Tasks 15–17 land. Sections marked **[thin]** are deliberately
> under-specified and need a working pass before they can be planned.
>
> **Parent spec:** `docs/superpowers/specs/2026-08-20-mc-jarvis-design.md`
> **Parent plan:** `docs/superpowers/plans/2026-08-21-mc-jarvis-phase1-slice.md`

## 1. What this is

`mc-jarvis assess` answers one question: **what does this scenario throw at
you, and how well does your deck answer it?**

A player choosing modular sets, or building against a scenario they have not
beaten, wants numbers the card images do not give them in aggregate — the
average boost icon, how many minions, how many treacheries, how much
acceleration, how much Tough. Those numbers exist in the card data. Nothing
computes them today.

### Goals

- Report the composition of a scenario's encounter deck as facts, with the
  cards behind every number available on request.
- Accept the combination the player is actually playing: villain, modular
  sets, player count, difficulty set, heroic level.
- Cross-reference a real decklist against that profile, so the answer names
  the gap rather than the statistic.

### Non-goals

- Ranking scenarios by difficulty. Difficulty is not a scalar and the data
  does not support the claim.
- Recommending specific cards from Python. Card advice is judgement, and this
  project puts judgement above the CLI line, in `SKILL.md`. See §3.
- Simulating the encounter deck. This is a static profile, not a Monte Carlo.

## 2. The two-part seam

The spec is split, and the split is load-bearing:

| Part | Content | Depends on |
|---|---|---|
| **Part 1 — Threat profile** | Everything in §5–§8. Composition, boost curve, minion/treachery/side-scheme profile, keyword frequency. | Nothing beyond Phase 1. Plannable once Task 17 lands. |
| **Part 2 — Deck cross-reference** | §9. `--deck`, coverage gaps, the answer that names the gap. | `deck fetch` / `deck check`, which the Phase 1 plan puts explicitly out of scope. |

Welding the two together would block the whole feature on the unwritten
deck-pipeline plan. Part 1 must be implementable and shippable alone.

## 3. Where the judgement lives

The parent spec's architecture line: *everything deterministic lives below
the CLI line; the host model only supplies judgement, via a skill file that
teaches it these commands.*

`assess` therefore emits **facts and derived statistics**. It does not return
card recommendations. Part 2 goes one step further and emits **relational
facts** — "the encounter deck holds 6 Tough minions; your deck holds 2 cards
that remove Tough" — which is still a count, not an opinion. Turning that
into "cut a Tackle for a Nova" is the model's job, taught by `SKILL.md`.

A `recommend_tech()` returning card suggestions would invert the project's
architecture and make the feature untestable: you can assert numbers, you
cannot assert opinions.

## 4. Verified data findings

Confirmed by direct inspection of the marvelsdb corpus on 2026-08-22. These
are the facts the design rests on.

### 4.1 The fields exist and are not yet indexed

The corpus carries `boost` (1,244 cards), `boost_star` (419),
`base_threat`, `base_threat_fixed`, `base_threat_star`,
`escalation_threat`, `escalation_threat_fixed`, `escalation_threat_star`,
`attack`, `attack_star`, `attack_cost`, `scheme_star`,
`scheme_acceleration` (116), `scheme_amplify` (58), `scheme_crisis` (65),
`scheme_hazard` (88), `hidden` (330), `health_per_hero` (235),
`health_per_group`, `cost_per_hero`, `base_threat_per_group`.

**None of these is a column in `schema.py` today** — only `scheme` is. This
is a schema change and must bump `SCHEMA_VERSION`, or the real-data check
fails as a bare `no such column`.

### 4.2 Sets are cleanly typed

`sets.json` gives `card_set_type_code`:

| Type | Count |
|---|---|
| `modular` | 159 |
| `nemesis` | 69 |
| `hero` | 69 |
| `villain` | 58 |
| `hero_special` | 6 |
| `leader` | 6 |
| `standard` | 4 |
| `main_scheme` | 4 |
| `expert` | 2 |
| `evidence` | 1 |

The difficulty sets are real sets with real contents:

| Set | Cards | Boost values |
|---|---|---|
| `standard` | 5 treacheries | –, –, 1, 1, 2 |
| `expert` | 3 treacheries | 2, 2, 3 |
| `standard_ii` | 5 treacheries + 2 environments | –, –, 1, 2, 2, 2, 1 |
| `expert_ii` | 4 treacheries | 1, 4, 3, – |
| `standard_iii` | 4 treacheries + 2 environments + 1 obligation | –, –, –, 1, –, –, 2 |
| `standard_pvp` | 12 treacheries + 4 side schemes + 4 obligations | all – |

Omitting the difficulty set understates the boost curve. Expert's three
cards average boost 2.3.

### 4.3 `boost: null` means zero, and this was measured, not assumed

No card in the corpus has `boost: 0`. 501 encounter-type cards have
`boost: null`. Either `null` is semantic zero, or it is upstream data lag —
and those have opposite consequences for the headline statistic.

The discriminating test is the null rate over time. If nulls concentrate in
recent packs it is lag, and the mean is untrustworthy for exactly the newest
content players ask about. Measured over encounter-deck-eligible cards in
encounter sets, by pack release date:

| Pack | Released | Cards | Null | Rate |
|---|---|---|---|---|
| `core` | 2019-11-01 | 82 | 21 | 26% |
| `trors` | 2020-09-04 | 77 | 26 | 34% |
| `gmw` | 2021-04-02 | 90 | 37 | 41% |
| `mts` | 2021-09-01 | 101 | 34 | 34% |
| `sm` | 2022-04-08 | 107 | 33 | 31% |
| `mut_gen` | 2022-09-30 | 94 | 28 | 30% |
| `next_evol` | 2023-08-18 | 113 | 23 | 20% |
| `aoa` | 2024-03-29 | 120 | 54 | 45% |
| `aos` | 2025-02-20 | 116 | 27 | 23% |
| `cw` | 2025-10-17 | 87 | 33 | 38% |
| `fne` | 2026-07-24 | 8 | 1 | 12% |
| `luke_cage` | 2026-08-21 | 5 | 1 | 20% |

**Total: 1,593 cards, 468 null (29%), flat across seven years.** No drift.
`boost: null` is zero boost icons, and the quantity-weighted mean is
trustworthy.

By type, one outlier:

| Type | Cards | Null | Rate |
|---|---|---|---|
| `environment` | 91 | 64 | **70%** |
| `treachery` | 397 | 126 | 32% |
| `attachment` | 304 | 85 | 28% |
| `minion` | 436 | 118 | 27% |
| `side_scheme` | 365 | 75 | 21% |

Environments are the outlier because most do not sit in the encounter deck —
a membership question (§5), not a data question.

**Standing gate.** The build asserts no card has `boost: 0`. If upstream ever
starts emitting an explicit zero, the `null`-means-zero reading has changed
and the build must say so rather than silently mixing two encodings.

### 4.4 The `*_star` family is a flag, not a value

`boost_star` is `Counter({'True': 419})` — never a number. The same holds
for `attack_star` (451), `scheme_star` (117), `base_threat_star` (2),
`escalation_threat_star` (19), `defense_star` (3), `recover_star` (1),
`cost_star` (7).

**134 cards carry both `boost` and `boost_star`** — the star is an additional
icon with a card-specific effect, not a replacement for the numeric count.
Every one of these is reported as a separate count and none may enter a
numeric mean.

### 4.5 Quantity weighting is not optional

The Rhino set ships `Stampede ×3 boost 1` and `Charge ×2 boost 2`. A mean
over distinct card rows is not the expected boost of a card the player draws.
Every mean this feature reports is **quantity-weighted**, and the unweighted
form is not offered, because there is no question it answers.

### 4.6 `*_fixed` means "does not scale with player count"

`base_threat_fixed` (292 cards) and `escalation_threat_fixed` (7) are
booleans. Applying per-hero scaling to a fixed-threat scheme produces a wrong
number in exactly the way printing raw villain HP did — the correction the
parent plan already records for Task 10, repeated on the scheme side.

Same family: `health_per_hero` (235), `health_per_group` (1),
`cost_per_hero` (4), `base_threat_per_group` (1).

### 4.7 marvelsdb has no scenario → modular mapping

There is no field anywhere in `cards.json`, `packs.json`, or `sets.json` that
records which modular sets a published scenario prescribes. That mapping
lives in the scenario's printed rules insert. §7 covers the consequence.

## 5. The load-bearing problem: encounter deck membership

`Armored Rhino Suit` sits in `set_code = rhino` with `boost: null` and
**never enters the encounter deck** — it attaches to Rhino during setup. The
full `rhino` set as the data gives it:

```
villain      ×1   Rhino                    (stage I)
villain      ×1   Rhino                    (stage II)
villain      ×1   Rhino                    (stage III)
main_scheme  ×1   The Break-In!
main_scheme  ×1   The Break-In!            hidden=True
attachment   ×1   Armored Rhino Suit       <- set aside, attaches at setup
attachment   ×2   Charge             boost 2
attachment   ×1   Enhanced Ivory Horn boost 2
minion       ×2   Hydra Mercenary    boost 1
minion       ×1   Sandman            boost 2
minion       ×1   Shocker            boost 2
treachery    ×2   Hard to Keep Down
treachery    ×2   "I'm Tough"
treachery    ×3   Stampede           boost 1
side_scheme  ×1   Breakin' & Takin'  boost 2
side_scheme  ×1   Crowd Control      boost 2
```

Nine of the 21 physical cards are not in the encounter deck. **Set membership
is the denominator of every average in this feature.** Get it wrong and all
the numbers are wrong while looking entirely plausible.

Nothing in the data marks set-aside status. `hidden: True` marks card backs
(121 main schemes, 71 alter-egos, 41 villain stages), not set-aside cards.

### 5.1 Structure: the `outofdeck.py` pattern, reused

This is the same shape as the player-side problem `outofdeck.py` already
solves, and it takes the same structure:

1. A **detection rule** over card type and text, not a hand-written list.
2. An **explicit acknowledgment** config for every card the rule flags.
3. **Build-time re-verification** of each stated reason against the data.

The third point is not ceremony. The parent plan records why: an earlier
draft inferred coverage, and a set containing both a detectable set-aside
card and an unmarked one was silently passed — which is precisely what the
audit exists to catch. Coverage must be acknowledged, never inferred.

### 5.2 Roles **[thin]**

Each card in an encounter set is classified into one role:

| Role | Meaning |
|---|---|
| `deck` | Shuffled into the encounter deck |
| `set_aside` | Set aside, enters play by a card effect |
| `starts_in_play` | In play at setup (main scheme, stage I villain) |
| `setup_attachment` | Attached to a card at setup (`Armored Rhino Suit`) |

The detection rules for each are **not yet written**. Candidate signals:
`type_code` (`villain`, `main_scheme` are never `deck`), `hidden`, the
scenario's own setup text, and phrases in card text. This needs a working
pass over real sets before it can be planned, and it is the single largest
piece of unknown work in this spec.

## 6. Command surface

```
mc-jarvis assess <villain>
    [--modular CODE]...          override the scenarios.yaml default
    [--players N]                default 1
    [--difficulty standard|expert|standard_ii|expert_ii|standard_iii]
    [--heroic N]                 default 0
    [--campaign]
    [--nemesis HERO]...
    [--deck ID]                  Part 2 only
    [--json]
```

Consistent with the parent spec's Global Constraints: an explicit verb, and
`--json` on every leaf.

`--modular` **overrides** the defaults rather than adding to them. A player
naming modulars is describing the game on their table, not amending a
recommendation.

## 7. `config/scenarios.yaml`

Hand-authored from the printed rules inserts, because §4.7 established there
is no upstream source. Maps each villain set to its official modular sets,
and records the difficulty and encounter sets the scenario ships with.

Following the `legality.yaml` precedent, the build gate runs **in both
directions**:

- **Fail** when a villain set has no entry. A new release would otherwise be
  assessed against no modulars at all, silently.
- **Fail** when an entry names a set code that does not exist. A renamed or
  removed set would otherwise leave a stale mapping in force.

Both directions matter for the same reason they do in `legality.yaml` and
`deckrules.check`: a hand-maintained list does not converge on its own.

## 8. What Part 1 reports **[thin]**

Shape of the output; the exact field names need a pass.

- **Composition** — encounter deck size (quantity-weighted), broken down by
  card type, and by contributing set.
- **Boost curve** — quantity-weighted mean, the full histogram, the
  `boost_star` count and its share. Reported with the deck size it is drawn
  over, so the reader can see the denominator.
- **Minions** — count and copies, health / attack / scheme ranges, which
  scale per hero, and Guard / Tough / Retaliate / Overkill / Quickstrike
  frequency.
- **Treacheries** — count and copies, Surge rate, keyword frequency.
- **Side schemes** — count, threat values at the given player count, and
  crisis / acceleration / amplify / hazard icon counts.
- **Scheme pressure** — main scheme threat per stage at N players, honouring
  `*_fixed` (§4.6), plus total acceleration icons in the deck.
- **Keyword frequency** — one table across the whole deck.

Every number can name the cards behind it, so the model can cite rather than
assert.

## 9. Part 2 — deck cross-reference **[thin]**

**Blocked on `deck fetch` / `deck check`.** Do not begin this part before the
deck-pipeline plan exists.

`assess <villain> --deck <id>` reports relational facts:

- Threat removal available per turn against the scenario's acceleration rate.
- Cards that remove or ignore Tough against the count of Tough minions.
- Ranged / area attacks against minion swarm size.
- Ally count and health against Guard and minion attack values.

Each is a count set beside a count. The gap is stated; the fix is the model's
to propose.

Open: where the decklist comes from (marvelcdb id, local JSON, or both) is a
decision that belongs to the deck-pipeline plan, not to this spec.

## 10. Claims recorded as unverified

These are **not** findings. Each needs verification against a primary source
before it may be modelled.

- **Nemesis frequency by difficulty.** Stated by the user 2026-08-22: nemesis
  sets enter via a treachery under Standard I, while Standard III raises the
  frequency of nemesis appearance through a counter-based timer mechanism.
  Verify against the Standard III rules insert. Until verified, `--nemesis`
  folds the set in without modelling its arrival rate.
- **Heroic levels add boost icons.** Heroic is prose in a rules insert, not a
  card set. The exact modifier and how it interacts with `boost_star` need
  reading before either is encoded.
- **Campaign mode.** Adds persistent upgrades and campaign-specific cards.
  Scope not yet determined; may not belong in this spec at all.

The parent plan's culture is that every assumption about external data ends
with a number you can fail. A stated mechanic that quietly becomes a modelled
fact is the same failure as a fixture shaped from an assumption.

## 11. File structure

| File | Responsibility |
|---|---|
| `src/mc_jarvis/encounterdeck.py` | Build-time: encounter-deck role classification and the set-aside audit. Mirrors `outofdeck.py`. |
| `src/mc_jarvis/assess.py` | Query-time: assemble the scenario, aggregate, emit. Mirrors `cards.py`. |
| `config/scenarios.yaml` | Villain set → official modular sets. Gated both directions (§7). |
| `config/encounter_setup.yaml` | Acknowledged set-aside cards, each with a reason re-verified at build time. |
| `src/mc_jarvis/schema.py` | Extended with §4.1's columns and an `encounter_role` table. Bumps `SCHEMA_VERSION`. |

`encounterdeck.py` is separate from `assess.py` for the same reason
`cardtext.py` is separate from `cards.py`: classification is build-time
enrichment with a dense test surface, aggregation is query-time. They change
for different reasons.

## 12. Testing

Under the parent plan's Global Constraints — fixtures shaped from observed
data, and every data-shaped task ending at a real-data gate with a number
that can fail.

- **The gate is a hand-computed scenario, end to end.** Rhino at 2 players,
  Standard difficulty, no modulars: deck size, quantity-weighted boost mean,
  minion count and copies, treachery count, side-scheme count — worked out by
  hand from the card list in §5, then compared against what `assess` emits.
  A hand-computed number is the only check that can fail an error shared
  between the fixture and the implementation.
- **The `boost: 0` assertion** of §4.3 runs at build time, permanently.
- **The `scenarios.yaml` gate** of §7 runs at build time, both directions.
- **The set-aside audit** of §5.1 fails the build on any flagged card lacking
  an acknowledgment, and on any acknowledgment whose stated reason no longer
  holds.

## 13. Open questions

1. **§5.2 role detection** is the largest unknown. It needs a working pass
   over real encounter sets before this spec can become a plan.
2. **Does `assess` need the villain's own stages in the profile?** Villain
   health scales per hero and the stage matters, but the villain is not in
   the encounter deck. Probably a separate section of the output rather than
   part of the composition statistics.
3. **Environments.** 70% carry no boost value and most do not sit in the
   deck. Confirm during the §5.2 pass rather than assuming either way.
4. **Obligations.** 95 carry boost values and they enter the encounter deck
   only when their hero is in play — so they belong to the profile only under
   `--nemesis`, or when a modular set ships one (23 do).
