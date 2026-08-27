# `mc-jarvis assess` Part 1 — Threat Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mc-jarvis assess <villain>` reports what a scenario's encounter deck actually contains — composition, boost curve, minion and treachery profile, scheme pressure — as facts with the cards behind every number.

**Architecture:** Build-time classification is separated from query-time aggregation, exactly as `cardtext.py` is separate from `cards.py`. `encounterdeck.py` decides, per card, whether it is in the encounter deck at all — the denominator of every number this feature reports. `assess.py` assembles a scenario from that classification and aggregates it. Both the deck-membership residue and the scenario→modular mapping are **parsed from the card data first** and config holds only what the data cannot give, gated in both directions — the `timing.yaml` pattern.

**Tech Stack:** Python 3.10+, SQLite with FTS5, PyYAML, pypdf. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-22-scenario-assessment-design.md`

> **Read §14 first.** The spec's working pass (2026-08-23) **supersedes §4.7 and §5.2**, and corrects §5's worked example. §14.1–§14.9 carry the measured findings. Where §14 and an earlier section disagree, §14 is right — it has numbers.

**Out of scope:** Part 2 (§9, `--deck` cross-reference). It needs `deck fetch` / `deck check`, which do not exist. Do not begin it.

## Global Constraints

- **The repository ships code and configuration only.** No card text, no rules text, no PDFs, no built index. Everything copyrighted is fetched to the user's machine at `init`.
- **Every leaf command takes `--json`.** Added by `cli._leaf`; do not add it by hand.
- **Shape every fixture from observed data, never from an assumption about it.** The spec's own §5 example was an assumption and was wrong.
- **A task's real-data check is a gate, not a closing flourish.** "Expected: a small number" is not a threshold. Every gate names a number that can fail.
- **A negative result about text is only as strong as the variants tried**, and must be reported with the variants listed. §14.7 records two wrong conclusions that came from searching one spelling.
- **Every mean is quantity-weighted** (§4.5). The unweighted form is not offered; there is no question it answers.
- **`assess` reports facts, never card recommendations** (§3). Judgement lives above the CLI line, in `SKILL.md`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/mc_jarvis/schema.py` | Extended with §4.1's columns, `encounter_role`, `scenario_modulars`. Bumps `SCHEMA_VERSION`. |
| `src/mc_jarvis/index.py` | `COLUMNS` gains the new card fields; the `boost` invariant gate. |
| `src/mc_jarvis/encounterdeck.py` | **Build-time.** Per-card encounter-deck role, the set-aside audit, and the scenario→modular parse. Mirrors `outofdeck.py`. |
| `src/mc_jarvis/assess.py` | **Query-time.** Assemble a scenario, aggregate, emit. Mirrors `cards.py`. |
| `config/encounter_setup.yaml` | Acknowledged set-aside cards the data does not name, each with the sentence that justifies it, re-verified at build time. |
| `config/scenarios.yaml` | Only the residue of the `Contents` parse: sets with no block, the one upstream typo, unresolvable names. |
| `tests/test_encounterdeck.py`, `tests/test_assess.py` | |

`encounterdeck.py` holds both the role classification and the modular parse because both are build-time enrichment reading the same card text, and both feed one table set. They change together.

---

## Task 1: Card columns and the boost invariant

Implements §4.1 and §4.3, with §14.3's correction.

**Files:**
- Modify: `src/mc_jarvis/index.py` (`COLUMNS`, `SCHEMA_VERSION`), `src/mc_jarvis/schema.py`
- Test: `tests/test_index.py`

**Interfaces:**
- Produces: `cards.boost`, `cards.boost_star`, `cards.base_threat`, `cards.base_threat_fixed`, `cards.escalation_threat`, `cards.escalation_threat_fixed`, `cards.scheme_acceleration`, `cards.scheme_amplify`, `cards.scheme_crisis`, `cards.scheme_hazard`, `cards.hidden`, `cards.attack_star`, `cards.scheme_star` — all nullable INTEGER except the `_star` family, which is INTEGER 0/1.
- Produces: `index.assert_boost_invariant(rows: list[dict]) -> None`, raising `index.InvariantError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_index.py — append
def test_boost_invariant_rejects_an_explicit_zero():
    """§4.3: no card in the corpus has boost 0, so `absent` reads as zero
    boost icons. If upstream ever emits an explicit 0 the reading has
    changed and two encodings are being mixed."""
    with pytest.raises(index.InvariantError, match="boost"):
        index.assert_boost_invariant([{"code": "x1", "name": "X", "boost": 0}])


def test_boost_invariant_rejects_a_value_outside_one_to_four():
    """§14.3 measured the range: 1-4, never 0, never null. A 5 means the
    scale changed."""
    with pytest.raises(index.InvariantError, match="boost"):
        index.assert_boost_invariant([{"code": "x1", "name": "X", "boost": 7}])


def test_boost_invariant_accepts_absent_and_one_to_four():
    index.assert_boost_invariant([
        {"code": "a", "name": "A"},                 # absent
        {"code": "b", "name": "B", "boost": None},  # explicit null
        {"code": "c", "name": "C", "boost": 1},
        {"code": "d", "name": "D", "boost": 4},
    ])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_index.py -k boost_invariant -v`
Expected: FAIL — `AttributeError: module 'mc_jarvis.index' has no attribute 'assert_boost_invariant'`

- [ ] **Step 3: Add the columns to `schema.py`**

In the `CREATE TABLE IF NOT EXISTS cards (…)` block, after `scheme`:

```sql
    -- Encounter-side numbers (spec §4.1). None of these was indexed
    -- before; `assess` is their first consumer.
    boost                   INTEGER,
    base_threat             INTEGER,
    escalation_threat       INTEGER,
    scheme_acceleration     INTEGER,
    scheme_amplify          INTEGER,
    scheme_crisis           INTEGER,
    scheme_hazard           INTEGER,
    hidden                  INTEGER,
    -- `*_fixed` means "does not scale with player count" (§4.6).
    -- Applying per-hero scaling to a fixed-threat scheme is the same
    -- error as printing raw villain HP.
    base_threat_fixed       INTEGER,
    escalation_threat_fixed INTEGER,
    -- The `*_star` family is a FLAG, never a value (§4.4, §14.3):
    -- eleven fields, all boolean. 134 cards carry both `boost` and
    -- `boost_star`, so the star is an extra icon with a card-specific
    -- effect, not a replacement. It never enters a numeric mean.
    boost_star              INTEGER,
    attack_star             INTEGER,
    scheme_star             INTEGER,
```

- [ ] **Step 4: Add the columns to `index.COLUMNS`**

```python
COLUMNS = (
    "code name subname type_code faction_code pack_code set_code back_link "
    "double_sided is_unique permanent duplicate_of cost quantity "
    "resource_physical resource_mental resource_energy resource_wild "
    "attack thwart defense recover health health_per_hero scheme "
    "stage hand_size text flavor traits "
    "boost base_threat escalation_threat scheme_acceleration scheme_amplify "
    "scheme_crisis scheme_hazard hidden base_threat_fixed "
    "escalation_threat_fixed boost_star attack_star scheme_star"
).split()
```

- [ ] **Step 5: Write the invariant and call it**

In `index.py`, beside `_assert_copy_invariant`:

```python
def assert_boost_invariant(rows: list[dict]) -> None:
    """`boost` is absent or 1-4 (§4.3, measured again in §14.3).

    Two assertions, not one. An explicit 0 means upstream started using a
    different encoding for "no boost icons" and the corpus now mixes two.
    A value outside 1-4 means the printed scale changed. Either way the
    quantity-weighted mean silently stops meaning what it says.
    """
    bad = [r for r in rows
           if r.get("boost") is not None and r["boost"] not in (1, 2, 3, 4)]
    if bad:
        raise InvariantError(
            f"{len(bad)} cards have a boost value outside 1-4: "
            f"{[(r['code'], r.get('boost')) for r in bad[:5]]}. "
            f"`absent means zero` is no longer a safe reading.")
```

In `load_cards`, immediately after `_assert_copy_invariant(rows)`:

```python
    assert_boost_invariant(rows)
```

Bump `SCHEMA_VERSION` from 14 to 15.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_index.py -v`
Expected: PASS

- [ ] **Step 7: Rebuild and gate against the real corpus**

```bash
uv run mc-jarvis update
uv run python -c "
from mc_jarvis import index, paths
conn = index.connect(paths.db_path())
n = conn.execute('SELECT COUNT(*) FROM cards WHERE boost IS NOT NULL').fetchone()[0]
print('cards with a boost value:', n)
for r in conn.execute('SELECT boost, COUNT(*) n FROM cards WHERE boost IS NOT NULL GROUP BY boost ORDER BY boost'):
    print(f'   boost {r[\"boost\"]}: {r[\"n\"]}')
