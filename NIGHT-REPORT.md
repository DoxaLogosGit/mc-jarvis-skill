# mc-jarvis — state of play, 2026-08-22

**Tasks 1–15 and 17 of the Phase 1 plan are complete, committed, and green.**

    280 tests passing — against a v1.8 index. On the v1.7 index `init`
    actually produces, two integration tests fail honestly (see below).
    4,379 cards · 69 identities · 287 rules entries (216 resolve) · 1,180
    card-rules links · 4,588 timing triggers
    unmapped_glyphs: empty · unclassified prefixes: none

## Try it

    mc-jarvis init          # from nothing: card data + rulebooks + index
    mc-jarvis status
    mc-jarvis update

    mc-jarvis timing                    # the priority chart, with cites
    mc-jarvis timing "When Defeated"    # -> Forced Interrupt, rung 2b
    mc-jarvis timing --round            # the ten steps of a game round

`init` needs no browser — the rules manifest comes from archive.org. It
warns when that capture is behind FFG, because `update` re-reads the same
capture and cannot cure it.

Working: `doctor`, `init`, `update`, `status`, `card search`, `card show`,
`identity` / `hero`, `encounter`, `rules show`, `rules search`, `timing`.
All take `--json`.

## What is left

| Task | State |
|---|---|
| 16 `SKILL.md` + `install-skill` | not started — `SKILL.md` is still a placeholder |
| 18 designer rulings | design only, deliberately unscheduled |

Task 16 is now the only thing between this and the Phase 1 done criteria.
The timing section it must carry is drafted at the end of Task 17 in the
plan, already corrected for what the real data changed.

## Task 17 landed, and the real corpus rewrote nine parts of it

The plan's draft is kept in place for its reasoning; the nine corrections
are recorded under **"What the real corpus changed"** in Task 17. The ones
that would have produced wrong answers at a table:

- **A quoted trigger is a reference, not a trigger** (RR, ABILITY). The
  draft stripped the quotes, giving 15 printings an ability they do not
  have.
- **`explain` never showed rungs 1 or 5**, so "constant abilities beat
  every trigger" — the thing players get wrong — went unsaid. Naively
  fixing it instead reports the bare `Interrupts`/`Responses` headers, so
  a Response "resolves after Responses". Only eight slots order.
- **`Forced Action` (11 cards) classified as nothing**, because `Forced`
  was modelled as a prefix rather than a modifier.
- **`When Revealed (Norman Osborn)` was dropped** by a fixed list of
  allowed parentheticals.
- **Pages were hard-coded and two were wrong** — `Ability` is p.4, not
  p.5; `First Player` is p.19, not p.20. No page number lives in
  `timing.yaml` any more.

- **The prefix-length cutoff hid a real trigger.** `len(prefix) > 40`
  dropped bold spans without classifying or counting them, so no gate
  could report what it hid. Measured: 113 rows above the line, 112 of
  them prose bolded for emphasis, and one a genuine `Forced Response` —
  21147 Hela's Crown prints `<b>Forced Response<b>:`, an opening tag
  where a closing one belongs, so the span swallowed the card's `Boost`
  trigger too. The cutoff is now config with its measurement recorded
  (longest classifying span 29 chars, shortest bolded sentence 41), and a
  test re-measures both ends.

Two bugs outside the task, both surfaced by running `update` a **second**
time — the first run passed:

- `timing_triggers` carried the schema's only foreign key to `cards`, and
  `load_cards` truncates `cards`.
- `_reset_if_stale` could not drop through a foreign key either, so a
  schema bump aborted half-done — the one state it exists to prevent.

## Bookkeeping corrected

- The plan's **Done criteria** carried spec-era numbers that would have
  failed as written (~4,298 cards, 72 identities, "exactly four
  identities"). Now 4,379 / 69 / **eight**, with the originals kept in
  brackets, and the met ones ticked.
- Task 17's steps are ticked; earlier tasks' checkboxes are still unticked.
- **The 287 in this report was right; my "correction" to 263 was wrong**
  and is reverted. 287 is a complete index: 263 Rules Reference rows plus
  24 page-chunks of Learn to Play. 263 was this machine missing a
  rulebook.
- `mc-jarvis status` now prints `rules_resolved`, `rr_version`, and the
  rulebooks actually indexed, and names a missing one. The total on its
  own said nothing about either.

## The audit found a wrong-answer bug — read this first

`init` from an empty directory fetches **two** rulebooks and gives **v1.7**
of the Rules Reference. The development directory had one rulebook and
**v1.8**, placed by hand, and had never completed an `init` — it has no
`manifest.json`. Everything in Task 17 was built and gated against an
edition no user's `init` produces.

The two editions disagree on the rules, not just the layout. v1.7 lists
eight flat rungs and puts **"When Defeated" on rung 5 beside Boost**; v1.8
lists five rungs with lettered tiers and makes it a **Forced Interrupt at
2b**. So on a real user's index, `mc-jarvis timing "When Defeated"` gave
the v1.8 answer and **cited the user's own rulebook for it**.

`verify_chart` and `verify_citations` caught it, and `init` and `status`
both reported it. `timing` answered anyway. It now refuses when its own
verification fails, names the mismatch and the indexed version, and points
at `rules show Ability`. `--round` still works.

**Open:** the timing config is v1.8-only. Supporting v1.7 means keying
`expected_chart`, `aliases` and the rung mapping by version —
`build_meta.rr_version` now records which one the index holds.

## Earlier work still standing

**`docs/superpowers/specs/2026-08-22-scenario-assessment-design.md`** — the
`assess` feature (villain + modular sets → threat profile, then deck
cross-reference). Part 1 is plannable now; Part 2 is gated on the unwritten
deck pipeline.

- **Glyph mapping must run after chunking, not before.** Measured: 13 of
  217 entries otherwise stored as `Icon ([amplify])`, and 0 derived glyph
  names instead of 13. The entry count is identical either way, so nothing
  raises.
- **Both PDF backends agree** — 71 pages, 13 codepoints, 217 index
  entries, 46 redirects — so no backend is pinned.
- `scripts/rebuild.py` is gone; `mc-jarvis update` replaces it.
