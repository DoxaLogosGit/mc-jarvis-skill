# Scenario Assessment — Design

> **Status: working pass done 2026-08-23; ready to plan Part 1.** Written
> 2026-08-22 to record the idea and the data findings behind it before they
> were lost. Sections marked **[thin]** were under-specified pending a pass
> over real encounter sets; that pass is now recorded in §14, and **it
> contradicts §4.7 and §5.2**. Read §14 before planning from anything
> below — the corrections are marked inline, but §14 carries the numbers.
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

Re-verified 2026-08-23 against the raw JSON, and the precise shape is
narrower than "null means zero": the `boost` key is **either absent or one
of 1, 2, 3, 4**. It is never `0` and never explicitly `null` — 1,244 cards
carry it (2:560, 1:353, 3:312, 4:19). So the gate is really two assertions:
no `0`, and no value outside 1–4.

### 4.4 The `*_star` family is a flag, not a value

`boost_star` is `Counter({'True': 419})` — never a number. Re-verified
2026-08-23 against the raw JSON: **eleven** `*_star` fields exist, not the
eight listed here, and every one is boolean `True` only —
`attack_star` (451), `boost_star` (419), `scheme_star` (117),
`thwart_star` (42), `escalation_threat_star` (19), `cost_star` (7),
`health_star` (7), `threat_star` (4), `defense_star` (3),
`recover_star` (1), `base_threat_star` (2).

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

### 4.7 marvelsdb has no scenario → modular mapping — **WRONG, see §14.1**

~~There is no field anywhere in `cards.json`, `packs.json`, or `sets.json`
that records which modular sets a published scenario prescribes.~~

There is no structured *field*, which is what this claim checked. But the
mapping is in the data: FFG prints it in the **`Contents` block of the
scenario's own main scheme card**, and marvelsdb carries that text
verbatim. 49 of 56 villain sets have one. §14.1 has the measurement and
what it changes.

## 5. The load-bearing problem: encounter deck membership

> **The example below is wrong — see §14.2.** `Armored Rhino Suit` is
> asserted here to be set aside. Nothing in the data says so: it reads
> `Attach to Rhino`, exactly like `Charge` and `Enhanced Ivory Horn`, which
> this same list calls encounter-deck cards. Rhino's main scheme carries no
> set-aside instruction at all — its entire `Setup` block is *"Advance to
> stage 1B."* The membership problem is real and the reasoning below stands;
> the card chosen to illustrate it does not.

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

> **Done, and it is not the largest piece of work — see §14.2.** The pass
> proved a negative: **no signal in the card data distinguishes a set-aside
> card from a deck card of the same type.** A detection rule over card text
> is not achievable. What is achievable is the type rule plus a small
> enumerated residue: **29 cards of 1,353 deck-eligible, or 2.1%**,
> concentrated in about ten scenarios.

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

## 9. Part 2 — deck cross-reference

**No longer blocked.** `deckfetch`, `deckcheck`, `deckstats` and `allycost`
all exist and are tested; the schema carries `attack_cost` / `thwart_cost`
as of version 22.

This section was rewritten on 2026-09-02 after every one of its four
original pairings failed measurement. The findings are recorded in
**`2026-08-20-mc-jarvis-design.md` §§10.5–10.13** — a different document,
and a different §10 from this file's "Claims recorded as unverified".
Citations below name it explicitly.

### 9.0 The mistake that produced the original four

Each original pairing was derived from a keyword's **name** rather than
from what the Rules Reference says the keyword **does**. That single error
produced four confidently wrong pairings:

- `ranged` was paired against swarm size; it does nothing but ignore
  retaliate (design §10.11).
- Tough was measured by searching for the word *tough*, which found one
  answer; the mechanism is piercing, which found eleven (design §10.10).
- Guard was paired against ally count; it forbids an *action*, so allies —
  whose basic attack is an attack — are not an answer at all (design
  §10.12).
- Acceleration was treated as one quantity; icons and tokens are formally
  distinct and the Rules Reference says so in both entries (design §10.13).

**Standing instruction for whoever implements this:** before counting a
keyword, read its Rules Reference entry and count the *mechanism*. A query
written from a keyword's name has been wrong four times out of four here.

### 9.1 What the index cannot see

Three inputs to these questions are runtime state with no column, and any
output must not imply otherwise:

- **Acceleration tokens** (design §10.13). Not representable. They also
  enter play when the encounter deck empties, so a long game accelerates
  invisibly.
- **Hand contents.** `Cannonball` reduces his consequential damage by the
  number of [[AERIAL]] cards in hand (design §10.7).
- **Engagement.** This one is easy to report wrongly. Guard forbids
  attacking the villain *while a guard minion is engaged with you*, and
  Patrol likewise. A scenario's Guard count is therefore **potential
  Guard**, never active Guard, and must be labelled as such.

### 9.2 The four cross-references

Each is a count beside a count in **matched units**. Where the deck side is
unmeasured, it says so.

**1. Side-scheme pressure against acceleration.**

Not a rate against a rate. 97 of 116 acceleration icons sit on side schemes,
so thwarting one reduces the acceleration generating the threat you must
thwart: it is a feedback loop, and a ratio implies a static exchange the
game does not have (design §10.13). Report the scenario's icon sources and
where they sit, beside the deck's threat removal — as a **ceiling**, never
a per-turn rate, since a true rate needs readying, exhaustion, resources and
draw (design §10.5). Ally contribution is bounded by consequential damage
and reported split (design §10.6, §10.7).

Deck side measured and implemented in `threatremoval.py`. It is **three
numbers, not one**, because three different things limit them:

- **Basic thwarts — limited by exhaustion.** RR p.44: a character must
  exhaust to use a basic power. One per character per turn, and the ally
  side is capped again by the **ally limit of three in play** (RR p.7).
  That cap is not cosmetic: **62% of 1,501 published decks hold more than
  three allies**, and ignoring it overstates the ceiling **1.40x** on
  average across the corpus. Still a ceiling, since it assumes the three
  best allies are in play, ready, and spending their activation on
  thwarting rather than attacking or blocking (design §10.6).

  **Three is a default, not a constant**, and treating it as one was the
  first implementation's error:

  - It limits allies **in play**. One corpus deck holds 13 allies to field
    three.
  - **Cards raise it.** `The Triskelion` (leadership) unconditionally;
    `Avengers Tower`, `Utopia`, `Flight Squadron` and `Knowhere` on a trait
    condition. **16% of corpus decks carry one.** All five must be in play,
    so they are *named as potential* and never folded into the ceiling —
    applying them would assert a board state the deck cannot promise.
  - **Allies are exempted from it.** `Stinger`, the four `New Recruits`
    (Surge, Anole, Bling!, Indra) and the four `trickster_magic` linked
    allies consume no slot, so they field *in addition* to the three. 3% of
    corpus decks carry one; counting them within the limit understates the
    ceiling.
- **`(thwart)`-designated abilities — limited by resources, not
  exhaustion.** The same RR entry: "Unless specified by the ability's
  text, a hero does not exhaust" to resolve a `Hero Action (thwart)`.
  These are *additional* instances and must never be added into the
  exhaustion ceiling as though they competed for it.
- **Threat removal that is not a thwart.** Passes through Patrol (design
  §10.12) and is not a thwart attempt for any card that cares.

`allycost.totals` deliberately does **not** apply the ally limit: its
figures are lifetime totals, and an ally defeated in round two is replaced
by one played in round three. The two are named apart — `thwart_lifetime`
there, `basic_thwart.ceiling` here.

**2. Piercing against Tough.**

Deck: piercing sources, read from the deck's own card text — 11 exist in the
open pool, 5 of them allies, and `Brute Force` grants it to basic attacks.
Piercing is never *printed* on a player card, so this is readable within a
40–50 card deck but not queryable across the pool (design §10.10).
Scenario: Tough sources, keyword and granted counted separately; the spread
is 0–10 across scenarios and 13 of 53 have none.

Second answer, reported alongside: **damage per instance**. One tough card
annuls an entire damage instance whatever its size, so Tough is regressive
in hit size (design §10.9).

**3. Ranged against villain retaliate.**