print('boost_star:', conn.execute('SELECT COUNT(*) FROM cards WHERE boost_star=1').fetchone()[0])
print('both boost and star:', conn.execute('SELECT COUNT(*) FROM cards WHERE boost IS NOT NULL AND boost_star=1').fetchone()[0])
"
```

**Gate.** Measured 2026-08-23: **1,244** cards carry `boost` — 2:560, 1:353, 3:312, 4:19 — and **419** carry `boost_star`, of which **134** carry both. If the distribution has moved, find out why before continuing; it is the denominator of the headline statistic.

- [ ] **Step 8: Commit**

```bash
git add src/mc_jarvis/schema.py src/mc_jarvis/index.py tests/test_index.py
git commit -m "feat: index the encounter-side card fields, with the boost invariant"
```

---

## Task 2: Encounter-deck role classification

Implements §5.2 **as corrected by §14.5, §14.6, §14.7 and §14.8**. This is the denominator of every number the feature reports.

**Files:**
- Create: `src/mc_jarvis/encounterdeck.py`
- Modify: `src/mc_jarvis/schema.py`
- Test: `tests/test_encounterdeck.py`

**Interfaces:**
- Produces:
  - `encounterdeck.Role` — `str` constants: `DECK`, `STARTS_IN_PLAY`, `SETUP_ATTACHMENT`, `SET_ASIDE`, `OTHER_DECK`, `NOT_ENCOUNTER`
  - `encounterdeck.DECK_TYPES: tuple[str, ...]`
  - `encounterdeck.classify_card(row: dict) -> tuple[str, bool]` — returns `(role, returns_to_deck)`
  - `encounterdeck.set_aside_groups(rows: list[dict]) -> dict[tuple[str, str], set[str]]`
  - `encounterdeck.build(conn) -> dict[str, int]`

### Why the order matters

§14.2 first concluded no signal existed, then §14.5 and §14.7 found three. Both wrong conclusions came from searching one spelling. The rules below are in **decreasing confidence**, and each names the measurement behind it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_encounterdeck.py
import pytest

from mc_jarvis import encounterdeck as ed


def _card(**kw):
    base = {"code": "x", "name": "X", "type_code": "treachery", "traits": "",
            "text": "", "permanent": None, "boost": None, "quantity": 1,
            "set_code": "s"}
    base.update(kw)
    return base


# --- the type rule ---------------------------------------------------

def test_villains_and_main_schemes_are_never_in_the_deck():
    for t in ("villain", "main_scheme"):
        role, _ = ed.classify_card(_card(type_code=t))
        assert role == ed.STARTS_IN_PLAY, t


def test_player_side_types_in_encounter_sets_are_not_encounter_cards():
    """§14.2: every encounter-set `ally` is a rescued-captive type that
    enters play FOR the players via a side scheme. `upgrade`, `event`,
    `support` and `resource` in encounter sets are campaign rewards."""
    for t in ("ally", "upgrade", "event", "support", "resource",
              "player_side_scheme"):
        role, _ = ed.classify_card(_card(type_code=t))
        assert role == ed.NOT_ENCOUNTER, t


def test_an_ordinary_treachery_is_in_the_deck():
    role, returns = ed.classify_card(_card(type_code="treachery", boost=2))
    assert role == ed.DECK
    assert returns is True


# --- separate decks (§14.5) ------------------------------------------

def test_a_card_belonging_to_another_deck_is_not_in_the_encounter_deck():
    """The `infinity_gauntlet` modular is 7 cards and NONE of them is in
    the encounter deck: the Gauntlet attaches at setup and the six Stones
    are their own deck. Counting them adds 7 phantom cards."""
    role, returns = ed.classify_card(_card(
        type_code="environment", name="Power Stone",
        text="<b>Special:</b> You are stunned. Place this card in the "
             "[[infinity stone]] deck discard pile."))
    assert role == ed.OTHER_DECK
    assert returns is False


# --- Setup + permanent (§14.6) ---------------------------------------

def test_setup_and_permanent_never_returns():
    """`permanent` means "cannot be discarded from play", so a Setup card
    that is also permanent can never reach the discard pile."""
    role, returns = ed.classify_card(_card(
        type_code="attachment", name="Infinity Gauntlet", permanent=1,
        text="Permanent. Setup [star] <b>Forced Response</b>: ..."))
    assert role == ed.SETUP_ATTACHMENT
    assert returns is False


def test_setup_without_permanent_cycles_back_into_the_deck():
    """The three [[Setting]] environments start in play, are discarded
    when another is revealed, and rejoin the deck on reshuffle. Their own
    text proves it: a When Revealed ability and a boost value are both
    meaningless for a card that never enters the encounter deck."""
    role, returns = ed.classify_card(_card(
        type_code="environment", name="The Savage Land", permanent=None,
        boost=3,
        text="Setup. The villain gains retaliate 1. <b>Special</b>: ... "
             "<b>When Revealed</b>: Discard each other [[Setting]] "
             "environment in play."))
    assert role == ed.STARTS_IN_PLAY
    assert returns is True


def test_setup_with_neither_signal_stays_out_but_is_flagged():
    """The three `Chief ... Officer` environments FLIP rather than
    discard, which would keep them out permanently - but "flip" is not
    proof that nothing else discards them, so this is not asserted as
    certain."""
    role, returns = ed.classify_card(_card(
        type_code="environment", name="Chief Medical Officer",
        text="Setup. If there are 4 or more secret counters here, flip "
             "this card. <b>Hero Action</b>: ..."))
    assert role == ed.STARTS_IN_PLAY
    assert returns is False


def test_permanent_alone_does_not_remove_a_card_from_the_deck():
    """§14.5's trap. Enchantress's `Trance of Envy` is permanent AND has a
    When Revealed ability, which only fires on a reveal FROM the encounter
    deck. It is drawn, then stays. Treating `permanent` as "not in the
    deck" removes cards that demonstrably are."""
    role, returns = ed.classify_card(_card(
        type_code="attachment", name="Trance of Envy", permanent=1,
        text="Permanent. Your identity gains the [[Enthralled]] trait. "
             "<b>When Revealed</b>: Discard a card you control."))
    assert role == ed.DECK


def test_boost_alone_does_not_remove_a_card_either():
    """Also §14.5. `Armored Rhino Suit` has no boost and `Charge` has 2,
    which is tempting - but `The Sleeper` is set aside by its scenario and
    carries boost 1. Absence correlates; presence does not exclude."""
    role, _ = ed.classify_card(_card(
        type_code="attachment", name="Armored Rhino Suit",
        text="Attach to Rhino. <b>Forced Interrupt</b>: ..."))
    assert role == ed.DECK


# --- set-aside groups from card text (§14.7) -------------------------

def test_set_aside_groups_are_read_from_the_hyphenated_form():
    """FFG writes the adjective hyphenated. Searching `set aside` finds 5
    cards; `set-aside` finds 91. That single spelling difference is what
    made §14.2 conclude the list was underivable."""
    rows = [
        _card(set_code="apocalypse", name="Heart of the Empire",
              type_code="main_scheme",
              text="The first player reveals a random set-aside "
                   "[[Prelate]] minion."),
        _card(set_code="m.o.d.o.k.", name="Upgrading Adaptoids",
              type_code="main_scheme",
              text="put 1 random set-aside [[Adaptoid]] environment into "
                   "play instead."),
    ]
    groups = ed.set_aside_groups(rows)
    assert groups[("Prelate", "minion")] == {"apocalypse"}
    assert groups[("Adaptoid", "environment")] == {"m.o.d.o.k."}


def test_a_named_card_is_read_as_a_group_of_one():
    rows = [_card(set_code="magneto_villain", name="Sabotage Master Mold",
                  type_code="side_scheme",
                  text="<b>When Defeated</b>: Reveal the set-aside Orbital "
                       "Decay side scheme.")]
    assert ("Orbital Decay", "side_scheme") in ed.set_aside_groups(rows)


def test_the_nemesis_set_aside_area_is_not_a_card_group():
    """`set-aside area for your nemesis` is the nemesis area, not a group.
    Two regex artefacts, named in §14.7."""
    rows = [_card(set_code="standard_iii", name="Pursued by the Past",
                  text="Search the set-aside area for your nemesis side "
                       "scheme and reveal it.")]
    assert ed.set_aside_groups(rows) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_encounterdeck.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.encounterdeck'`

- [ ] **Step 3: Add the table to `schema.py`**

```sql
-- Whether a card is in the encounter deck at all, and whether a card
-- that starts in play later rejoins it (spec §5.2, corrected by §14.6).
-- This is the denominator of every number `assess` reports.
CREATE TABLE IF NOT EXISTS encounter_role (
    code            TEXT PRIMARY KEY,
    role            TEXT NOT NULL,
    -- A card that starts in play can be discarded and reshuffled in. It
    -- belongs in the composition statistics, just not the opening deck.
    returns_to_deck INTEGER NOT NULL DEFAULT 0,
    -- Which rule decided, so a wrong answer can be traced to its rule
    -- rather than guessed at.
    decided_by      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_encounter_role ON encounter_role(role);
```

- [ ] **Step 4: Write `encounterdeck.py`**

```python
"""Encounter-deck membership (spec §5.2, as corrected by §14.5-§14.8).

Set membership is the denominator of every average `assess` reports. Get
it wrong and all the numbers are wrong while looking entirely plausible.

The rules below are in decreasing confidence, and each carries the
measurement behind it. Two earlier attempts concluded no signal existed;
both were wrong, and both times the cause was searching a single spelling.
A negative result about text in this corpus is only as strong as the
variants tried.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict

DECK = "deck"
STARTS_IN_PLAY = "starts_in_play"
SETUP_ATTACHMENT = "setup_attachment"
SET_ASIDE = "set_aside"
OTHER_DECK = "other_deck"
NOT_ENCOUNTER = "not_encounter"

# Types that can be shuffled into an encounter deck.
DECK_TYPES = ("minion", "treachery", "side_scheme", "attachment",
              "environment", "obligation")
# In play from the start; never shuffled in.
IN_PLAY_TYPES = ("villain", "main_scheme")
# Player-side cards that happen to ship in encounter sets: rescued
# captives, campaign rewards. Never in the encounter deck (§14.2).
PLAYER_TYPES = ("ally", "upgrade", "event", "support", "resource",
                "player_side_scheme", "hero", "alter_ego")

# FFG writes "Setup" both as a bold trigger and as a bare sentence
# opener. Matching only `<b>Setup</b>` misses `Setup. Attach to the
# villain.` entirely.
SETUP_RE = re.compile(r"<b>\s*Setup\s*</b>|(?<![A-Za-z])Setup\s*[.\[]", re.I)
WHEN_REVEALED_RE = re.compile(r"<b>\s*(?:Forced\s+)?When Revealed", re.I)
OTHER_DECK_RE = re.compile(r"\[\[([^\]]+)\]\]\s*deck", re.I)
# The adjective, hyphenated. `set aside` (the verb) appears on 5 cards;
# `set-aside` appears on 91.
ASIDE_TRAIT_RE = re.compile(
    r"set-aside\s+\[\[([^\]]+)\]\]\s+"
    r"(minion|environment|ally|attachment|side scheme|treachery)", re.I)
ASIDE_NAMED_RE = re.compile(
    r"set-aside\s+([A-Z][A-Za-z' -]{2,28}?)\s+"
    r"(minion|environment|ally|attachment|side scheme|treachery)")
# "the set-aside area for your nemesis" is the nemesis area, not a group.
NOT_A_GROUP = re.compile(r"^area\b", re.I)


