# Record: scenario depth, written decks, and the pre-live battery

> **This is a record, not a forward plan.** Everything below is built,
> tested and on `main`. It is written in the shape of the other plans'
> findings sections so the plan directory stops being two weeks behind
> the specs. The reasoning lives in the spec sections cited; this is an
> index with the constraint that shaped each piece.

Covers 2026-08-28 to 2026-09-09, commits `f896a73`..`34286409676`.

## Why there was no plan

The work came from a conversation rather than a spec: the user asked a
question, the answer exposed something the tool got wrong, and the fix
went in with its spec section. That is a good loop, and it produced eight
corrections that a plan would not have predicted — but it left the plan
directory describing an older tool. Both are recorded here.

## What was built

| piece | spec | shaped by |
| --- | --- | --- |
| Target threat, the clock a scenario is raced against | assess §14.14 | it was in the payload all along; only the indexed columns had been checked |
| A second losing condition, and what mechanism it counts | §14.15 | 16 of 26 are printed outside the encounter deck |
| Whether that card can be removed at all | §14.16 | printed vs granted permanence; one card in the pool grants it |
| A nemesis set belongs to a player, not a scenario | §14.17 | `card_set_type_code` types all 69; `--modular` accepted them |
| What can pull a nemesis set into play, and whether it is on a timer | §14.18 | Standard I/II carry one treachery; Standard III counts to players + 3 |
| Deck exhaustion measured and *not* built; reset acceleration reported | §14.19 | one card in the pool changes what a reset does |
| A name that matches cards but no scenario says so | §14.20 | `assess kingpin` claimed absence for six cards that exist |
| The pre-live battery | §14.21, §14.22 | the defects were all on the input side |
| A roster of villains is not a list of alternates | §14.23 | five relationships, none derivable from a name count |
| Decks written by hand, and pasted on stdin | design §10.17 | 93 names collide; the ladder takes it to 10 |
| Ripgrep measured and declined | design §10.18 | 18ms over the whole card pool |

## The corrections, because they are the point

Each of these was wrong in a way that looked right:

1. **"Target threat is not in the schema"** — checked the indexed columns
   and stopped. It is `threat` in the raw payload, on 129 of 246 main
   schemes.
2. **"You face one, not all"** — said of every set naming more than one
   villain, so Four Horsemen players were told they fought one of four.
3. **Wrecking Crew reported no opposition at all** — its four villains are
   four separate sets. The population error again, and the only silent one.
4. **A/B villain stages read as a ladder** — they are one set of stages per
   difficulty, so the printed opposition was doubled.
5. **`--modular` accepted any string** — a typo was named in the header and
   assessed as nothing.
6. **`timing "when revealed"` refused** a trigger the chart names at rung 3.
7. **The aspect filter dropped the playing hero's own signature card** —
   Rogue's Gambit silently became the generic ally.
8. **A hero name shared by two heroes took the first row** — T'Challa decks
   resolved against Shuri's signature set.

Six of the eight were found by a test written to look for them: the
corpus round-trip (§10.17) and the command sweep over `SKILL.md` (§14.22).
The other two came from the user naming a scenario the output described
wrongly.

## Gates added

`assess.opposition_gate` — any scenario naming more than one villain with
no `opposition` config entry, because the default reading was the wrong
one. Joins the five gates the assess plan already required.

## Still open after this pass

- **Heroic levels, campaign mode, the three `Chief … Officer`
  environments** — unchanged, and still recorded in the assess plan.
- **A declared-`size` coverage check** — `2026-08-25-card-data-sources.md`
  says it "should be built regardless" and needs no second source. The
  `packs` table carries only `code` and `name`, so the check cannot be
  written without indexing the declared size. The `assess kingpin`
  message improved without it, and is the weaker version: it names the
  sets a card lives in but cannot say "68 of a declared 276".
- **The live integration test** — the user's, and the reason the battery
  in §14.22 exists.
