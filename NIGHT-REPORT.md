# mc-jarvis — overnight run, 2026-08-22

**Tasks 1–10 of the Phase 1 plan are complete, committed, and green.**
The loop stopped at the planned boundary, not on an error.

    104 tests passing (86 unit + 18 integration)
    4,379 cards indexed · 69 identities · 265 out-of-deck rows
    1,053 cost-arrow clauses parsed

## Try it

    uv run --extra dev python -c "from mc_jarvis.cli import main; main(['card','search','web','--limit','5'])"

Working commands: `doctor`, `card search`, `card show`, `identity` / `hero`,
`encounter`. Every one takes `--json`.

    card search "Sp//dr"                 punctuation is not FTS syntax
    card show "Black Panther"            lists candidates, never guesses
    card show "First Aid"                shows printings: core x3, ant x2, nebu x2
    identity Ironheart                   six faces, hand size 4 -> 5 -> 6
    encounter Rhino                      stages I/II/III, HP per hero

`scripts/rebuild.py` rebuilds the index; `mc-jarvis init` lands in Task 15.

## Why it stopped

**Task 11 needs you.** The FFG product page returns 403 to every HTTP
client, so the rules manifest cannot be fetched without a real browser.
Save the page to `/tmp/ffg.html` and Tasks 11–17 can run:

    https://www.fantasyflightgames.com/en/products/marvel-champions-the-card-game/

Task 11 is also flagged in the plan as its least-verified component: its
fixture is built from an assumption about the page markup, and the plan
says to look at the real page **before** writing the parser.

## Findings — seven corrections to the spec

Each was caught by a real-data gate, not by a unit test, and each is
recorded in the plan.

1. **`duplicate_of` is inverted in §8.** The spec says it is encounter-only
   and no player card uses it. 341 of 351 stubs resolve to *player* cards,
   211 to `basic`. They are hero-pack reprints, and this is how player-side
   reprints are marked. Unresolved they are 351 nameless rows.

2. **"Own any pack containing a card and you have enough copies" is false.**
   50 printings ship fewer than the deck limit — Ant-Man has 2 *First Aid*
   against a limit of 3. The grouped form holds (0 violations). `--owned`
   must resolve through `canonical_code`.

3. **§10's Sp//dr ordering constraint does not exist.** Under RR p.45 her
   hero face and permanent support do not match at all — clause 1 needs
   *both* cards to lack an alter-ego title. It is an artifact of name-equality
   matching, which §8 warns against three paragraphs earlier.

4. **The cost-arrow parse was silently broken.** Real markup puts the colon
   outside the bold span (`<b>Interrupt</b>: When …`). Timing extraction
   was **24 clauses where 281 belong** — ~260 cards would have reported
   their trigger as something the player must pay.

5. **Audit coverage must be acknowledged, not inferred.** A hero with both
   a permanent card and an unmarked set-aside card was silently passed.
   Real data hid this; a fixture caught it. All eight flagged identities
   are now listed explicitly, each reason re-verified at build time.

6. **"Player-legal" is not `faction_code != 'encounter'`.** That counts
   2,154 cards against §16's 1,607; `campaign` is not deck-legal.
   `index.PLAYER_FACTIONS` names the seven that are.

7. **Villains do not thwart.** They carry `scheme`, a roman-numeral
   `stage`, and `health_per_hero` — the printed 14/15/16 is multiplied by
   the player count. Printing it without saying so gives the wrong tracker
   value.

## The pattern worth noticing

Findings 4 and 5 are the same failure: **a fixture shaped from my
assumption, and a test written to match the fixture.** Both passed while
the feature was wrong. The plan now carries a Global Constraint requiring
fixtures to be shaped from observed data, and every data-shaped task to
end with a real-data gate that has a number you can fail.

## Also fixed in the plan

- `_bundled/` was referenced by three modules but created by no task — the
  package would not have built at Task 1.
- argparse does *not* normalise subcommand aliases; `hero` needed an
  explicit table.
- Schema changes now bump `SCHEMA_VERSION`, which drops and rebuilds the
  derived index instead of failing with a bare "no such column".