def classify_card(row: dict) -> tuple[str, bool]:
    """One card's role, and whether it can rejoin the encounter deck.

    Returns `(role, returns_to_deck)`. Scenario-specific asides are NOT
    decided here - they depend on which scenario is being played, and
    `build` applies them from `set_aside_groups`.
    """
    kind = row.get("type_code") or ""
    text = row.get("text") or ""

    if kind in IN_PLAY_TYPES:
        return STARTS_IN_PLAY, False
    if kind in PLAYER_TYPES:
        return NOT_ENCOUNTER, False
    if kind not in DECK_TYPES:
        return NOT_ENCOUNTER, False

    # Belongs to a different deck entirely - the infinity stone deck, the
    # invocation deck, and four others (§14.5).
    if OTHER_DECK_RE.search(text):
        return OTHER_DECK, False

    if SETUP_RE.search(text):
        # `permanent` means "cannot be discarded from play", so it can
        # never reach the discard pile and never rejoins the deck. This is
        # the ONLY place `permanent` is load-bearing: on its own it says
        # nothing about deck membership (§14.5).
        if row.get("permanent"):
            role = (SETUP_ATTACHMENT if kind == "attachment"
                    else STARTS_IN_PLAY)
            return role, False
        # No `permanent`: it can be discarded. A When Revealed ability or
        # a boost value proves it has a use FROM the deck, so it rejoins.
        returns = bool(WHEN_REVEALED_RE.search(text)) or \
            row.get("boost") is not None
        return STARTS_IN_PLAY, returns

    return DECK, True


def set_aside_groups(rows: list[dict]) -> dict[tuple[str, str], set[str]]:
    """Card groups other cards describe as set aside.

    Keyed by `(trait_or_name, type_code)`, valued by the set codes whose
    text refers to them. Cross-checked in `audit` against the main scheme
    `Setup` blocks - two unrelated places in the data, so a disagreement
    is a signal rather than a coin flip.
    """
    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        text = row.get("text") or ""
        for rx in (ASIDE_TRAIT_RE, ASIDE_NAMED_RE):
            for m in rx.finditer(text):
                label = m.group(1).strip()
                if NOT_A_GROUP.match(label) or "[[" in label:
                    continue
                kind = m.group(2).lower().replace(" ", "_")
                groups[(label, kind)].add(row.get("set_code") or "")
    return dict(groups)


def build(conn: sqlite3.Connection) -> dict[str, int]:
    from collections import Counter

    rows = [dict(r) for r in conn.execute(
        "SELECT code, name, type_code, traits, text, permanent, boost, "
        "quantity, set_code FROM cards")]

    conn.execute("DELETE FROM encounter_role")
    counts: Counter = Counter()
    payload = []
    for row in rows:
        role, returns = classify_card(row)
        decided = ("type" if role in (NOT_ENCOUNTER, STARTS_IN_PLAY)
                   and not (row.get("text") or "") else "text")
        payload.append((row["code"], role, int(returns), decided))
        counts[role] += 1
    conn.executemany(
        "INSERT OR REPLACE INTO encounter_role "
        "(code, role, returns_to_deck, decided_by) VALUES (?, ?, ?, ?)",
        payload)
    conn.commit()
    return dict(counts)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_encounterdeck.py -v`
Expected: PASS, 11 tests

- [ ] **Step 6: Gate against the real corpus**

```bash
uv run python -c "
from mc_jarvis import index, paths, encounterdeck as ed
conn = index.connect(paths.db_path())
print(ed.build(conn))
for r in conn.execute('''SELECT e.role, COUNT(*) n FROM encounter_role e
    JOIN cards c ON c.code=e.code JOIN sets s ON s.code=c.set_code
    WHERE s.card_set_type_code IN (\"villain\",\"modular\")
    GROUP BY e.role ORDER BY n DESC'''):
    print(f'   {r[\"role\"]:<18} {r[\"n\"]}')
print('returns_to_deck:', conn.execute('SELECT COUNT(*) FROM encounter_role WHERE returns_to_deck=1 AND role<>\"deck\"').fetchone()[0])
"
```

**Gate**, measured 2026-08-23 over villain+modular sets:
- `other_deck` — **15 or more** (the infinity stone deck alone accounts for 15)
- `setup_attachment` + `starts_in_play` with `returns_to_deck = 0` — **7** (Power Stone, Infinity Gauntlet, Flight, Super Strength, Telepathy, Gene Pool, Ancient Ritual) plus the 3 `Chief … Officer` environments
- `starts_in_play` with `returns_to_deck = 1` — **exactly 3**, the `[[Setting]]` environments

If `returns_to_deck = 1` is not 3, the §14.6 rule has drifted; read the cards before changing the threshold.

- [ ] **Step 7: Commit**

```bash
git add src/mc_jarvis/encounterdeck.py src/mc_jarvis/schema.py tests/test_encounterdeck.py
git commit -m "feat: classify encounter-deck membership, the denominator of every average"
```

---

## Task 3: The set-aside audit and its config

Implements §5.1's three-step structure with its first step replaced (§14.7): a rule over card text, cross-checked against a second source, with config for the residue.

**Files:**
- Create: `config/encounter_setup.yaml`, symlink `src/mc_jarvis/_bundled/encounter_setup.yaml`
- Modify: `src/mc_jarvis/encounterdeck.py`, `pyproject.toml`
- Test: `tests/test_encounterdeck.py`

**Interfaces:**
- Consumes: `encounterdeck.set_aside_groups`
- Produces:
  - `encounterdeck.load_config(path: Path | None = None) -> dict`
  - `encounterdeck.setup_blocks(conn) -> dict[str, str]` — villain set code → its main scheme `Setup` text
  - `encounterdeck.audit(conn) -> list[str]` — problems, empty when clean
  - `encounterdeck.AuditError`

- [ ] **Step 1: Write `config/encounter_setup.yaml`**

```yaml
# Cards a scenario sets aside that the card text does not name.
#
# Most set-aside cards ARE named, by other cards, using the hyphenated
# adjective: "a random set-aside [[Prelate]] minion". `set_aside_groups`
# reads those, and the main scheme `Setup` block names them independently
# - two unrelated places in the data, so `audit` cross-checks them rather
# than trusting either.
#
# This file holds only what NEITHER source names, plus any group the
# regex resolves to nothing. Each entry carries the sentence that
# justifies it, re-verified at build time against the indexed text, so a
# reworded card fails the build instead of leaving a stale reason.

version: 1

# Villain sets whose `Setup` block flags an aside or a put-into-play that
# `set_aside_groups` does not cover. 33 of 56 villain sets carry such a
# block; most are covered by the text rule. List the exceptions here.
acknowledged: {}

# Groups the regex finds but that resolve to no card - upstream typos and
# phrasings the pattern was not built for. Empty is the goal.
unresolved: {}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_encounterdeck.py — append
def test_audit_is_clean_when_every_flagged_set_is_covered(tmp_path):
    """A scenario whose Setup block sets something aside must have that
    something identified - by the text rule or by config. Coverage is
    acknowledged, never inferred: the parent plan records a case where a
    set containing both a detectable card and an unmarked one was
    silently passed."""
    from mc_jarvis import index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.executemany(
        "INSERT INTO sets (code, name, card_set_type_code) VALUES (?, ?, ?)",
        [("apoc", "Apocalypse", "villain")])
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, set_code, text, quantity, "
        "traits) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("m1", "The Age of Apocalypse", "main_scheme", "apoc",
          "<b>Setup</b>: Set aside each [[Prelate]] minion.", 1, ""),
         ("m2", "Heart of the Empire", "main_scheme", "apoc",
          "The first player reveals a random set-aside [[Prelate]] minion.",
          1, ""),
         ("p1", "Prelate Guard", "minion", "apoc", "Guard.", 2, "Prelate.")])
    conn.commit()
    assert ed.audit(conn) == []


def test_audit_names_a_flagged_set_that_nothing_covers(tmp_path):
    from mc_jarvis import index

    conn = index.connect(tmp_path / "mc.sqlite")
    conn.execute(
        "INSERT INTO sets (code, name, card_set_type_code) VALUES (?, ?, ?)",
        ("myst", "Mystery", "villain"))
    conn.execute(
        "INSERT INTO cards (code, name, type_code, set_code, text, quantity, "
        "traits) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("m1", "A Scheme", "main_scheme", "myst",
         "<b>Setup</b>: Set the Whatsit attachment aside.", 1, ""))
    conn.commit()
    problems = ed.audit(conn)
    assert problems
    assert "myst" in problems[0]
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_encounterdeck.py -k audit -v`
Expected: FAIL — `AttributeError: module 'mc_jarvis.encounterdeck' has no attribute 'audit'`

- [ ] **Step 4: Implement the audit**

Append to `encounterdeck.py`:

```python
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "_bundled" / "encounter_setup.yaml"

# A `Setup` block that removes cards from the deck, in either of the two
# forms FFG uses. 16 villain sets say "set ... aside" and 26 say
# "put ... into play"; 9 say both, so 33 of 56 need covering.
FLAGS_ASIDE_RE = re.compile(r"\bset\b.{0,40}\baside\b", re.I)
FLAGS_INTO_PLAY_RE = re.compile(r"\bput\b.{0,60}\binto play\b", re.I)


class AuditError(RuntimeError):
    """A scenario removes cards from its deck and nothing says which."""


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def setup_blocks(conn) -> dict[str, str]:
    """Each villain set's main-scheme `Setup` instruction, as plain text."""
    out: dict[str, str] = {}
    for row in conn.execute(
            "SELECT c.set_code, c.text FROM cards c "
            "JOIN sets s ON s.code = c.set_code "
            "WHERE c.type_code = 'main_scheme' AND s.card_set_type_code = "
            "'villain' AND c.text LIKE '%Setup%'"):
        text = re.sub(r"<[^>]+>", "", " ".join((row["text"] or "").split()))
        if "Setup:" in text:
            out.setdefault(row["set_code"], text[text.find("Setup:"):])
    return out


def audit(conn, config: dict | None = None) -> list[str]:
    """Every scenario that removes cards from its deck must say which.

    Two independent sources: the hyphenated `set-aside` references in card
    text, and the main scheme's own `Setup` block. A set flagged by the
    second and covered by neither the first nor config is reported.
    """
    config = config if config is not None else load_config()
    acknowledged = set(config.get("acknowledged") or {})
    rows = [dict(r) for r in conn.execute(
        "SELECT code, name, type_code, traits, text, set_code FROM cards")]
    covered = {s for sets in set_aside_groups(rows).values() for s in sets}

    problems = []
    for set_code, setup in sorted(setup_blocks(conn).items()):
        if not (FLAGS_ASIDE_RE.search(setup)
                or FLAGS_INTO_PLAY_RE.search(setup)):
            continue
        if set_code in covered or set_code in acknowledged:
            continue
        problems.append(
            f"{set_code}: its Setup block removes cards from the encounter "
            f"deck and nothing identifies them - "
            f"{setup[:110]!r}. Add an `acknowledged` entry to "
            f"encounter_setup.yaml, or extend the set-aside rule.")
    return problems
