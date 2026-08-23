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
  a modelled fact.
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

**15 deck-eligible cards belong to the infinity stone deck alone**, and
they are detectable: their text says `Place this card in the
[[infinity stone]] deck`. The `infinity_gauntlet` modular is the sharpest
case in the corpus — **7 cards, none of them in the encounter deck**: the
Gauntlet attaches at setup, and the six Stones are their own deck. A
scenario including that modular would gain 7 phantom encounter cards, a
100% error for that set's contribution.

**Data-source bound.** The user played a Bullseye scenario online, and
`Adamantium-Lace Spines` appears nowhere in the corpus. Bullseye exists
only as a **minion**, in `dangerous_recruits` and `daredevil_nemesis`.
marvelcdb — current here to 2026-08-21 — carries no Bullseye villain set.
DragnCards keeps its own database and carries content marvelcdb does not,
so `assess` coverage is bounded by marvelcdb's, and a scenario a player
has actually played may simply be absent. `assess` must say so plainly
rather than report a partial deck.

**Revised detection order**, replacing §14.2's two-step:

1. `type_code` — `villain` and `main_scheme` are never in the deck; the
   player-side types (§14.2) are never in it either.
2. `Setup` keyword in the card's own text → `starts_in_play` /
   `setup_attachment`. 13 cards, free.
3. `Place this card in the [[X]] deck` → `other_deck`. 15+ cards, free.
4. The scenario's `Setup` prose → the residue, per scenario, acknowledged
   in config and gated. 33 of 56 scenarios need one.
5. Anything left → `deck`.

Steps 2 and 3 are new and cost nothing. They do not remove the need for
step 4, but they shrink it and they catch the two worst cases in the
corpus.