Deck: ranged sources, split by reliability — permanent self-grants
(Star-Lord, Yondu, War Machine, Sidearm, Hawkeye's Bow) and ranged weapons
are dependable; one-attack events are not; `Directed Force` and
`Sharpshooter` grant nothing (design §10.11).
Scenario: **villain retaliate separated from all other retaliate.** Zola
prints Retaliate 1 on all three stages and taxes every attack all game;
a modular minion taxes only the attacks you choose to make into it. 10
scenarios carry villain retaliate, 23 carry it only elsewhere, 20 none.

Second answer: retaliate needs the character to survive the attack, so a
one-shot kill pays nothing.

**4. Non-attack damage against Guard; non-thwart threat removal against
Patrol.**

Deck: 103 cards deal damage to the villain without being an attack (51 open
pool); 71 remove threat without being a thwart (41 open pool). Read from the
`(attack)` / `(thwart)` designators, which **compound** — `(attack/thwart)`,
`(attack/defense/thwart)` — so the test is whether `attack` appears as a
token, not as a substring. 7 cards deal non-attack damage that only an
attack can trigger, and are excluded (design §10.12).
Scenario: 61 Guard minions and 15 granting cards; 23 Patrol and 3. The
grants are not additive — `Blue Area of the Moon` gives *every* minion
guard, so a Guard figure must state whether a global grant is in play.

Ally attack capacity belongs here as the answer to **the minion**, which is
what allies actually contribute.

### 9.2a Implemented, 2026-09-03

`crossref.py`, reached by `assess <scenario> --deck <id|path>`. Two
decisions the implementation settled:

**The cross-reference attaches to every trajectory step, not to one deck.**
The opening deck answers what you face first; it does not answer a session.
`dark_beast` is the case that proves it: its opening deck prints no tough,
no guard and no patrol, and after three sets shuffle in it has guard 3,
patrol 2 and tough 1. A single figure for the whole scenario would hide
the half that arrives later.

**A villain stage is not an encounter-deck row.** `assess.deck_cards`
returns the encounter deck, which never contains the villain, so the first
working version reported **zero villain retaliate for Zola** — who prints
Retaliate 1 on all three stages and is the single most important retaliate
fact in the game. `crossref.villain_rows` supplies them from the scenario's
set codes. This is the §10.5 population error a fourth time: the query was
right and the population was wrong.

Two classifier defects found by tests rather than by reading:

- `"this attack gains ranged"` matched the permanent self-grant pattern,
  putting `Marvel Boy` beside `Star-Lord`. The determiner discriminates —
  a permanent grant is possessive (`'s`, `your`, `its`), a one-off is
  demonstrative — and `this`/`that` are both five characters, so a
  fixed-width lookbehind separates them.
- Keywords are granted in **lists**. `Marvel Boy` reads "gains piercing and
  ranged", so requiring the keyword to follow `gains` directly classified
  six real grants as merely mentioning it.

Verified against the whole pool: ranged resolves to 5 permanent, 14
one-attack, 2 payoff-only (`Sharpshooter`, `Directed Force`); piercing to
11 permanent, 2 conditional, 22 one-attack, 3 payoff-only — the last
including both `Luke Cage` faces, whose text makes attacks *lose* piercing.

### 9.3 What this reports, and what it does not

Facts in matched units, and the gap between them. The fix stays the model's
to propose (§3), and the pool stays out of reach: answering "you could have
included X" requires the card pool, which is a recommendation, not a
statistic (design §10.5).

Two heroes invert the whole section and must not be reported as deficient:
**Colossus** accumulates tough as a currency, and **Deadpool** scales off
acceleration tokens — `Cable`, `Montage` and `It Ain't Over...` all grow
with them and `Exhausting Personality` places one as a cost (design §10.5,
§10.13).

Open: where the decklist comes from is settled — `deckfetch` takes a
marvelcdb id or a local JSON file.

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

---

## 14. Working pass, 2026-08-23

The pass §5.2 asked for, run against the real corpus. Two findings
contradict the spec above, and both make the feature *smaller*.

### 14.1 The scenario → modular mapping is in the data (corrects §4.7)

§4.7 checked for a structured field and correctly found none. It did not
check the card text. FFG prints the scenario's contents on the **main
scheme card**, and marvelsdb carries it verbatim:

> `[unus]` **Contents**: Unus (I) and Unus (II). *(Unus (II) and Unus (III)
> instead for expert mode.)* Unus, Infinites, and Standard sets. **One
> modular set** *(Dystopian Nightmare)*. **Setup**: Reveal the Gene Pool
> side scheme.

**61 main-scheme cards across 55 sets carry a `Contents` block; 49 of the
56 villain sets have one.** Parsing the modular clause and resolving the
names against `sets.name` where `card_set_type_code = 'modular'`:

| Outcome | Villain sets |
|---|---|
| named, every name resolved | 35 |
| named, at least one name unresolved | 7 |
| no `Contents` block at all | 7 |
| player chooses, no set named | 6 |
| random selection | 1 |

The 7 unresolved are **not** a parsing dead end — they are formatting
variance plus one upstream typo:

- `'<i>Acolytes</i>'`, `'<i>Mystique</i>'`, `'<i>Sentinels</i>'`,
  `'<i>Zero Tolerance</i>'`, `'<i>Brotherhood</i>'` — inner markup left in
  the capture; strip tags before resolving.
- `'S.H.I.E.L.D'` — the set is named `S.H.I.E.L.D.`, with the final stop.
- `"Batrocs's Brigade"` — FFG's own typo for `Batroc's Brigade`. One card,
  and a misprint like the `Hero Reponse` family already in `timing.yaml`.

**Three kinds of scenario, not one mapping.** The parse must keep them
apart, because a player choosing modulars needs to know which the box
prescribes:

- **prescribed** — `(Dystopian Nightmare)` stated flatly;
- **recommended** — `(recommended: Bomb Scare)`, as Rhino and Ultron print
  it. The player may substitute freely;
- **open** — *"Choose 1 modular set, plus 1 per hero…"* (Thunderbolts,
  Mojo), *"3–4 modular sets"* (the PvP scenarios), or random (Magog).

Flattening `recommended` into `prescribed` would state a constraint the box
does not impose.

**What this changes in §7.** `config/scenarios.yaml` stops being
hand-authored from printed inserts for all 56 scenarios. It is **parsed
from the main scheme**, and the config carries only what the text cannot
give: the 7 sets with no `Contents` block, the one typo, and any name the
parse cannot resolve. Same shape as `timing.yaml` — the primary source is
parsed, the config holds only the residue, and both directions are gated.
§7's two failure modes still apply, and gain a third: **fail when a
`Contents` block names a modular set that does not resolve and no config
entry covers it.**

### 14.2 Set-aside cannot be detected, and it barely matters (corrects §5.2)

§5.1 proposed "a detection rule over card type and text, not a hand-written
list". **For `set_aside`, that rule does not exist.** Measured:

- `Armored Rhino Suit` reads `Attach to Rhino.` — character-for-character
  the same opening as `Charge` and `Enhanced Ivory Horn`, which §5 lists as
  encounter-deck cards. No field, keyword, or phrase separates them.
- **Five cards in the whole corpus** contain the phrase "set aside", and
  three of those are `Contents`/`Setup` prose rather than the card's own
  rules text.
- `hidden` marks card backs, as §5 already says. It is not a role.

The instruction lives in the **main scheme's `Setup` block**, in prose —
17 of 55 sets carry one — and it names things in four different ways:

| Form | Example |
|---|---|
| a named card | *"Set the Orbital Decay side scheme aside."* |
| a trait | *"Set each [[Captive]] ally aside."* |
| a whole set | *"Set the Blue Moon, Genosha, and Savage Land sets aside."* |
| a category | *"Set aside each unused villain card."* |

**Deck-eligible types, settled.** `minion`, `treachery`, `side_scheme`,
`attachment`, `environment`. Not eligible: `villain` and `main_scheme`
(start in play), and `ally` / `upgrade` / `event` / `support` / `resource`
/ `player_side_scheme`, which are **player-side cards** that happen to ship
in encounter sets — every encounter-set `ally` is a rescued-captive type
that enters play for the players via a side scheme, never shuffled in.
`obligation` is eligible only under `--nemesis` (§13.4). Settling this
first matters: it moves the denominator of every average.

**Magnitude — corpus-wide is the wrong measure.** `assess` never reports a
corpus average; it reports one scenario's deck. Per affected scenario,
set-aside cards as a share of that scenario's deck-eligible copies:

| Scenario | Deck-eligible | Set aside | Error |
|---|---|---|---|
| `m.o.d.o.k.` | 25 | 4 | **16.0%** |
| `apocalypse` | 14 | 1 | 7.1% |
| `morlock_siege` | 14 | 1 | 7.1% |
| `red_skull` | 23 | 1 | 4.3% |
| `magneto_villain` | 26 | 1 | 3.8% |
| `god_of_lies` | 28 | 1 | 3.6% |
| `enchantress_villain` | 32 | 1 | 3.1% |

**So the config is a prerequisite, not a refinement** — for the scenarios
it affects. A 16% error in the denominator makes every average that
scenario reports wrong while looking entirely plausible, which is the
failure §5 opens with.

**But the affected scenarios are detectable**, which is what makes this
tractable. A scenario whose main-scheme `Setup` block contains a set-aside
or put-into-play instruction is one where the type rule is unreliable:

| | Villain sets |
|---|---|
| `Setup` says "set … aside" | 16 |
| `Setup` says "put … into play" | 26 |
| both | 9 |
| **needs acknowledgment (either)** | **33** |
| **type rule alone is sufficient** | **23** |

> **Corrected to 41 on 2026-08-27.** Those counts came from matching
> within an arbitrary 60-character window between "put" and "into play".
> The Wrecking Crew's Breakout reads *"Put the Day of Reckoning,
> Thunderstruck, Pile It On!, and Clear the Road side schemes into play"* —
> 85 characters — so the whole scenario slipped the audit unflagged and its
> four side schemes stayed classified as deck cards. Scoped to a sentence
> instead, **41 of 56** scenarios remove cards at setup, not 33.
>
> Two lessons, both already on this project's list. An unmeasured cutoff
> hides exactly what it is too small for — the same failure as the 40-char
> trigger-prefix limit. And a rule that extracts *some* of a list passed an
> `all(...)` check on the subset it found, which is worse than extracting
> nothing: `wrecking_crew` looked covered.

So the design is the `timing` refusal, not a silent approximation:

- The type rule stands for all 56, and is complete for 23 of them.
- For the 33 flagged, `config/encounter_setup.yaml` must acknowledge what
  the `Setup` sentence removes, each entry carrying that sentence and
  re-verified at build time.
- **`assess` flags a scenario whose `Setup` block is flagged and
  unacknowledged**, rather than reporting numbers that may be a sixth
  wrong. Same move as `timing` refusing when its chart does not match the
  indexed rulebook.

The whole-set asides are a different question: they change *which sets are
in play*, not which cards within a set are in the deck, and belong to
scenario assembly (§14.1).

§5.1's three-step structure survives with its first step replaced: not a
detection rule over card text, but a **type rule plus a detectable flag
plus an enumerated residue**.

### 14.3 Confirmed unchanged

- **No card has `boost: 0`** (§4.3). The gate is valid. Narrower than
  stated: the key is either **absent or 1–4**, never `0` and never an
  explicit `null` — 1,244 cards carry it (2:560, 1:353, 3:312, 4:19). So
  the gate is two assertions, not one.
- **Every `*_star` field is boolean `True`** (§4.4), verified against the
  raw JSON. There are **eleven**, not the eight listed: `health_star`,
  `threat_star` and `thwart_star` were missed.

### 14.4 Still open after this pass

- §13.3 (environments) is now partly answered and partly sharpened: they
  are deck-eligible by type, but 26 scenarios "put" one into play at setup
  and `m.o.d.o.k.` sets three of four aside — so environments are the
  single biggest driver of the flagged-scenario residue.
- §13.2 (villain stages) and §13.4 (obligations) are untouched and remain
  open.
- The **`recommended` vs `prescribed` distinction** is drawn from grammar
  alone. It should be checked against one printed insert before it is
  relied on, per §10's rule that a stated mechanic must not quietly become
  a modelled fact. **Checked 2026-09-03 and the warning was justified —
  see §14.11.**
- Whether a `Contents` block lists what a scenario **requires** or what
  **shipped in the box** — `dark_beast` names five sets, only one of them
  modular. The parse takes the modular clause specifically, which sidesteps
  this, but the question should be settled before the non-modular part of
  the block is used for anything.

### 14.5 Corrections from domain knowledge, 2026-08-23

Four cards named by the user, checked against the corpus. Two of them
correct §14.2, which overstated the negative.

**§14.2 was too strong: a signal does exist.** A `Setup` keyword in the
card's own text marks a card that enters play at setup, and it catches
exactly the cards the user named:

| Card | Set | Type | `permanent` | `boost` |
|---|---|---|---|---|
| `Infinity Gauntlet` | `infinity_gauntlet` | attachment | 1 | – |
| `Power Stone` | `power_stone` | attachment | 1 | – |
| `Flight` / `Super Strength` / `Telepathy` | own sets | attachment | 1 | – |
| `Gene Pool`, `Ancient Ritual` | `infinites`, `clan_akkaba` | side_scheme | 1 | – |
| `The Savage Land`, `Genosha`, `Blue Area of the Moon` | own sets | environment | – | 3 |

**13 deck-eligible cards carry it.** Small, but precise and free — it costs
one regex and needs no acknowledgment. §14.2's claim that "no signal in the
card data distinguishes a set-aside card from a deck card" is wrong as
stated; the correct claim is narrower: **no signal distinguishes the
*scenario-specific* asides** — the ones named only in a main scheme's
`Setup` prose, like `Orbital Decay` or the `[[Captive]]` allies.

**`permanent` is NOT a membership signal, and this is a trap.** It is
tempting — 37 deck-eligible cards carry it — but it means "cannot be
discarded from play", not "starts outside the deck". Enchantress's
`Trance of Envy` is `permanent` **and** has a `When Revealed` ability,
which only fires when a card is revealed from the encounter deck. It is
drawn, then stays. The same holds for `Intense Focus` and `Total Focus`.
Treating `permanent` as "not in the deck" would wrongly remove cards that
demonstrably are.

**`boost` is not a membership signal either**, though it looks like one.
`Armored Rhino Suit` has no boost value and `Charge` has 2 — which is the
difference §5 needed and could not find. But `The Sleeper` and
`Future of Despair` are both set aside by their scenario's `Setup` block
and carry boost 1 and 3. Absence correlates; presence does not exclude.

**A fifth role is missing: `other_deck`.** The spec's four roles have no
place for a card that belongs to a *different* deck. Six exist:

| Deck | Sets |
|---|---|
| `[[infinity stone]]` | `infinity_gauntlet`, `loki`, `thanos` |
| `[[invocation]]` | `doctor_strange` and its nemesis / invocation sets |
| `[[sense]]` | `daredevil` |
| `[[gift]]`, `[[labor]]` | `hercules` |
| `[[weather]]` | `storm` |

**6 cards belong to the infinity stone deck**, and they are detectable by
that membership claim: their text says `Place this card in the
[[infinity stone]] deck`.

> **Corrected 2026-08-26 while implementing this.** This section first said
> 15, measured by matching any card whose text *mentions* `[[infinity
> stone]]`. That counts referrers, not members: 24 cards name a `[[X]]
> deck` and only 6 say they go into one — the rest say "put the top card
> of", "shuffle the", "begins the game with". `Infinity Gauntlet` is the
> card that makes the difference matter, because it is a **setup
> attachment** that happens to discuss the stone deck, and a mention-match
> files it as a member. Both readings keep it out of the encounter deck,
> so the count of excluded cards was right by accident — but the role was
> wrong, and the role is what `assess` reports.
>
> A sixth instance of the project's recurring failure: a regex matching a
> mention where a claim was meant. The `infinity_gauntlet` modular is the sharpest
case in the corpus — **7 cards, none of them in the encounter deck**: the
Gauntlet attaches at setup, and the six Stones are their own deck. A
scenario including that modular would gain 7 phantom encounter cards, a
100% error for that set's contribution.

**Data-source bound — traced 2026-08-25, see
`2026-08-25-card-data-sources.md`.** Bullseye *is* a playable villain in
Fear No Evil; the card is `Adamantium-Laced Spine` (singular, "Laced"),
which is why three searches missed it. marvelcdb has **68 of a declared
276** cards for that box and none of its five villain sets — the encounter
half is simply unentered upstream, in both the GitHub repo and the live
API. DragnCards sees it because it also reads **Cerebro**, a separate
community database with 4,632 cards.

Decided: marvelcdb stays primary, Cerebro is a backup and cross-check
only, because Cerebro publishes no quantities and every mean here is
quantity-weighted (§4.5).

Two consequences for this spec:

- `assess` must distinguish **"you typed the name wrong"** from **"the
  data is not published"**. `packs.json` declares a `size` per pack, so
  the second is detectable with no second source at all: *"Fear No Evil
  holds 68 of a declared 276 cards; its encounter sets are not in the
  index."*
- `Adamantium-Laced Spine` validates §14.7 against content we have never
  seen. Bullseye (I) reads *"When Revealed: **Set aside** Adamantium-Laced
  Spine"* and Bullseye (II) *"Find Adamantium-Laced Spine and attach it"* —
  a set-aside card named by another card's text, then brought into play by
  a stage advance. It is also a shape §5.2's four roles do not cover: set
  aside at setup, then a **permanent attachment** mid-game, never in the
  encounter deck at any point.

### 14.6 `Setup` alone does not exclude a card — it can cycle back

Raised by the user and confirmed in the data: a card that starts in play
may later be removed to the **encounter discard pile**, and rejoins the
encounter deck at the next reshuffle. Starting in play and being in the
deck are not exclusive.

The three `[[Setting]]` environments prove it, and they carry their own
evidence:

> `The Savage Land` — **Setup.** The villain gains retaliate 1.
> **Special**: … **When Revealed**: Discard each other `[[Setting]]`
> environment in play. — `permanent` = –, **boost = 3**

A `When Revealed` ability and a boost value are both **meaningless for a
card that never enters the encounter deck**: When Revealed fires only when
a card is revealed from it, and a boost value is only read when the card is
drawn face-down as a boost card. `Genosha` and `Blue Area of the Moon` are
identical in shape. So the cycle is: start in play → another Setting
environment is revealed → discarded → reshuffled into the deck → drawn.

**`permanent` earns its place here after all**, in the opposite direction
to §14.5's trap. It means "cannot be discarded from play", so a `Setup`
card that is also `permanent` can never reach the discard pile and never
rejoins the deck. That splits the 13 cleanly:

| `Setup` + … | Cards | In the deck? |
|---|---|---|
| `permanent` | 7 — Power Stone, Infinity Gauntlet, Flight, Super Strength, Telepathy, Gene Pool, Ancient Ritual | **never** |
| `When Revealed` and/or `boost` | 3 — the `[[Setting]]` environments | **starts in play, returns later** |
| neither | 3 — the `Chief … Officer` environments (they *flip*, they do not discard) | probably never; unverified |

So `starts_in_play` is not one role but two, and the difference matters to
`assess`: a card that rejoins the deck belongs in the composition
statistics, just not in the opening deck. The model needs a
`returns_to_deck` flag alongside the role, not a fourth role value.

**Revised detection order**, replacing §14.2's two-step and §14.5's first
draft:

1. `type_code` — `villain` and `main_scheme` are never in the deck; the
   player-side types (§14.2) are never in it either.
2. `Place this card in the [[X]] deck` → `other_deck`. 15+ cards, free.
3. `Setup` keyword **and** `permanent` → `starts_in_play`, never returns.
   7 cards, free.
4. `Setup` keyword **without** `permanent` → starts in play but
   `returns_to_deck`, if it carries a boost value or a `When Revealed`
   ability. 3 cards; the remaining 3 are unverified and go to config.
5. The scenario's `Setup` prose → the residue, per scenario, acknowledged
   in config and gated. 33 of 56 scenarios need one.
6. Anything left → `deck`.

Steps 2–4 are free. They do not remove step 5, but they shrink it and they
catch the two worst cases in the corpus.

### 14.7 The set-aside list *is* derivable from card text — I searched wrong twice

§14.2 concluded "only five cards in the whole corpus contain the phrase
'set aside'". That search was for the **spaced** form. FFG writes the
adjective **hyphenated**, and:

| Form | Cards |
|---|---|
| `set aside` (verb) | 5 |
| `set-aside` (adjective) | **91** |

Ninety-one cards refer to set-aside cards, and they do it in a resolvable
way — as **trait-and-type groups**, not free prose:

> `Heart of the Empire` — *The first player reveals a random set-aside
> `[[Prelate]]` minion.*
> `Upgrading Adaptoids` — *put 1 random set-aside `[[Adaptoid]]`
> environment into play instead.*
> `Sabotage Master Mold` — *Reveal the set-aside Orbital Decay side
> scheme.*

Extracting `set-aside (<trait>|<Name>) <type>` and resolving against the
corpus:

| Group | Type | Copies | Referenced from |
|---|---|---|---|
| `[[Thunderbolt]]` | minion | **19** | `thunderbolts` |
| `[[Captive]]` | ally | 13 | `project_wideawake`, `taskmaster` |
| `[[Prelate]]` | minion | 5 | `apocalypse` |
| `[[Adaptoid]]` | environment | 4 | `m.o.d.o.k.` |
| `[[Morlock]]` | ally | 4 | `morlock_siege` |
| `Rescued Captive` | ally | 4 | `batroc` |
| `Orbital Decay` | side scheme | 1 | `magneto_villain` |
| `Absorbing Man`, `Titania`, `Whirlwind`, `Zzzax` | ally | 4 | `trickster_magic` |
| `Dreadpool` | minion | 1 | `dreadpool` |

**Every group here independently matches what §14.2 derived from the main
scheme `Setup` blocks**, and it adds one the Setup blocks missed — the 19
`[[Thunderbolt]]` minions. Two unrelated places in the data agreeing is
the same shape as the mirror's two version strategies: it makes the result
checkable rather than trusted, and a disagreement is a signal rather than
a coin flip.

Two regex artefacts to exclude: `set-aside area for …` is the *nemesis*
set-aside area, not a card group.

**What this changes.** §5.1's original instinct — "a detection rule over
card type and text, not a hand-written list" — was right, and §14.2 was
wrong to abandon it. `config/encounter_setup.yaml` shrinks again: it holds
only what *neither* source names, and the build gate becomes a
cross-check between the two sources plus an acknowledgment for the
residue.

**Method note, recorded because it cost two wrong conclusions.** Both
errors were the same mistake: searching one spelling and reporting the
absence as a finding. `set aside` vs `set-aside`, and earlier
`<b>Setup</b>` without the bare `Setup.` form. A negative result about
text in this corpus is only as strong as the variants tried, and it must
be reported with the variants listed — the same standard §4.3 already
applies to `boost: null`.

### 14.8 Quest chains: side schemes that advance, and never enter the deck

Confirmed by the user for `magneto_villain`, and the chain is fully
visible in the card text — each link names the next:

> `Boarding Party` → **When Defeated**: Flip this card and reveal
> `Sabotage Master Mold`
> `Sabotage Master Mold` → **When Defeated**: Reveal the set-aside
> `Orbital Decay` side scheme
> `Orbital Decay` → **When Defeated**: Flip this card and reveal
> `Physical Strain`

They function as a quest: heroes remove threat to advance to the next, and
the last one is what allows Magneto to be defeated. **None of them ever
enters the encounter deck**, and unlike the `[[Setting]]` environments of
§14.6 they never cycle back.

Their signature separates them from the deck side schemes in the same set:
each carries a **`When Defeated`** ability and a static restriction
(*"Magneto cannot have more than 6[per_hero] sustained damage"*), and
crucially **no boost value and no `When Revealed`** — while `Magnetic
Mayhem` (boost 4), `Seized!` (boost 3) and `Magnetically Sealed` (`When
Revealed` + `Boost`) in the same set have both and are deck cards.

That is the §14.6 discriminator applied to a different role: **a card with
no boost value and no `When Revealed` ability has no way to be used from
the encounter deck.** It is worth testing as a general negative signal
before the config is written, because it would also catch the chain
members that no other card names.

**Still open:** the three `Chief … Officer` environments — the user is
checking whether they can ever be discarded. They *flip* rather than
discard, which would keep them out of the deck permanently, but "flip" is
not proof that nothing else discards them.

### 14.9 Scenarios whose deck grows during play

Raised by the user: The Hood, Mojo and Dark Beast add modular sets to the
encounter deck *while you play*, at random. A single deck profile is the
wrong answer for these, and pretending otherwise would be the same class
of error as reporting a mean over the wrong denominator.

All three are the same mechanism with different parameters — a **pool**
of set-aside sets, and a **trigger** that shuffles one in:

| Scenario | Pool | Determinable? | Trigger |
|---|---|---|---|
| `dark_beast` | Blue Moon, Genosha, Savage Land | **yes** — named in `Contents` | villain stage `When Revealed` |
| `mojo` | the 7 MojoMania modulars (Crime, Fantasy, Horror, Longshot, Sci-Fi, Sitcom, Western) — player pre-selects 1 + 1/hero | **yes** — the pack's modular sets | main scheme `When Revealed` |
| `the_hood` | any 7 modulars the player chooses, from all 158 | **no** | villain and main scheme `When Revealed` |

`the_hood` therefore *requires* `--modular`; there is nothing to infer.
`assess` must say so rather than assess it against an empty pool. The
other two have pools the data gives us.

**The model: report a trajectory, not a number.** The deck is a function
of how many additions have happened, so report the profile at each step
rather than predicting where a game stops. Predicting that would be
simulation, which §1 rules out as a non-goal.

- **k = 0** — the opening deck: villain set, difficulty set, and anything
  shuffled in at setup. Fully deterministic.
- **k = 1 … |pool|** — the deck after that many additions.

**Two of the three statistics are exactly computable, and the third is
not — the difference must be printed, not hidden.**

- **Additive statistics** — deck size, total boost icons, minion copies,
  acceleration icons. Sets are drawn uniformly without replacement, so by
  linearity of expectation the expected contribution after `k` draws is
  exactly `k/n ×` the pool total. **Exact, not a simulation.** The bounds
  are exact too: sort the pool by that statistic and take the `k` lightest
  and `k` heaviest.
- **Ratio statistics** — quantity-weighted mean boost, Surge rate. These
  are ratios of two random quantities, and `E[X/Y] ≠ E[X]/E[Y]`. The
  **range is still exact** (min and max over the k-subsets), so report the
  range as the answer and the ratio-of-expectations only if it is labelled
  as an approximation. Reporting it bare would be a number that looks like
  the others and is not.

So the honest output for `dark_beast` is not "average boost 1.8" but
"opening deck 24 cards, mean boost 1.6; after one environment set is
shuffled in, 31–34 cards and mean boost 1.7–1.9". The player gets the
spread they actually face, and the model has something to reason with.

**Cheapest correct first version:** report `k = 0` and `k = |pool|` — the
opening deck and the fully-grown deck — and name the pool. That is two
exact profiles and no statistics anyone has to caveat, and it already
answers "what does this scenario throw at me" better than a single
number that is wrong for the whole game.

### 14.10 A scenario is not a villain

Raised 2026-08-27: Fear No Evil ships five scenarios, each of which lets
you choose among five villains. That breaks the assumption that a villain
set *is* a scenario — and the assumption is already broken in the data
mc-jarvis holds, before FNE arrives.

Of 57 sets carrying a main scheme, **7 have no villain set of their own**:

| Scenario | Where its villain comes from |
|---|---|
| `morlock_siege`, `on_the_run` | a chosen `[[MARAUDER]]` villain |
| `registration`, `resistance`, and their `synthezoid_` variants | the PvP "chosen leader" |
| `wrecking_crew` | four separate villain sets at once |

And 6 villain sets have no main scheme, because they are *components*:
the four Wrecking Crew sets, `marauders`, and `exp_kang`.

So the mapping is many-to-many in both directions, and the column that
recorded it was misnamed `villain_set`. It is now `scenario_set`: the set
holding the main scheme, which is what a scenario actually is.

**But this changes the threat profile far less than it appears.**
Measured: **no villain card is ever an encounter-deck member** — the type
rule excludes every one — so which villain a scenario hosts does not
change its encounter deck. `morlock_siege` is the in-data proof: it
shuffles all seven `[[MARAUDER]]` villains into a villain deck and turns
them up in random order, and its encounter deck is identical every time.
The profile is a property of the scenario; the villain contributes its
own stats, which §13.2 already separates out as an open question.

Bullseye and Kingpin are **not** an example of this. They are not
alternatives within one scenario: Kingpin is his own scenario and the
Fear No Evil campaign's final encounter. A villain choice is a choice
*within* a scenario, and only the scenarios listed above offer one.

**One exception, and only one.** `on_the_run` reads *"Put 1 random
[[MARAUDER]] villain into play. Remove the minion with the same title as
the villain … from the game."* There the villain chosen determines which
minion leaves the deck. It is already acknowledged in
`encounter_setup.yaml` with `affects_deck: true`, which is exactly what
that flag is for.

**What Part 1 must therefore do:** key the profile on the scenario, accept
a villain as a way of naming one, and — where a scenario offers a choice —
say so rather than picking silently. Modelling which villains a scenario
can host is only needed once §13.2's villain-stats section is built, and
FNE cannot be tested against until marvelcdb publishes it
(`2026-08-25-card-data-sources.md`).



### 14.11 `prescribed` never meant required, and the label implied it did

The open item in §14.4 — that the `recommended`/`prescribed` split was
drawn from grammar alone and should be checked before being relied on —
was correct to worry, and the label failed the check.

`assess` printed a suffix for `recommended`, `open` and `random` and
**nothing** for `prescribed`, so a prescribed pairing read as required by
omission. Asked to analyse Ebony Maw "with recommended modulars", I went
further and told the user its modulars were "required, not recommended —
there's nothing optional to pick". That was an unverified grammatical
label restated as a rule, which is exactly what §10 exists to stop.

**The primary source does not say required.** Ebony Maw's main scheme
reads: *"Two modular encounter set (Armies of Titan and Black Order)."*
The constraint stated is the **count**; the names sit in parentheses. The
surveyed contents blocks come in only two shapes:

| Shape | Scenarios | States |
| --- | --- | --- |
| `Two modular sets (A and B)` | the large majority | a count, names parenthetical |
| `One modular set (recommended: X)` | Rhino, Klaw, Ultron | the same, with the word printed |

The only difference is that three scenarios say "recommended" aloud.

**And the Rules Reference is against the stronger reading.** `Modular
Encounter Set` (RR p.29) opens by defining them as cards that can be added
to or removed from nearly any scenario, and says that *depending on the
scenario* some are required while others are chosen. So a required
category does exist — but nothing in these contents blocks marks which
sets fall in it, and the parse cannot tell.

`prescribed` therefore means **"named by the scenario"**, not "required",
and now prints that way. The honest reading of the data is that the count
is the hard constraint and the named sets are the box's default pairing.


### 14.12 Half the scenarios were assessed without a required modular set

§14.11 corrected the *label*. The user then supplied the rule the label
should have encoded: **a modular set named inside parentheses is the
suggestion; one named outside them is required.**

Checked against the contents blocks, the rule holds exactly, and
`Taskmaster` is its own proof: *"Taskmaster, Hydra Patrol, and Standard
encounter sets. One modular encounter set (Weapon Master)."* Hydra Patrol
is required there and **parenthetical for Absorbing Man** — the same set,
required in one scenario and suggested in another, distinguished by
nothing but the brackets.

`MODULAR_NAMED_RE` only ever captured the parenthetical clause, so every
set named outside it was dropped. **26 of 53 scenarios were assessed
against an encounter deck missing a required set**, between 2 and 14 cards
each. Taskmaster ran 30 cards instead of 38, Crossbones 37 instead of 41,
Unus 23 instead of 30. Deck size, boost mean, keyword counts, minion and
side-scheme totals and every `--deck` cross-reference were wrong for half
the scenarios in the game.

`required_modulars()` now reads the non-parenthetical portion and stores
those sets under a `required` kind. `assess` includes them, and
`--modular` substitutes for the *suggestion* only — a required set cannot
be dropped by passing a different list.

**One trap, found by the fix producing a wrong answer.** `Taskmaster`,
`Thunderbolts` and `Enchantress` each name **both a villain set and a
modular set**. The first pass pulled the Taskmaster modular set into the
Taskmaster scenario because the contents line names the villain set. The
parse now excludes the scenario's own set name. This is the §10.5 shape
again: the query was right and the population admitted a card that could
not belong.

#### Name collisions, fixed

The residual noted above was not a one-off. **Four names belong to both a
playable hero and a villain scenario** — Black Widow, Magneto, Nebula and
Venom — and two more (Taskmaster, Thunderbolts, plus Enchantress) name
both a villain set and a modular set.

`resolve` ran `SELECT code FROM sets WHERE code = ? OR lower(name) =
lower(?)` and took `fetchone()` with no ordering, so which row won was
arbitrary. `Magneto` and `Nebula` happened to land on the scenario;
`Venom` reached the hero pack and `Black Widow` the nemesis set, and both
replied that the scenario was not a scenario.

Resolution now orders by exact code first — someone typing `vnm` means
`vnm` — then by whether the set has a main scheme, which is what makes a
set a scenario. All four names now resolve to their scenario, and the
component codes still reach the message naming the scenarios that face
them.


### 14.13 The name collisions are 18, not 4, and `villain` is not the test

§14.12 fixed four hero/villain name collisions. The user asked whether
Civil War and Synthezoid Smackdown had been checked, and whether the
source data already separates hero packs from encounters. Both questions
found something.

**The collision space is 18 set names, in five shapes:**

| Shape | Names |
| --- | --- |
| hero ↔ villain | Black Widow, Magneto, Nebula, Venom |
| hero ↔ leader | Iron Man, Vision, She-Hulk, Captain America, Captain Marvel |
| villain ↔ modular | Taskmaster, Thunderbolts, Enchantress, Wrecking Crew |
| hero ↔ modular | Spider-Man, Maria Hill |
| scenario ↔ scenario | **Registration, Resistance** |

Only the first row had been looked at.

**The data does separate them, and `card_set_type_code` is still the wrong
test.** It carries hero (69), villain (58), nemesis (69), modular (159),
leader (6) and main_scheme (4). But **Civil War and Synthezoid Smackdown
contain no villain**: their sets are typed `main_scheme`, and their
opposition is a `leader` set named after a hero. Keying "is a scenario" on
`card_set_type_code = 'villain'` would drop all four. Having a main scheme
remains the right test — it is what the type field cannot express.

**These scenarios are not competitive-only, and calling them "PvP" was
wrong.** Their own setup text reads *"In competitive mode…"* and *"In
cooperative mode…"*: both modes are printed on the scenario, and the two
differ in which side scheme is revealed at setup. The leader is the
opposition in **either** mode, so nothing about the resolution or the
stage display depends on which is being played — but the earlier framing
described half of what these sets are.

One thing does depend on it: **setup**. Competitive reveals the
`Choosing Sides` side scheme, cooperative reveals the chosen leader's own.
Which is faced is a choice no decklist carries and no card field infers,
so `assess` states it as a caveat rather than silently counting one of
them.

**`Registration` and `Resistance` are genuinely ambiguous.** Civil War's
`registration` (16 cards) and Synthezoid Smackdown's
`synthezoid_registration` (4) share a name *and* a type, so no ordering
separates them and the alphabetical tie-break was silently assessing Civil
War. `resolve` now reports the ambiguity and names both codes, the same
way `card show` refuses to guess between a hero face and an ally (§8).

**A leader IS the villain of its scenario.** The first pass treated a
leader set as a component to be routed around. It is not: the `leader`
cards carry **stages I–IV, hit points per hero, ATK and SCH** exactly as a
villain's do, and the table plays against them. What a leader set lacks is
a main scheme, which the PvP scenario supplies.

Two consequences. `encounter` filtered its stage line to
`type_code = 'villain'`, so a leader set printed its contents with **no
stat line at all for the card being fought**; it now prints "Leader
stages". And `assess` now names the working invocation —
`assess registration --modular iron_man_leader` — rather than only
explaining what a leader is not.

Finally, when a name was ambiguous and the chosen set is not a scenario,
the error now names the other candidates. `Iron Man` reporting only on
`iron_man` looked like missing data rather than a choice between a hero
set and a leader set.


### 14.14 Open: the main scheme's target threat is not in the schema

`assess` now reports the villain ladder, deck density and the deck's
acceleration icons, but **not the main scheme's clock**, because the field
that would carry it has not been identified.

`Main Scheme, Main Scheme Deck` (RR p.27) names two numbers: the
**acceleration field**, which is the threat placed during step one of
every villain phase, and the **target threat value**, which completes the
stage when reached. Checked against Rhino and Klaw, the indexed columns
map as `base_threat` = starting threat (0, fixed on both) and
`escalation_threat` = the per-phase acceleration (1). **Neither is the
target threat value**, and no column obviously holds it — the A-side rows
carry nothing at all.

Until that is settled the clock is not reported. A "threat to complete"
figure taken from the wrong column would be exactly the kind of
confidently sourced wrong number §10.15 exists to stop, and target threat
is the number a player most wants when judging whether a scenario can be
out-thwarted.

Worth checking against a printed card image before modelling: the target
threat may be a per-hero value printed only on the scheme art, in which
case marvelsdb may not carry it at all.