```

- [ ] **Step 5: Link the config and run the tests**

```bash
ln -sfn ../../../config/encounter_setup.yaml src/mc_jarvis/_bundled/encounter_setup.yaml
```

Add to the `force-include` block in `pyproject.toml`:

```toml
"config/encounter_setup.yaml" = "src/mc_jarvis/_bundled/encounter_setup.yaml"
```

Run: `uv run pytest tests/test_encounterdeck.py -v`
Expected: PASS

- [ ] **Step 6: Run the audit against the real corpus and fill the config**

```bash
uv run python -c "
from mc_jarvis import index, paths, encounterdeck as ed
conn = index.connect(paths.db_path())
problems = ed.audit(conn)
print('uncovered scenarios:', len(problems))
for p in problems: print('  ', p[:150])
"
```

**Every uncovered scenario is a decision, not a number to suppress.** Read its `Setup` sentence. If the cards it removes are named by another card's text, the rule missed them — extend the rule and say which variant it missed. If nothing names them, add an `acknowledged` entry quoting the sentence. Do **not** widen `FLAGS_ASIDE_RE` to make the count go down.

Measured 2026-08-23: **33 of 56** villain sets carry a flagged `Setup` block, and the text rule covers those referenced by `[[Prelate]]`, `[[Adaptoid]]`, `[[Captive]]`, `[[Morlock]]`, `[[Thunderbolt]]`, `Rescued Captive` and `Orbital Decay`. Expect roughly **20** to need an entry.

- [ ] **Step 7: Commit**

```bash
git add config/encounter_setup.yaml src/mc_jarvis/encounterdeck.py \
        src/mc_jarvis/_bundled tests/test_encounterdeck.py pyproject.toml
git commit -m "feat: the set-aside audit, cross-checking card text against Setup blocks"
```

---

## Task 4: The scenario → modular mapping, parsed

Implements §7 **as corrected by §14.1**: parsed from the main scheme, not hand-authored.

**Files:**
- Create: `config/scenarios.yaml`, symlink in `_bundled`
- Modify: `src/mc_jarvis/encounterdeck.py`, `src/mc_jarvis/schema.py`, `pyproject.toml`
- Test: `tests/test_encounterdeck.py`

**Interfaces:**
- Produces:
  - `encounterdeck.parse_contents(text: str) -> dict` — `{"kind": str, "names": list[str], "count": int | None}` where `kind` is `prescribed` | `recommended` | `open` | `random` | `none`
  - `encounterdeck.build_scenarios(conn) -> dict[str, int]`
  - `encounterdeck.scenario_gate(conn) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_encounterdeck.py — append
def test_prescribed_modulars_are_read_from_the_contents_block():
    """§14.1: FFG prints the scenario's contents on its main scheme card,
    and marvelsdb carries it verbatim. 49 of 56 villain sets have one."""
    got = ed.parse_contents(
        "<b>Contents</b>: Unus (I) and Unus (II). Unus, Infinites, and "
        "Standard sets. One modular set <i>(Dystopian Nightmare)</i>. "
        "<b>Setup</b>: Reveal the Gene Pool side scheme.")
    assert got["kind"] == "prescribed"
    assert got["names"] == ["Dystopian Nightmare"]


def test_two_named_modulars_are_split():
    got = ed.parse_contents(
        "<b>Contents</b>: ... Two modular sets <i>(Dark Riders and "
        "Infinites)</i>.")
    assert got["names"] == ["Dark Riders", "Infinites"]


def test_a_recommendation_is_not_a_prescription():
    """`(recommended: Bomb Scare)` and `(Dystopian Nightmare)` are
    different strings in FFG's own text. Flattening them would state a
    constraint the box does not impose."""
    got = ed.parse_contents(
        "<b>Contents</b>: ... One modular encounter set "
        "<i>(recommended: Bomb Scare)</i>.")
    assert got["kind"] == "recommended"
    assert got["names"] == ["Bomb Scare"]


def test_markup_and_trailing_stops_are_stripped():
    """Five sets failed to resolve because the capture kept inner <i>
    tags; two more because the stop sat inside the parens."""
    got = ed.parse_contents(
        "<b>Contents</b>: ... Two modular sets (<i>Acolytes</i> and "
        "<i>Mystique</i>.).")
    assert got["names"] == ["Acolytes", "Mystique"]


def test_a_player_chosen_scenario_names_nothing():
    """Thunderbolts and the PvP scenarios let the player choose. There is
    no mapping to infer, and inventing one would be worse than none."""
    got = ed.parse_contents(
        "<b>Contents</b>: ... <b>Setup</b>: Choose 1 modular set, plus "
        "1[per_hero] additional modular sets, each with an [[Elite]] minion.")
    assert got["kind"] == "open"
    assert got["names"] == []


def test_a_random_scenario_is_marked_random():
    got = ed.parse_contents(
        "<b>Contents</b>: ... 1 random modular set from the collection.")
    assert got["kind"] == "random"


