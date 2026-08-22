# mc-jarvis — state of play, 2026-08-22

**Tasks 1–15 of the Phase 1 plan are complete, committed, and green.**

    223 tests passing (176 unit + 47 integration)
    4,379 cards · 69 identities · 287 rules entries · 1,180 card-rules links
    unmapped_glyphs: empty

## Try it

    mc-jarvis init          # from nothing: card data + rulebooks + index
    mc-jarvis status
    mc-jarvis update

`init` needs no browser — the rules manifest comes from archive.org. It
warns when that capture is behind FFG, because `update` re-reads the same
capture and cannot cure it.

Working: `doctor`, `init`, `update`, `status`, `card search`, `card show`,
`identity` / `hero`, `encounter`, `rules show`, `rules search`. All take
`--json`.

## What is left

| Task | State |
|---|---|
| 16 `SKILL.md` + `install-skill` | not started — `SKILL.md` is still a placeholder |
| 17 timing reference | not started — findings below, config not yet written |
| 18 designer rulings | design only, deliberately unscheduled |

**Do 17 before 16.** Task 16 *is* `SKILL.md`, so writing it before `timing`
exists means writing it twice.

## Task 17: four corrections to the plan, verified against real data

Found 2026-08-22 while preparing the task. None is implemented yet.

1. **The Round Overview yields 9 steps, not 10.** Step 10 — *"End the round.
   Proceed to step one of the next game round."* — has no `See:` clause, so
   the plan's regex skips it entirely. `see` must be optional, and the
   plan's `assert all(s["see"] for s in steps)` is wrong: 9 of 10 name
   entries.

2. **Step 6's `see` list wraps across a line and is silently truncated.**
   The body reads `6. Villain and minions activate. See: Activation, Attack\n
   (Enemy Activation), Scheme (Enemy Activation)`. Parsing line-by-line
   captures `Activation, Attack` and drops the rest. Split the whole body on
   `\n(?=\d{1,2}\.\s)` instead. **Assert step 6 resolves to three entries** —
   that is the assertion that catches this, and no fixture would suggest it.

3. **Two page numbers in the plan are stale.** `Ability` is indexed at p.4
   (plan says 5) and `First Player` at p.19 (plan says 20). Rather than
   correct them, drop `rr_page` from `timing.yaml` and read the page from
   `rules_entries`. That kills the whole drift class and keeps
   `mc-jarvis timing` agreeing with `rules show Ability`. All 11 cited
   entries have a non-NULL page; 46 rows in the table do not, so
   `verify_citations` needs a guard that names a NULL rather than emitting
   `p.None`.

4. **Two latent bugs in the plan's `timing.py` draft.** `parse_chart`'s
   `len(...) < 90` wrap guard never fires on today's chart — untested logic.
   And `explain()` filters on `and r["sub"]`, which excludes every
   un-lettered rung, so rung 1 (constant/delayed/lasting) and rung 5
   (consequential damage) never appear — contradicting what the plan's own
   `SKILL.md` text promises.

Confirmed present and correct: the chart parses out of the `ABILITY` body
exactly as the plan describes, and all eight cited RR entries resolve.

## Also landed this session

**`docs/superpowers/specs/2026-08-22-scenario-assessment-design.md`** — the
`assess` feature (villain + modular sets → threat profile, then deck
cross-reference). Captured deliberately ahead of implementation; revisit
after 15–17. Part 1 is plannable now, Part 2 is gated on the unwritten deck
pipeline.

## Corrections this session made to the plan

- **Glyph mapping must run after chunking, not before.** The plan's draft
  `init.py` had it backwards. Measured on the real Rules Reference: 13 of
  217 entries stored as `Icon ([amplify])` instead of
  `Amplify Icon ([amplify])`, and 0 derived glyph names instead of 13. The
  entry count is identical either way, so nothing raises.
- **Both PDF backends agree** — 71 pages, 13 codepoints, 217 index entries,
  46 redirects from `pdftotext` and `pypdf` alike — so no backend is pinned.
- `scripts/rebuild.py` is gone; `mc-jarvis update` replaces it.

## Stale bookkeeping still to fix

- The plan's checkboxes are all unticked; it records no progress.
- The plan's **Done criteria carry superseded numbers** — "~4,298 cards, 72
  identities", "the setup audit reports exactly four identities". Real data
  gives 4,379 / 69 / **eight**. They will fail as written.