def test_no_contents_block_at_all():
    assert ed.parse_contents("<b>Setup</b>: Advance to stage 1B.")["kind"] \
        == "none"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_encounterdeck.py -k contents -v`
Expected: FAIL — `AttributeError: … has no attribute 'parse_contents'`

- [ ] **Step 3: Add the table to `schema.py`**

```sql
-- Which modular sets a scenario prescribes, parsed from its own main
-- scheme's Contents block (spec §14.1, correcting §4.7). `kind`
-- distinguishes prescribed from recommended from player-chosen, because
-- a player picking modulars needs to know which the box imposes.
CREATE TABLE IF NOT EXISTS scenario_modulars (
    villain_set TEXT NOT NULL,
    kind        TEXT NOT NULL,   -- prescribed | recommended | open | random | none
    modular_set TEXT,            -- NULL when the scenario names none
    PRIMARY KEY (villain_set, COALESCE(modular_set, ''))
);
```

SQLite forbids an expression in `PRIMARY KEY`. Use a unique index instead:

```sql
CREATE TABLE IF NOT EXISTS scenario_modulars (
    villain_set TEXT NOT NULL,
    kind        TEXT NOT NULL,
    modular_set TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scenario_modulars
    ON scenario_modulars(villain_set, COALESCE(modular_set, ''));
```

- [ ] **Step 4: Implement the parse**

Append to `encounterdeck.py`:

```python
NUM = r"(?:One|Two|Three|Four|Five|\d+(?:[-–]\d+)?)"
MODULAR_NAMED_RE = re.compile(
    rf"{NUM}\s+modular(?:\s+encounter)?\s+sets?\s*(?:<i>)?\s*\(([^)]+)\)",
    re.I)
MODULAR_OPEN_RE = re.compile(
    rf"(?:Choose\s+\d+\s+modular)|(?:{NUM}\s+modular(?:\s+encounter)?\s+sets?)",
    re.I)
MODULAR_RANDOM_RE = re.compile(r"random\s+modular", re.I)
RECOMMENDED_RE = re.compile(r"^\s*recommended\s*:\s*", re.I)


def parse_contents(text: str) -> dict:
    """The modular clause of a main scheme's `Contents` block.

    Three kinds of scenario, and they must stay apart: `prescribed` names
    the sets the box imposes, `recommended` names a suggestion the player
    may substitute freely, and `open` leaves the choice entirely to the
    player.
    """
    flat = " ".join((text or "").split())
    if MODULAR_RANDOM_RE.search(flat):
        return {"kind": "random", "names": [], "count": None}

    m = MODULAR_NAMED_RE.search(flat)
    if m:
        clause = m.group(1)
        kind = "recommended" if RECOMMENDED_RE.search(clause) else "prescribed"
        clause = RECOMMENDED_RE.sub("", clause)
        clause = re.sub(r"<[^>]+>", "", clause)
        names = [n.strip(" .,") for n in re.split(r",| and ", clause)
                 if n.strip(" .,")]
        return {"kind": kind, "names": names, "count": len(names)}

    if MODULAR_OPEN_RE.search(flat):
        return {"kind": "open", "names": [], "count": None}
    return {"kind": "none", "names": [], "count": None}


def build_scenarios(conn) -> dict[str, int]:
    from collections import Counter

    by_name = {r["name"]: r["code"] for r in conn.execute(
        "SELECT code, name FROM sets WHERE card_set_type_code = 'modular'")}
    config = load_config()
    aliases = (config.get("modular_aliases") or {})

    conn.execute("DELETE FROM scenario_modulars")
    counts: Counter = Counter()
    rows = []
    for row in conn.execute(
            "SELECT DISTINCT c.set_code, c.text FROM cards c "
            "JOIN sets s ON s.code = c.set_code "
            "WHERE c.type_code = 'main_scheme' "
            "AND s.card_set_type_code = 'villain' "
            "AND c.text LIKE '%<b>Contents</b>%'"):
        parsed = parse_contents(row["text"])
        counts[parsed["kind"]] += 1
        if not parsed["names"]:
            rows.append((row["set_code"], parsed["kind"], None))
            continue
        for name in parsed["names"]:
            code = by_name.get(name) or by_name.get(aliases.get(name, ""))
            rows.append((row["set_code"], parsed["kind"], code or f"?{name}"))
    conn.executemany(
        "INSERT OR REPLACE INTO scenario_modulars "
        "(villain_set, kind, modular_set) VALUES (?, ?, ?)", rows)
    conn.commit()
    return dict(counts)


def scenario_gate(conn) -> list[str]:
    """Both directions, as §7 requires, plus a third §14.1 adds.

    - a villain set with no mapping at all;
    - a mapping naming a set code that does not exist;
    - a `Contents` block naming a modular the parse could not resolve.
    """
    problems = []
    have = {r["villain_set"] for r in conn.execute(
        "SELECT DISTINCT villain_set FROM scenario_modulars")}
    config = load_config()
    known_gaps = set(config.get("no_contents_block") or [])

    for row in conn.execute(
            "SELECT DISTINCT set_code FROM cards WHERE type_code = 'villain'"):
        code = row["set_code"]
        if code not in have and code not in known_gaps:
            problems.append(
                f"{code}: no Contents block and no config entry. It would "
                f"be assessed against no modular sets at all, silently.")

    for row in conn.execute(
            "SELECT villain_set, modular_set FROM scenario_modulars "
            "WHERE modular_set LIKE '?%'"):
        problems.append(
            f"{row['villain_set']}: names modular set "
            f"{row['modular_set'][1:]!r}, which does not resolve. Add a "
            f"`modular_aliases` entry if it is an upstream typo.")

    real = {r["code"] for r in conn.execute("SELECT code FROM sets")}
    for row in conn.execute(
            "SELECT villain_set, modular_set FROM scenario_modulars "
            "WHERE modular_set IS NOT NULL AND modular_set NOT LIKE '?%'"):
        if row["modular_set"] not in real:
            problems.append(
                f"{row['villain_set']}: maps to {row['modular_set']!r}, "
                f"which is not a set. A renamed set leaves a stale mapping.")
    return problems
```

Add to `config/scenarios.yaml`:

```yaml
# Only the residue of the Contents parse (spec §14.1). The mapping itself
# is read from each scenario's own main scheme card, because FFG prints it
# there and marvelsdb carries it verbatim - 49 of 56 villain sets.
#
# Gated in three directions by `scenario_gate`: a villain set with no
# mapping, a mapping to a set that does not exist, and a named modular the
# parse cannot resolve. A hand-maintained list does not converge on its
# own; the gates are what keep this file honest.

version: 1

# Upstream spellings that do not match `sets.name`.
modular_aliases:
  # FFG's own typo, on the Batroc main scheme.
  "Batrocs's Brigade": "Batroc's Brigade"
  # The set is named with the final stop.
  "S.H.I.E.L.D": "S.H.I.E.L.D."

# Villain sets whose main scheme carries no Contents block at all. Seven
# were measured 2026-08-23; each needs its modulars from the printed
# insert, or an explicit statement that it prescribes none.
no_contents_block: []
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_encounterdeck.py -v`
Expected: PASS

- [ ] **Step 6: Gate against the real corpus**

```bash
uv run python -c "
from mc_jarvis import index, paths, encounterdeck as ed
conn = index.connect(paths.db_path())
print('kinds:', ed.build_scenarios(conn))
for p in ed.scenario_gate(conn): print('  GATE', p[:130])
"
```

**Gate**, measured 2026-08-23 across 56 villain sets: **35 prescribed with every name resolved, 7 named but unresolved, 7 with no `Contents` block, 6 player-chosen, 1 random.** The 7 unresolved are formatting variance plus one upstream typo — Step 4's `modular_aliases` covers two of them, and stripping inner markup covers five. **Expect the unresolved count to reach 0**; every remaining one is a decision.

- [ ] **Step 7: Commit**

```bash
git add config/scenarios.yaml src/mc_jarvis/encounterdeck.py \
        src/mc_jarvis/schema.py src/mc_jarvis/_bundled tests/ pyproject.toml
git commit -m "feat: parse the scenario-modular mapping from the main scheme"
```

---

## Task 5: Scenario assembly

> **Corrections applied 2026-08-27, measured against the built index.**
> The code below was written before §14.10 and before the a/b measurement,
> and is wrong in five ways. Implement the corrected form.
>
> 1. **`scenario_modulars.villain_set` no longer exists**; the column is
>    `scenario_set` (§14.10). The SQL below throws as written.
> 2. **`Scenario.villain_set` is renamed `scenario_set`** for the same
>    reason. Leaving the old name re-introduces the wrong model at the API
>    surface.
> 3. **`deck_cards` must filter `is_reprint = 0`.** 10 deck-role rows are
>    reprints of a card already counted.
> 4. **`deck_cards` must drop back faces.** 70 deck-role rows are the back
>    of a card whose front is also a deck row - `aoa_mission` returns 10
>    rows for 5 missions. Two candidate rules were cross-checked: rows
>    named by some card's `back_link` (66) against rows whose code is
>    `X+b` with an `X+a` sibling (70). The `back_link` set is a strict
>    subset; the 4 extras were read individually and only ONE is a back
>    face (`45104b`, whose front carries an upstream-wrong `back_link`).
>    The other three - `01144b` Android Efficiency, `50184b` A.I.M.
>    Interference, `61033b` Suggestion - are separate physical cards that
>    happen to share a code stem. So: use `back_link`, plus a config list
>    for the upstream-broken case.
> 5. **The Task 5 tests all use `rhino`, where set == scenario**, so
>    nothing exercises what §14.10 says Part 1 must do. Add the two
>    missing directions: a component set (`marauders`, `exp_kang`, the
>    four wrecking-crew sets) must name its host scenario rather than
>    report no mapping, and a scenario with no villain set of its own
>    (`morlock_siege`, `on_the_run`, the PvP four) must resolve normally.
>
> **Decision on `returns_to_deck`** (the code and the schema comment
> disagreed): `deck_cards` includes the 3 `returns_to_deck = 1` cards -
> The Savage Land, Genosha, Blue Area of the Moon - because each carries a
> boost value and a When Revealed ability, which are only meaningful from
> the deck. Each row carries its `role`, so `profile` can report them
> apart from the opening deck rather than hiding them in one number.

Turns a villain plus options into the multiset of cards a player faces.

**Files:**
- Create: `src/mc_jarvis/assess.py`
- Test: `tests/test_assess.py`

**Interfaces:**
- Consumes: `encounter_role`, `scenario_modulars`
- Produces:
  - `assess.Scenario` — dataclass `villain_set: str`, `modulars: list[str]`, `difficulty: str`, `players: int`, `heroic: int`, `nemesis: list[str]`, `pool: list[str]`
  - `assess.resolve(conn, villain: str, *, modular=None, players=1, difficulty="standard", heroic=0, nemesis=()) -> Scenario`
  - `assess.deck_cards(conn, scenario: Scenario, *, added: int = 0) -> list[dict]`
  - `assess.UnknownScenario`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assess.py
import pytest

from mc_jarvis import assess, index


@pytest.fixture
def conn(tmp_path):
    c = index.connect(tmp_path / "mc.sqlite")
    c.executemany(
        "INSERT INTO sets (code, name, card_set_type_code) VALUES (?, ?, ?)",
        [("rhino", "Rhino", "villain"), ("bomb", "Bomb Scare", "modular"),
         ("standard", "Standard", "standard")])
    c.executemany(
        "INSERT INTO cards (code, name, type_code, set_code, quantity, boost, "
        "text, traits) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [("v1", "Rhino", "villain", "rhino", 1, None, "", ""),
         ("t1", "Stampede", "treachery", "rhino", 3, 1, "", ""),
         ("a1", "Charge", "attachment", "rhino", 2, 2, "", ""),
         ("b1", "Bomb", "treachery", "bomb", 2, 1, "", ""),
         ("s1", "Caught Off Guard", "treachery", "standard", 1, 1, "", "")])
    c.executemany(
        "INSERT INTO encounter_role (code, role, returns_to_deck, decided_by) "
        "VALUES (?, ?, ?, ?)",
        [("v1", "starts_in_play", 0, "type"), ("t1", "deck", 1, "type"),
         ("a1", "deck", 1, "type"), ("b1", "deck", 1, "type"),
         ("s1", "deck", 1, "type")])
    c.execute("INSERT INTO scenario_modulars (villain_set, kind, modular_set) "
              "VALUES ('rhino', 'recommended', 'bomb')")
    c.commit()
    return c


def test_resolve_uses_the_prescribed_modulars(conn):
    s = assess.resolve(conn, "rhino")
    assert s.modulars == ["bomb"]


def test_explicit_modulars_override_rather_than_add(conn):
    """§6: a player naming modulars is describing the game on their table,
    not amending a recommendation."""
    conn.execute("INSERT INTO sets (code, name, card_set_type_code) "
                 "VALUES ('other', 'Other', 'modular')")
    s = assess.resolve(conn, "rhino", modular=["other"])
    assert s.modulars == ["other"]


def test_the_difficulty_set_is_included(conn):
    """Omitting it understates the boost curve - Expert's three cards
    average 2.3 (§4.2)."""
    codes = {c["code"] for c in assess.deck_cards(conn, assess.resolve(conn, "rhino"))}
    assert "s1" in codes


def test_cards_that_are_not_in_the_deck_are_excluded(conn):
    codes = {c["code"] for c in assess.deck_cards(conn, assess.resolve(conn, "rhino"))}
    assert "v1" not in codes


def test_an_unknown_villain_is_named_not_guessed(conn):
    with pytest.raises(assess.UnknownScenario, match="galactus"):
        assess.resolve(conn, "galactus")


def test_a_villain_missing_from_marvelcdb_says_so(conn):
    """§14.5: coverage is bounded by marvelcdb, which carries no Bullseye
    villain set even though the scenario is playable online. `assess` must
    say the scenario is absent rather than report a partial deck."""
    with pytest.raises(assess.UnknownScenario, match="not in the card data"):
        assess.resolve(conn, "bullseye")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_assess.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mc_jarvis.assess'`

- [ ] **Step 3: Write the assembly half of `assess.py`**

```python
"""Scenario threat profile (spec §1-§8, Part 1).

Facts and derived statistics only. No card recommendations: turning
"6 Tough minions, 2 answers" into "cut a Tackle" is the model's job,
taught by SKILL.md. A `recommend_tech()` here would invert the project's
architecture and make the feature untestable - you can assert numbers,
you cannot assert opinions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DIFFICULTIES = ("standard", "expert", "standard_ii", "expert_ii",
                "standard_iii", "standard_pvp")


class UnknownScenario(RuntimeError):
    """No such villain set in the index."""


@dataclass
class Scenario:
    villain_set: str
    modulars: list[str] = field(default_factory=list)
    difficulty: str = "standard"
    players: int = 1
    heroic: int = 0
    nemesis: list[str] = field(default_factory=list)
    # Sets that may be shuffled in DURING play (§14.9). Empty for the
    # great majority of scenarios.
    pool: list[str] = field(default_factory=list)
    modular_kind: str = "none"


def resolve(conn, villain: str, *, modular=None, players: int = 1,
            difficulty: str = "standard", heroic: int = 0,
            nemesis=()) -> Scenario:
    row = conn.execute(
        "SELECT code FROM sets WHERE code = ? OR lower(name) = lower(?)",
        (villain, villain)).fetchone()
    if row is None:
        raise UnknownScenario(
            f"{villain!r} is not in the card data. mc-jarvis indexes "
            f"marvelcdb, which does not carry every scenario that is "
            f"playable - a partial deck would be worse than no answer.")
    code = row["code"]

    mapped = conn.execute(
        "SELECT kind, modular_set FROM scenario_modulars WHERE villain_set = ?",
        (code,)).fetchall()
    if not mapped and modular is None:
        raise UnknownScenario(
            f"{code!r} has no modular mapping. Pass --modular to say which "
            f"sets are on your table.")

    kind = mapped[0]["kind"] if mapped else "open"
    if modular is not None:
        # An explicit list REPLACES the default (§6).
        modulars = list(modular)
    else:
        modulars = [m["modular_set"] for m in mapped if m["modular_set"]]

    return Scenario(villain_set=code, modulars=modulars,
                    difficulty=difficulty, players=players, heroic=heroic,
                    nemesis=list(nemesis), modular_kind=kind)


def _sets(scenario: Scenario) -> list[str]:
    return ([scenario.villain_set] + scenario.modulars
            + [scenario.difficulty] + scenario.nemesis)


def deck_cards(conn, scenario: Scenario, *, added: int = 0) -> list[dict]:
    """Every card in the encounter deck, one row per printing.

    `quantity` is carried, never collapsed: the Rhino set ships
    `Stampede x3 boost 1` and `Charge x2 boost 2`, and a mean over rows is
    not the expected boost of a card the player draws (§4.5).
    """
    codes = _sets(scenario) + scenario.pool[:added]
    marks = ",".join("?" * len(codes))
    return [dict(r) for r in conn.execute(
        f"SELECT c.*, e.role, e.returns_to_deck FROM cards c "
        f"JOIN encounter_role e ON e.code = c.code "
        f"WHERE c.set_code IN ({marks}) AND e.role = 'deck' "
        f"ORDER BY c.set_code, c.code", codes)]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_assess.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mc_jarvis/assess.py tests/test_assess.py
git commit -m "feat: assemble a scenario from its villain, modulars and difficulty"
```

---

## Task 6: Aggregation, and the hand-computed gate

> **The gate's own arithmetic is wrong. Corrected 2026-08-27 by re-reading
> the `rhino` and `standard` sets from the index.**
>
> | set | card | qty | boost | contributed |
> |---|---|---|---|---|
> | rhino | Charge | 2 | 2 | 4 |
> | rhino | Enhanced Ivory Horn | 1 | 2 | 2 |
> | rhino | Armored Rhino Suit | 1 | - | 0 |
> | rhino | Hydra Mercenary | 2 | 1 | 2 |
> | rhino | Sandman | 1 | 2 | 2 |
> | rhino | Shocker | 1 | 2 | 2 |
> | rhino | Hard to Keep Down | 2 | - | 0 |
> | rhino | "I'm Tough" | 2 | - | 0 |
> | rhino | Stampede | 3 | 1 | 3 |
> | rhino | Breakin' & Takin' | 1 | 2 | 2 |
> | rhino | Crowd Control | 1 | 2 | 2 |
> | standard | Advance | 2 | - | 0 |
> | standard | Assault | 2 | - | 0 |
> | standard | Caught Off Guard | 1 | 1 | 1 |
> | standard | Gang-Up | 1 | 1 | 1 |
> | standard | Shadow of the Past | 1 | 2 | 2 |
>
> `rhino` is **17 copies / 19 boost** - the plan's sum had six terms and
> dropped Breakin' & Takin' and Crowd Control. `standard` is 5 rows but
> **7 copies**, not 5; its boost total of 4 was right. So the gate reads
> `deck_size == 24`, `by_set["standard"] == 7`, `boost.total == 23`,
> `mean == 23/24`.
>
> Note the trap this set: `by_set["rhino"] == 17` was the one assertion
> that was already correct, which made a systematic error look like a
> single mismatch.
>
> **`rhino` has no a/b deck rows**, so this gate cannot catch the
> back-face double-count. Add a second gate on `aoa_mission`: 5 missions,
> 10 rows before de-duping, **5 after**.

Implements §8. The gate is §12's: a scenario worked out by hand and compared against what `assess` emits.

**Files:**
- Modify: `src/mc_jarvis/assess.py`
- Test: `tests/test_assess.py`

**Interfaces:**
- Produces: `assess.profile(conn, scenario: Scenario, *, added: int = 0) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assess.py — append
def test_boost_mean_is_quantity_weighted(conn):
    """Stampede x3 boost 1 and Charge x2 boost 2 give (3*1 + 2*2)/5 = 1.4,
    not the row mean of 1.5. A mean over distinct rows is not the expected
    boost of a card the player draws (§4.5)."""
    s = assess.resolve(conn, "rhino", modular=[])
    got = assess.profile(conn, s)
    # rhino: Stampede x3 boost 1, Charge x2 boost 2; standard: 1 boost 1
    assert got["deck_size"] == 6
    assert round(got["boost"]["mean"], 3) == round((3 * 1 + 2 * 2 + 1) / 6, 3)


def test_a_card_with_no_boost_counts_as_zero_not_as_missing(conn):
    """§4.3: absent means zero boost icons, measured flat across seven
    years of releases. Excluding those cards from the denominator inflates
    the mean."""
    conn.execute("INSERT INTO cards (code, name, type_code, set_code, "
                 "quantity, boost, text, traits) VALUES "
                 "('t9','Quiet','treachery','rhino',1,NULL,'','')")
    conn.execute("INSERT INTO encounter_role (code, role, returns_to_deck, "
                 "decided_by) VALUES ('t9','deck',1,'type')")
    conn.commit()
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["deck_size"] == 7
    assert round(got["boost"]["mean"], 3) == round((3 + 4 + 1) / 7, 3)


def test_the_histogram_sums_to_the_deck_size(conn):
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert sum(got["boost"]["histogram"].values()) == got["deck_size"]


def test_boost_star_is_counted_never_averaged(conn):
    """§4.4: the star is an additional icon with a card-specific effect,
    not a numeric value. 134 cards carry both."""
    conn.execute("UPDATE cards SET boost_star = 1 WHERE code = 'a1'")
    conn.commit()
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["boost"]["star_copies"] == 2       # Charge x2
    assert round(got["boost"]["mean"], 3) == round((3 * 1 + 2 * 2 + 1) / 6, 3)


def test_every_number_can_name_its_cards(conn):
    """§8: so the model can cite rather than assert."""
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["by_type"]["treachery"]["cards"]


def test_the_denominator_is_reported_with_the_mean(conn):
    """§8: reported with the deck size it is drawn over, so the reader can
    see the denominator."""
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    assert got["boost"]["over"] == got["deck_size"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_assess.py -k boost -v`
Expected: FAIL — `AttributeError: module 'mc_jarvis.assess' has no attribute 'profile'`

- [ ] **Step 3: Implement `profile`**

```python
def _weighted(cards: list[dict], field_: str) -> tuple[int, int]:
    """(total, copies) over quantity, treating an absent value as zero."""
    total = sum((c.get(field_) or 0) * c["quantity"] for c in cards)
    copies = sum(c["quantity"] for c in cards)
    return total, copies


def profile(conn, scenario: Scenario, *, added: int = 0) -> dict:
    from collections import Counter, defaultdict

    cards = deck_cards(conn, scenario, added=added)
    size = sum(c["quantity"] for c in cards)

    boost_total, _ = _weighted(cards, "boost")
    histogram: Counter = Counter()
    for c in cards:
        histogram[c.get("boost") or 0] += c["quantity"]

    by_type: dict[str, dict] = defaultdict(
        lambda: {"copies": 0, "rows": 0, "cards": []})
    for c in cards:
        entry = by_type[c["type_code"]]
        entry["copies"] += c["quantity"]
        entry["rows"] += 1
        entry["cards"].append({"code": c["code"], "name": c["name"],
                               "quantity": c["quantity"]})

    by_set: Counter = Counter()
    for c in cards:
        by_set[c["set_code"]] += c["quantity"]

    return {
        "scenario": scenario.villain_set,
        "modulars": scenario.modulars,
        "modular_kind": scenario.modular_kind,
        "difficulty": scenario.difficulty,
        "players": scenario.players,
        "deck_size": size,
        "boost": {
            # Quantity-weighted, over the WHOLE deck: a card with no boost
            # value has zero boost icons and stays in the denominator.
            "mean": (boost_total / size) if size else 0.0,
            "total": boost_total,
            "over": size,
            "histogram": dict(sorted(histogram.items())),
            # Counted, never averaged (§4.4).
            "star_copies": sum(c["quantity"] for c in cards
                               if c.get("boost_star")),
        },
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
        "by_set": dict(by_set),
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_assess.py -v`
Expected: PASS

- [ ] **Step 5: Write the hand-computed real-data gate**

```python
# tests/test_assess.py — append
@pytest.mark.integration
def test_rhino_standard_one_player_matches_a_hand_count(real_index):
    """§12's gate, and the only check that can fail an error shared
    between a fixture and the implementation.

    Worked by hand from the `rhino` set as the card data gives it, plus
    the Standard set, no modulars:

        rhino    Charge              x2  boost 2
        rhino    Enhanced Ivory Horn x1  boost 2
        rhino    Armored Rhino Suit  x1  boost -
        rhino    Hydra Mercenary     x2  boost 1
        rhino    Sandman             x1  boost 2
        rhino    Shocker             x1  boost 2
        rhino    Hard to Keep Down   x2  boost -
        rhino    "I'm Tough"         x2  boost -
        rhino    Stampede            x3  boost 1
        rhino    Breakin' & Takin'   x1  boost 2
        rhino    Crowd Control       x1  boost 2

    The three villain stages and both main scheme cards are excluded by
    type. That is 17 copies from `rhino`.
    """
    s = assess.resolve(real_index, "rhino", modular=[], difficulty="standard")
    got = assess.profile(real_index, s)

    rhino_only = got["by_set"].get("rhino")
    assert rhino_only == 17, got["by_set"]

    # Standard adds 5 treacheries: boost -, -, 1, 1, 2 (§4.2).
    assert got["by_set"].get("standard") == 5
    assert got["deck_size"] == 22

    # Hand-computed boost total for `rhino`:
    #   2*2 + 1*2 + 2*1 + 1*2 + 1*2 + 3*1 = 4+2+2+2+2+3 = 15
    # Standard adds 1 + 1 + 2 = 4. Total 19 over 22 copies.
    assert got["boost"]["total"] == 19
    assert round(got["boost"]["mean"], 2) == round(19 / 22, 2)
```

- [ ] **Step 6: Run the gate**

Run: `uv run pytest tests/test_assess.py -m integration -v`

**This gate is the point of the task.** If it fails, do **not** adjust the expected numbers to match the output. Re-read the `rhino` set from the index and work the arithmetic again by hand; `Armored Rhino Suit`'s membership is the one genuinely uncertain card, and §14.5 records that nothing in the data excludes it. If the discrepancy is exactly that card, the finding is that it *is* in the deck — record it in the spec rather than special-casing it.

- [ ] **Step 7: Commit**

```bash
git add src/mc_jarvis/assess.py tests/test_assess.py
git commit -m "feat: quantity-weighted composition and boost curve, gated by hand"
```

---

## Task 7: Minions, treacheries, schemes, keywords

> **Corrected 2026-08-27. The task's keyword rule was wrong, and wrong in
> the direction that produces a confident headline number.**
>
> The plan re-implements keyword matching in `assess.py` with
> `\b{word}\b` over card text. `card_keywords` already exists and does
> exactly that - and it is what made the defect visible: **261
> encounter-deck cards mention `surge` and only 80 print it.** Rhino's
> entire treachery suite reads *"this card gains surge"* - a conditional
> whose condition is the point of the card - so the naive count reports
> **12 of 14 copies surging** for a deck whose printed surge rate is
> **zero**.
>
> Corrections:
>
> 1. **The fix belongs in `cardtext.py`, not `assess.py`.** `KEYWORDS`
>    lives there, `card_keywords` is built there, and every consumer of
>    that table has the same overcount. Adding a second keyword list in
>    `assess.py` would fix one caller and leave the rest wrong.
>    `card_keywords` gains `printed INTEGER NOT NULL DEFAULT 0`;
>    `SCHEMA_VERSION` 18 -> 19.
> 2. **The rule is FFG's typography, not a lookbehind.** A first attempt
>    excluded `gains?\s+$` and left nine keywords at a suspicious ratio of
>    exactly 1.00 - the shape of a rule that never fires. The grant forms
>    measured in the corpus are `gains X`, `gains X and Y`, `loses X`,
>    `attacks gain X`, `has X`, `with X`; no window catches them all. What
>    does: a printed keyword stands as **its own sentence**, carrying
>    nothing but keywords, their values and icon tokens. Grants always
>    carry a subject and a verb.
> 3. **Four residue cards were read individually.** `Heart-Shaped Herb`
>    prints Surge with reminder text and no full stop - printed.
>    `Escaped Convict` (two rows) prints it with neither - printed.
>    `Full Auto` reads `<b>When Revealed (Alter-Ego)</b>: Surge.`, so it
>    surges only in alter-ego - **conditional**. That last is the one a
>    future reader will re-litigate.
> 4. **Report the two apart and never sum them:** `surge_copies` and
>    `conditional_surge_copies`. `surge_rate` is over printed surge only.
> 5. **`piercing`, `overkill` and `ranged` are printed by NO
>    encounter-deck card.** Every instance grants the keyword to an attack
>    (`Charge`: "Rhino's attacks gain overkill"). A zero there is a
>    measurement, not a broken rule, and the gate asserts it.
>
> **Gate**, re-measured. Rhino + Standard, 2 players, no modulars: deck
> size **24** (not 22), minions **4 copies**, treacheries **14 copies**
> (not 12), side schemes **2** with threat total **6** (Breakin' & Takin'
> 2 fixed + Crowd Control 2 per hero x2), `guard` **2**, `toughness`
> **1**, printed surge **0**, conditional surge **12**.

The rest of §8. Each number carries the cards behind it.

**Files:**
- Modify: `src/mc_jarvis/assess.py`
- Test: `tests/test_assess.py`

**Interfaces:**
- Produces: `profile()` gains `minions`, `treacheries`, `side_schemes`, `scheme_pressure`, `keywords`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assess.py — append
def test_minion_profile_reports_ranges_and_keywords(conn):
    conn.executemany(
        "INSERT INTO cards (code, name, type_code, set_code, quantity, "
        "boost, health, attack, scheme, health_per_hero, text, traits) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [("m1", "Hydra Mercenary", "minion", "rhino", 2, 1, 3, 1, 1, 0,
          "Guard.", ""),
         ("m2", "Sandman", "minion", "rhino", 1, 2, 4, 2, 1, 1,
          "Toughness.", "")])
    conn.executemany("INSERT INTO encounter_role (code, role, "
                     "returns_to_deck, decided_by) VALUES (?,'deck',1,'type')",
                     [("m1",), ("m2",)])
    conn.commit()
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    m = got["minions"]
    assert m["copies"] == 3
    assert m["health"] == {"min": 3, "max": 4}
    assert m["scales_per_hero"] == 1          # Sandman only
    assert m["keywords"]["guard"] == 2        # quantity-weighted
    assert m["keywords"]["toughness"] == 1


def test_fixed_threat_is_not_scaled_by_player_count(conn):
    """§4.6: applying per-hero scaling to a fixed-threat scheme produces a
    wrong number in exactly the way printing raw villain HP did."""
    conn.execute(
        "INSERT INTO cards (code, name, type_code, set_code, quantity, "
        "base_threat, base_threat_fixed, text, traits) VALUES "
        "('ss1','Crowd Control','side_scheme','rhino',1,4,1,'','')")
    conn.execute("INSERT INTO encounter_role (code, role, returns_to_deck, "
                 "decided_by) VALUES ('ss1','deck',1,'type')")
    conn.commit()
    at_one = assess.profile(conn, assess.resolve(conn, "rhino", modular=[], players=1))
    at_four = assess.profile(conn, assess.resolve(conn, "rhino", modular=[], players=4))
    assert at_one["side_schemes"]["threat_total"] == 4
    assert at_four["side_schemes"]["threat_total"] == 4       # unchanged


def test_per_hero_threat_scales(conn):
    conn.execute(
        "INSERT INTO cards (code, name, type_code, set_code, quantity, "
        "base_threat, base_threat_fixed, text, traits) VALUES "
        "('ss2','Breakin','side_scheme','rhino',1,2,NULL,'','')")
    conn.execute("INSERT INTO encounter_role (code, role, returns_to_deck, "
                 "decided_by) VALUES ('ss2','deck',1,'type')")
    conn.commit()
    at_three = assess.profile(conn, assess.resolve(conn, "rhino", modular=[], players=3))
    assert at_three["side_schemes"]["threat_total"] == 6


def test_surge_rate_is_reported_over_treachery_copies(conn):
    conn.execute(
        "INSERT INTO cards (code, name, type_code, set_code, quantity, "
        "boost, text, traits) VALUES "
        "('t5','Magnetic Missile','treachery','rhino',2,1,'Surge. …','')")
    conn.execute("INSERT INTO encounter_role (code, role, returns_to_deck, "
                 "decided_by) VALUES ('t5','deck',1,'type')")
    conn.commit()
    got = assess.profile(conn, assess.resolve(conn, "rhino", modular=[]))
    t = got["treacheries"]
    assert t["surge_copies"] == 2
    assert t["surge_rate"] == pytest.approx(2 / t["copies"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_assess.py -k minion -v`
Expected: FAIL — `KeyError: 'minions'`

- [ ] **Step 3: Implement the sections**

Add to `assess.py`, and call them from `profile`:

```python
# Keywords worth counting across an encounter deck. Lower-cased and
# matched on a word boundary so `guard` does not match `safeguard`.
MINION_KEYWORDS = ("guard", "toughness", "retaliate", "overkill",
                   "quickstrike", "stalwart", "steady", "piercing")
ICON_FIELDS = ("scheme_acceleration", "scheme_amplify", "scheme_crisis",
               "scheme_hazard")


def _keyword_counts(cards: list[dict], words) -> dict[str, int]:
    import re as _re

    out: dict[str, int] = {}
    for word in words:
        rx = _re.compile(rf"\b{_re.escape(word)}\b", _re.I)
        n = sum(c["quantity"] for c in cards if rx.search(c.get("text") or ""))
        if n:
            out[word] = n
    return out


def _span(cards: list[dict], field_: str) -> dict | None:
    values = [c[field_] for c in cards if c.get(field_) is not None]
    return {"min": min(values), "max": max(values)} if values else None


def _threat(card: dict, players: int) -> int:
    """`*_fixed` means the value does not scale with player count (§4.6)."""
    base = card.get("base_threat") or 0
    if card.get("base_threat_fixed"):
        return base
    return base * players


def _minions(cards: list[dict], players: int) -> dict:
    rows = [c for c in cards if c["type_code"] == "minion"]
    return {
        "rows": len(rows),
        "copies": sum(c["quantity"] for c in rows),
        "health": _span(rows, "health"),
        "attack": _span(rows, "attack"),
        "scheme": _span(rows, "scheme"),
        "scales_per_hero": sum(1 for c in rows if c.get("health_per_hero")),
        "keywords": _keyword_counts(rows, MINION_KEYWORDS),
        "cards": [{"code": c["code"], "name": c["name"],
                   "quantity": c["quantity"]} for c in rows],
    }


def _treacheries(cards: list[dict]) -> dict:
    rows = [c for c in cards if c["type_code"] == "treachery"]
    copies = sum(c["quantity"] for c in rows)
    surge = _keyword_counts(rows, ("surge",)).get("surge", 0)
    return {
        "rows": len(rows),
        "copies": copies,
        "surge_copies": surge,
        "surge_rate": (surge / copies) if copies else 0.0,
        "cards": [{"code": c["code"], "name": c["name"],
                   "quantity": c["quantity"]} for c in rows],
    }


def _side_schemes(cards: list[dict], players: int) -> dict:
    rows = [c for c in cards if c["type_code"] == "side_scheme"]
    icons = {f.replace("scheme_", ""):
             sum((c.get(f) or 0) * c["quantity"] for c in rows)
             for f in ICON_FIELDS}
    return {
        "rows": len(rows),
        "copies": sum(c["quantity"] for c in rows),
        "threat_total": sum(_threat(c, players) * c["quantity"] for c in rows),
        "icons": {k: v for k, v in icons.items() if v},
        "cards": [{"code": c["code"], "name": c["name"],
                   "quantity": c["quantity"],
                   "threat": _threat(c, players)} for c in rows],
    }
```

In `profile`, before the `return`:

```python
    minions = _minions(cards, scenario.players)
    treacheries = _treacheries(cards)
    side_schemes = _side_schemes(cards, scenario.players)
    acceleration = sum((c.get("scheme_acceleration") or 0) * c["quantity"]
                       for c in cards)
```

and add to the returned dict:

```python
        "minions": minions,
        "treacheries": treacheries,
        "side_schemes": side_schemes,
        "scheme_pressure": {"acceleration_icons": acceleration},
        "keywords": _keyword_counts(cards, MINION_KEYWORDS + ("surge",)),
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_assess.py -v`
Expected: PASS

- [ ] **Step 5: Gate against the real corpus**

```bash
uv run python -c "
import json
from mc_jarvis import index, paths, assess
conn = index.connect(paths.db_path())
s = assess.resolve(conn, 'rhino', modular=[], players=2)
p = assess.profile(conn, s)
print(json.dumps({k: p[k] for k in ('deck_size','boost','minions','treacheries','side_schemes')}, indent=1)[:1400])
"
```

**Gate.** Rhino at 2 players, Standard, no modulars: deck size **22**, minions **4 copies** (Hydra Mercenary ×2, Sandman, Shocker), treacheries **12 copies**, side schemes **2**. `guard` must be **2** (Hydra Mercenary ×2) and `toughness` **1**. Work any mismatch out by hand from the set list in §5 before touching the code.

- [ ] **Step 6: Commit**

```bash
git add src/mc_jarvis/assess.py tests/test_assess.py
git commit -m "feat: minion, treachery, side-scheme and keyword profiles"
```

---

## Task 8: Growing decks, the CLI, and the skill

Implements §14.9 and §6, and teaches the model about them.

**Files:**
- Modify: `src/mc_jarvis/assess.py`, `src/mc_jarvis/cli.py`, `src/mc_jarvis/init.py`, `src/mc_jarvis/update.py`, `skill/mc-jarvis/SKILL.md`
- Test: `tests/test_assess.py`, `tests/test_skill_install.py`

**Interfaces:**
- Produces: `assess.trajectory(conn, scenario) -> list[dict]`, `assess.handle(args) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assess.py — append
def test_a_growing_scenario_reports_the_opening_and_grown_decks(conn):
    """§14.9: The Hood, Mojo and Dark Beast add modular sets DURING play.
    A single profile is the wrong answer, so report the trajectory."""
    conn.execute("INSERT INTO sets (code, name, card_set_type_code) "
                 "VALUES ('pool1', 'Pool One', 'modular')")
    conn.execute("INSERT INTO cards (code, name, type_code, set_code, "
                 "quantity, boost, text, traits) VALUES "
                 "('p1','Extra','treachery','pool1',4,3,'','')")
    conn.execute("INSERT INTO encounter_role (code, role, returns_to_deck, "
                 "decided_by) VALUES ('p1','deck',1,'type')")
    conn.commit()
    s = assess.resolve(conn, "rhino", modular=[])
    s.pool = ["pool1"]
    steps = assess.trajectory(conn, s)
    assert [x["added"] for x in steps] == [0, 1]
    assert steps[0]["deck_size"] < steps[1]["deck_size"]


def test_a_fixed_scenario_reports_one_step(conn):
    steps = assess.trajectory(conn, assess.resolve(conn, "rhino", modular=[]))
    assert len(steps) == 1
    assert steps[0]["added"] == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_assess.py -k trajectory -v`
Expected: FAIL — `AttributeError: … has no attribute 'trajectory'`

- [ ] **Step 3: Implement the trajectory and the CLI handler**

```python
def trajectory(conn, scenario: Scenario) -> list[dict]:
    """The deck at each stage of growth (§14.9).

    Scenarios whose pool is empty get one entry - the deck they start and
    end with. For the three that grow, report the opening deck and the
    fully-grown one: two exact profiles, and no statistic that needs a
    caveat. Predicting how far a game goes would be simulation, which §1
    rules out.
    """
    steps = [0] if not scenario.pool else [0, len(scenario.pool)]
    out = []
    for k in steps:
        entry = profile(conn, scenario, added=k)
        entry["added"] = k
        out.append(entry)
    return out


def handle(args) -> int:
    from .cards import _open
    from .cli import emit

    conn = _open()
    try:
        scenario = resolve(
            conn, args.villain, modular=args.modular, players=args.players,
            difficulty=args.difficulty, heroic=args.heroic,
            nemesis=args.nemesis or ())
    except UnknownScenario as exc:
        print(f"mc-jarvis assess: {exc}")
        return 1

    steps = trajectory(conn, scenario)
    if args.json:
        emit({"scenario": scenario.villain_set, "steps": steps}, as_json=True)
        return 0

    first = steps[0]
    label = {"recommended": " (recommended, not required)",
             "open": " (you choose these)",
             "random": " (drawn at random)"}.get(scenario.modular_kind, "")
    print(f"{scenario.villain_set} - {scenario.difficulty}, "
          f"{scenario.players} player(s)")
    print(f"  modular sets: {', '.join(scenario.modulars) or 'none'}{label}")
    for step in steps:
        when = "opening deck" if step["added"] == 0 else \
            f"after {step['added']} set(s) shuffled in"
        b = step["boost"]
        print(f"\n  {when}: {step['deck_size']} cards")
        print(f"    boost: mean {b['mean']:.2f} over {b['over']} cards, "
              f"{b['star_copies']} with a star icon")
        print(f"    histogram: " + "  ".join(
            f"{k}:{v}" for k, v in b["histogram"].items()))
        m, t, ss = step["minions"], step["treacheries"], step["side_schemes"]
        print(f"    minions {m['copies']}, treacheries {t['copies']} "
              f"({t['surge_rate']:.0%} surge), side schemes {ss['copies']}")
        if m["keywords"]:
            print("    minion keywords: " + ", ".join(
                f"{k} {v}" for k, v in sorted(m["keywords"].items())))
    return 0
```

- [ ] **Step 4: Wire the CLI**

In `cli.build_parser`, after the `rulings` block:

```python
    asr = _leaf(sub, "assess", "what a scenario throws at you")
    asr.add_argument("villain")
    asr.add_argument("--modular", action="append",
                     help="override the scenario's default modular sets")
    asr.add_argument("--players", type=int, default=1)
    asr.add_argument("--difficulty", default="standard",
                     choices=list(assess_difficulties()))
    asr.add_argument("--heroic", type=int, default=0)
    asr.add_argument("--nemesis", action="append")
```

with, at the top of `cli.py`:

```python
def assess_difficulties():
    from .assess import DIFFICULTIES
    return DIFFICULTIES
```

and in `_dispatch`:

```python
    if name == "assess":
        from . import assess
        return assess.handle(args)
```

- [ ] **Step 5: Wire the build**

In `init.rebuild_index`, after `counts["timing_triggers"] = timing.build(conn)`:

```python
    from . import encounterdeck
    counts.update(encounterdeck.build(conn))
    counts.update(encounterdeck.build_scenarios(conn))
    problems = encounterdeck.audit(conn) + encounterdeck.scenario_gate(conn)
    if problems:
        # Not fatal: card and rules commands are unaffected. But every
        # `assess` number would be computed over a wrong denominator, so
        # say which scenario rather than serving it silently.
        print("WARNING: scenario data is incomplete; `assess` may report "
              "wrong numbers for these:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
```

Add `"scenarios_incomplete": json.dumps(problems)` to the `build_meta` rows, and surface it in `update.status` beside `timing_broken`.

- [ ] **Step 6: Teach the skill**

Add to `SKILL.md`'s command table:

```markdown
| what a scenario throws at you | `mc-jarvis assess <villain> [--modular --players --difficulty]` |
```

and a section:

```markdown
## Scenario threat profiles

`mc-jarvis assess <villain>` reports what a scenario's encounter deck
holds: size, boost curve, minions, treacheries, side schemes, keywords.
Every number names the cards behind it, so cite rather than assert.

`--modular` **replaces** the scenario's defaults rather than adding to
them: a player naming modulars is describing the game on their table.

Three things to carry into any answer:

- **Some scenarios grow while you play.** The Hood, Mojo and Dark Beast
  shuffle in modular sets mid-game, so `assess` reports the opening deck
  *and* the fully-grown one. Quote both — a single average is wrong for
  most of the game. The Hood needs `--modular`, because the player picks
  its seven sets and nothing can infer them.
- **Difficulty changes the numbers.** Omitting the difficulty set
  understates the boost curve; Expert's three cards average boost 2.3.
- **Coverage is bounded by marvelcdb.** If `assess` says a villain is not
  in the card data, that is the honest answer — the scenario may be
  perfectly playable and simply absent upstream. Do not substitute a
  similar villain.
```

- [ ] **Step 7: Run everything**

Run: `uv run pytest -q`
Expected: PASS, including `test_the_skill_names_every_command_a_player_would_ask_for`, which fails if `assess` is missing from `SKILL.md`.

```bash
uv run mc-jarvis update
uv run mc-jarvis assess rhino --players 2
uv run mc-jarvis assess dark_beast
uv run mc-jarvis assess the_hood
```

Expected: `rhino` prints one deck; `dark_beast` prints an opening and a grown deck; `the_hood` refuses and asks for `--modular`.

- [ ] **Step 8: Commit**

```bash
git add src/mc_jarvis/assess.py src/mc_jarvis/cli.py src/mc_jarvis/init.py \
        src/mc_jarvis/update.py skill/ tests/
git commit -m "feat: mc-jarvis assess, with growing-deck trajectories"
```

---

## Done criteria

- [ ] `uv run pytest tests/ -v` passes, unit and integration
- [ ] `mc-jarvis assess rhino --modular '' --players 2` matches the corrected hand count: **24** cards, boost total **23** (the original 22/19 was the plan's own arithmetic error — see the Task 6 correction)
- [ ] all four gates return empty — `encounterdeck.audit`, `encounterdeck.scenario_gate`, `assess.back_face_gate`, `assess.growth_gate` — or every remaining entry is acknowledged in config with the sentence that justifies it
- [ ] `starts_in_play` with `returns_to_deck = 1` is exactly 3 — the `[[Setting]]` environments
- [ ] `other_deck` is **6**. The plan said "at least 15"; that came from a regex counting every *mention* of `[[X]] deck` rather than membership, and 15 included cards that merely name the infinity stone deck
- [ ] printed surge on encounter-deck cards is **80**, against 261 mentions
- [ ] `mc-jarvis assess the_hood` refuses and names `--modular`
- [ ] `mc-jarvis assess bullseye` says the scenario is not in the card data
- [ ] `git status` clean; no fetched artifact tracked

## Deliberately not in this plan

- **Part 2** (§9) — needs `deck fetch` / `deck check`.
- **Heroic levels** (§10) — the modifier is prose in a rules insert and has not been read. `--heroic` is accepted and recorded, and changes nothing until it is.
- **Campaign mode** (§10) — scope undetermined; may not belong in this spec.
- **Nemesis arrival rate** (§10) — `--nemesis` folds the set in without modelling how often it arrives, because the Standard III timer mechanism is unverified.
- **The three `Chief … Officer` environments** (§14.6) — treated as `starts_in_play`, `returns_to_deck = 0`. Unverified; the user is checking whether anything discards them.
