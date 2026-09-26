# Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mc-jarvis safe to announce to the Marvel Champions community: no silently wrong numbers, no lost user data on update, working on Windows and in Claude Desktop, and a README that matches the tool.

**Architecture:** Five phases. Correctness fixes in `assess` and `index`; Windows support at the three places the platform shows through (output encoding, the data directory, the launchers) plus a CI matrix that proves it; a Python bundle builder replacing the bash one so the release artifact is built the same way everywhere; documentation; then release, soft launch and announcement, which are mostly the user's.

**Tech Stack:** Python ≥3.10, SQLite (FTS5), PyYAML, pypdf, hatchling, uv, pytest, GitHub Actions. POSIX `sh` and Windows `cmd` for the two launchers.

**Spec:** No separate spec document. The scope below was agreed in session on 2026-09-26 and is quoted in full under **Scope**. Background: `docs/superpowers/specs/2026-08-22-scenario-assessment-design.md` §5 (the acknowledged set-aside residue), §14.29 (what the live trials found), §14.30 (heroic).

## Global Constraints

- **Distribution rule:** the repository ships code and configuration only - no card text, rules text, PDFs or built index, *including in comments, docstrings and config*. Card **names** are functional identification and are allowed; card **sentences** are not. Run `uv run python -m mc_jarvis.policy` before every commit and read its exit status directly - never through a pipe, which reports the pipe's status instead.
- `skill/mc-jarvis/SKILL.md` stays under 500 lines (`tests/test_skill_install.py::test_skill_md_stays_under_the_length_limit`). It is at 499 now: any line added there removes one elsewhere, named in the step.
- CI runs `uv run pytest -q -m "not integration"` with **no built index**. Rehearse with `rm -rf /tmp/empty && XDG_DATA_HOME=/tmp/empty uv run pytest -q -m "not integration"`. Tests needing the real corpus take the `real_index` fixture - never `paths.db_path()`.
- After every push: `gh run list --limit 1` until the run for *that* commit title completes, and report its conclusion. Do not poll faster than every 20 seconds; the unauthenticated API rate-limits per IP.
- Commit messages end with the session's attribution lines (see the latest system reminder). No other co-author lines.
- No new runtime dependencies. `requires-python = ">=3.10"` stays.
- Messages that name a command use `paths.invocation()`, never a literal `mc-jarvis` (`tests/test_paths.py::test_no_message_hardcodes_the_installed_name`).
- Outward-facing actions - pushing a release tag, anything posted publicly - happen only after the user says so in chat for that specific action.

## Review Focus

1. **A Windows `python3` that is the Microsoft Store stub.** `command -v python3` finds it; running it opens the Store and exits non-zero. The shell launcher must skip a candidate that does not run. Pinned in Task 6.
2. **Paths with spaces**, which on Windows means most user folders (`C:\Users\Jay Atkinson\...`). Both launchers must quote correctly. Pinned in Task 6, on POSIX and on Windows CI.
3. **A restored collection naming a pack that upstream renamed or removed.** Carrying the collection across a reset must not silently narrow every `--owned` search to nothing; `collection show` names the codes the index no longer knows. Pinned in Task 2.
4. **An agent reading output through a pipe on Windows**, where Python before 3.15 encodes with the ANSI code page and raises on anything outside it. Pinned in Task 3.
5. **Linux and macOS users with an existing index.** The Windows data-directory branch must not move theirs. Pinned in Task 4.

---

## Scope

As agreed:

- **Phase 1, correctness:** acknowledged setup removals surface as `assess` caveats; a recorded collection survives a schema reset.
- **Phase 2, Windows:** UTF-8 output; a `mc-jarvis.cmd` launcher; the data directory under `%LOCALAPPDATA%`; Windows and macOS in CI; LF line endings for the shell launcher; a human ground-zero test on the user's Windows machine.
- **Phase 2b, Claude Desktop** (added by the user mid-planning): set-up instructions and a test, for both Desktop's Claude Code sessions and Desktop's own skill upload.
- **Phase 3, README truth pass:** Status section; per-harness unzip locations; what has been tested; prerequisites and download size.
- **Phase 4:** v0.3.0; soft launch with two or three testers; GitHub Issues with a bug template.
- **Phase 5:** a demo and an announcement draft.
- **Out of scope:** campaign mode, upstream typo PRs, the pack-size coverage check.

Two things found while planning, folded into the owning tasks:

- **A locally built skill bundle contains a second copy of the skill.** In a checkout, `src/mc_jarvis/_bundled/` holds gitignored development symlinks, one of them to the whole `skill/` directory, and the bash builder copies the package with `cp -RL`, following them. CI builds from a clean checkout so published zips are unaffected, but a local build and a release build differ, and a harness that scans skills recursively would find two. Task 5.
- **The wheel ships `_bundled/.gitignore`.** Task 5.

---

## Phase 1 - correctness

### Task 1: Acknowledged setup removals become caveats

`assess juggernaut` reports 29 cards. Juggernaut's Helmet starts attached to Juggernaut at setup, so 28 are in the deck, and nothing says so. Sixteen `acknowledged` entries in `config/encounter_setup.yaml` carry `affects_deck: true`; nothing in `src/` reads that flag, and `caveats()` reads only `adds_during_play`. The spec (§5) puts the residue at about 29 cards across roughly ten scenarios.

A single count per entry would be wrong for four of them: Mysterio and Nebula remove cards per player, Absorbing Man and On the Run remove a card chosen at random. So each entry gets a short hand-written `deck_note`: what the count includes that setup takes out, with a number only where setup fixes one.

**Files:**
- Modify: `config/encounter_setup.yaml` (the 16 entries listed in Step 6)
- Modify: `src/mc_jarvis/assess.py` - `caveats()`
- Test: `tests/test_assess.py`

**Interfaces:**
- Produces: an `acknowledged.<set>.deck_note: str` config field, required whenever `affects_deck: true`.
- Consumes: `caveats(scenario, sets, config=None, *, conn=None) -> list[str]` (existing signature, unchanged).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assess.py`:

```python
# --- acknowledged setup removals (spec §5) ------------------------------

def test_every_deck_affecting_acknowledgment_says_what_it_takes():
    """`affects_deck: true` was read by nothing, so a known overstatement
    reached no one. Each such entry must say, in words a player can use,
    what the count includes that setup removes."""
    from mc_jarvis.encounterdeck import load_config

    ack = load_config().get("acknowledged") or {}
    missing = sorted(k for k, v in ack.items()
                     if (v or {}).get("affects_deck")
                     and not ((v or {}).get("deck_note") or "").strip())
    assert not missing, f"no deck_note: {missing}"


def test_an_acknowledged_removal_reaches_the_player():
    from mc_jarvis import assess

    sc = assess.Scenario(scenario_set="juggernaut")
    note = "Juggernaut's Helmet starts attached, so the deck is 1 card smaller"
    config = {"acknowledged": {"juggernaut": {
        "affects_deck": True, "deck_note": note}}}
    assert any(note in c for c in assess.caveats(sc, ["juggernaut"],
                                                 config=config))
    # Only for the scenario on the table.
    assert not any(note in c for c in assess.caveats(sc, ["rhino"],
                                                     config=config))
    # And only when the entry says the deck is affected.
    config["acknowledged"]["juggernaut"]["affects_deck"] = False
    assert not any(note in c for c in assess.caveats(sc, ["juggernaut"],
                                                     config=config))


def test_juggernaut_names_its_helmet(real_index):
    from mc_jarvis import assess

    step = assess.profile(real_index, assess.resolve(real_index, "juggernaut"))
    assert any("Juggernaut's Helmet" in c for c in step["caveats"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_assess.py -k "acknowledg or helmet" -p no:randomly`
Expected: 3 failures - `no deck_note: ['absorbing_man', ...]`, and the two caveat assertions.

- [ ] **Step 3: Implement the caveat**

In `src/mc_jarvis/assess.py`, `caveats()`, immediately before `return out`:

```python
    # Acknowledged in config because the set-aside rule cannot read the
    # Setup wording - so the cards they name are still counted below.
    # `affects_deck` was recorded for every one of them and read by
    # nothing, which left a known overstatement invisible to the only
    # person who needed it.
    for code, entry in (config.get("acknowledged") or {}).items():
        entry = entry or {}
        if entry.get("affects_deck") and code in sets and entry.get("deck_note"):
            out.append("setup takes cards out of this deck that the count "
                       "below still includes: "
                       + " ".join(entry["deck_note"].split()))
```

- [ ] **Step 4: Run the synthetic test to verify it passes**

Run: `uv run pytest -q tests/test_assess.py -k "reaches_the_player" -p no:randomly`
Expected: PASS. The other two still fail until Step 6.

- [ ] **Step 5: Audit the sixteen entries**

For each entry, work out what `deck_cards` counts that setup takes out. This prints the data you need - the reason, the Setup block, and every counted card - to your terminal only. Nothing from it is committed except the note you write.

```bash
uv run python - <<'PY'
import re
from mc_jarvis.cards import _open
from mc_jarvis import assess, encounterdeck as ed
c = _open(); tag = re.compile(r"<[^>]+>")
ack = ed.load_config()["acknowledged"]; blocks = ed.setup_blocks(c)
for code, e in ack.items():
    if not e.get("affects_deck"): continue
    try: cards = assess.deck_cards(c, assess.resolve(c, code))
    except Exception as x: print(f"\n## {code}: cannot resolve ({x})"); continue
    print(f"\n## {code}\nreason: {' '.join(e['reason'].split())}")
    print("setup:", tag.sub('', blocks.get(code, '')))
    for x in cards:
        print(f"   {x['quantity']}x {x['name']} [{x['type_code']}, {x['role']}]")
PY
```

For each entry decide, from the Setup block and the counted list:
- **Which counted cards leave**: named, or picked out by trait or type ("every Board Member environment").
- **How many copies**: a fixed number, or *per player*, or *one chosen at random from N*.
- **Whether they are counted at all.** A villain stage or a card already outside the deck (role other than `deck`) is not in the count, so it does not belong in the note.

- [ ] **Step 6: Write the sixteen `deck_note`s**

Add `deck_note:` to each of: `absorbing_man`, `baron_zemo`, `brotherhood_of_badoon`, `enchantress_villain`, `hela`, `juggernaut`, `kang`, `magog`, `mysterio`, `nebula`, `on_the_run`, `red_skull`, `ronan`, `sandman`, `spiral`, `stryfe`.

Rules for each note:
- Name cards by **name**, never quote a card sentence (distribution rule).
- Say how much smaller the deck is: a number when setup fixes it; "1 per player" or "one of N, at random" when it does not. Never invent a number.
- If the audit shows the removed cards are **not** in the count (Step 5, last bullet), change `affects_deck` to `false` and write in `reason` why, instead of writing a note.
- One or two plain sentences, written for a player, not a maintainer.

Worked example - `juggernaut`, audited in session on 2026-09-24:

```yaml
  juggernaut:
    reason: >-
      An attachment is attached at setup and leaves the deck. The
      other named card is an ally, never an encounter-deck card.
      Re-read 2026-09-24 after upstream corrected that ally's name,
      which had been misspelled; the reason held.
    affects_deck: true
    deck_note: >-
      Juggernaut's Helmet starts attached to Juggernaut, so the deck is
      1 card smaller than shown.
    setup_digest: "4ed19699efeab2caf676a55d91733975"
```

Do **not** change any `setup_digest`: the digest covers the Setup wording, which this task does not touch.

- [ ] **Step 7: Run the tests, the audit gate and policy**

```bash
uv run pytest -q tests/test_assess.py -p no:randomly
uv run python -c "from mc_jarvis.cards import _open; from mc_jarvis import encounterdeck as ed; print(ed.audit(_open()) or 'audit clean')"
uv run python -m mc_jarvis.policy; echo "policy exit=$?"
```
Expected: all pass, `audit clean`, `policy exit=0`.

- [ ] **Step 8: Check what a player sees for two scenarios**

Run: `uv run mc-jarvis assess juggernaut | head -6` and `uv run mc-jarvis assess mysterio --players 3 | head -6`
Expected: a `NOTE:` line naming Juggernaut's Helmet; Mysterio's note says the removal scales with players, with no invented total.

- [ ] **Step 9: Commit**

```bash
git add config/encounter_setup.yaml src/mc_jarvis/assess.py tests/test_assess.py
git commit   # "fix: say which setup removals the deck count still includes"
```

### Task 2: A recorded collection survives a schema reset

`_reset_if_stale` (`src/mc_jarvis/index.py`) drops every table when `SCHEMA_VERSION` changes - `owned_packs` included. A collection is the one thing in the index the player typed rather than something derived from sources, so every release that bumps the schema silently empties it.

**Files:**
- Modify: `src/mc_jarvis/index.py` - `_reset_if_stale`, `connect`, new `USER_TABLES`, new `_restore`
- Modify: `src/mc_jarvis/collection.py` - new `unknown_owned`, used by `handle` for `show`
- Test: `tests/test_index.py`, `tests/test_collection.py`

**Interfaces:**
- Produces: `index.USER_TABLES: dict[str, tuple[str, ...]]`; `index._reset_if_stale(conn) -> dict[str, list[tuple]]` (was `-> bool`; its only caller is `connect`); `collection.unknown_owned(conn) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_index.py`:

```python
def test_a_schema_reset_keeps_the_players_collection(tmp_path):
    """A reset rebuilds everything derived from sources. The collection
    is not derived - the player typed it - and every release that bumps
    the schema used to empty it without a word."""
    from mc_jarvis import index

    db = tmp_path / "mc.sqlite"
    conn = index.connect(db)
    conn.execute("INSERT INTO owned_packs (pack_code) VALUES ('core')")
    conn.execute("INSERT INTO sets (code, name, card_set_type_code) "
                 "VALUES ('rhino', 'Rhino', 'villain')")
    conn.execute(f"PRAGMA user_version = {index.SCHEMA_VERSION - 1}")
    conn.commit()
    conn.close()

    conn = index.connect(db, rebuild=True)
    assert [r[0] for r in conn.execute("SELECT pack_code FROM owned_packs")] == ["core"]
    # The reset still happened: derived data is gone.
    assert conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 0
```

Append to `tests/test_collection.py`, using the file's own `_mkdb` helper (its `packs` table holds `core`, `sm` and `aos`):

```python
def test_a_collection_naming_a_vanished_pack_says_so(tmp_path):
    """After a reset carries the collection across, a pack renamed
    upstream would narrow every --owned search to nothing, silently."""
    conn = _mkdb(tmp_path)
    conn.execute("INSERT INTO owned_packs (pack_code) VALUES ('core')")
    conn.execute("INSERT INTO owned_packs (pack_code) VALUES ('gone_pack')")
    assert collection.unknown_owned(conn) == ["gone_pack"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_index.py tests/test_collection.py -k "reset_keeps or vanished" -p no:randomly`
Expected: FAIL - the collection comes back empty; `unknown_owned` does not exist.

- [ ] **Step 3: Carry user tables across the reset**

In `src/mc_jarvis/index.py`, above `_reset_if_stale`:

```python
# Tables holding what the player told us rather than anything derived
# from sources. A schema reset rebuilds everything derived; these are
# read before the drop and written back after the new schema exists.
# A future change to one of these tables' columns must migrate it here,
# or the restore fails loudly rather than dropping the player's data.
USER_TABLES: dict[str, tuple[str, ...]] = {
    "owned_packs": ("pack_code",),
}
```

Change `_reset_if_stale` to save before dropping and return what it saved. Keep the existing body; the changes are the return type, the save loop, and the two returns:

```python
def _reset_if_stale(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    ...  # existing docstring, plus: "Returns the user tables' rows, to
         # be restored once the new schema exists."
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return {}
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        " AND name NOT LIKE 'sqlite_%'")]
    kept = {name: [tuple(r) for r in conn.execute(
                f'SELECT {", ".join(cols)} FROM "{name}"')]
            for name, cols in USER_TABLES.items() if name in tables}
    ...  # existing drop loop, unchanged
    return kept
```

Add below it:

```python
def _restore(conn: sqlite3.Connection, kept: dict[str, list[tuple]]) -> None:
    for name, rows in kept.items():
        cols = USER_TABLES[name]
        conn.executemany(
            f'INSERT OR IGNORE INTO "{name}" ({", ".join(cols)}) '
            f'VALUES ({", ".join("?" * len(cols))})', rows)
    if kept:
        conn.commit()
```

And in `connect`:

```python
    kept = _reset_if_stale(conn) if rebuild else {}
    if not rebuild:
        _refuse_if_stale(conn)
    conn.executescript(schema.SCHEMA)
    _restore(conn, kept)
    return conn
```

- [ ] **Step 4: Report codes the index no longer knows**

In `src/mc_jarvis/collection.py`, after `owned_packs`:

```python
def unknown_owned(conn) -> list[str]:
    """Owned pack codes the index has no pack for.

    A collection outlives rebuilds, and upstream occasionally renames a
    pack. A code that matches nothing narrows every `--owned` search by
    that pack's cards, and nothing else would ever say why.
    """
    return [r["pack_code"] for r in conn.execute(
        "SELECT pack_code FROM owned_packs WHERE pack_code NOT IN "
        "(SELECT code FROM packs) ORDER BY pack_code")]
```

In `handle`, the plain-text `show` branch, replace the final `print(...)` / `return 0` with:

```python
        print(f"{len(owned)} pack(s): {', '.join(owned)}")
        lost = unknown_owned(conn)
        if lost:
            print(f"not in this index - renamed or removed upstream: "
                  f"{', '.join(lost)}. `{invocation()} collection set "
                  f"--replace <pack>...` re-records it.")
        return 0
```

And in the `--json` branch add `"unknown": unknown_owned(conn)` to the emitted dict.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q tests/test_index.py tests/test_collection.py -p no:randomly`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/mc_jarvis/index.py src/mc_jarvis/collection.py tests/test_index.py tests/test_collection.py
git commit   # "fix: a schema reset keeps the player's collection"
```

---

## Phase 2 - Windows

### Task 3: UTF-8 output on every platform

Agents read our output through a pipe. On Windows before Python 3.15, a pipe's encoding is the ANSI code page (cp1252 in the US), and `print` raises `UnicodeEncodeError` on any character outside it - mid-answer.

**Files:**
- Modify: `src/mc_jarvis/cli.py` - new `_utf8_streams`, called first in `main`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `cli._utf8_streams() -> None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_output_is_utf8_whatever_the_pipe_defaults_to(monkeypatch):
    """A Windows pipe defaults to the ANSI code page, which cannot encode
    a star or an arrow, so a card name could crash the command
    mid-answer. Output is UTF-8 on every platform."""
    import io
    import sys

    from mc_jarvis import cli

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    cli._utf8_streams()
    print("\u2605 \u2192 Coup de Gr\u00e2ce")
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").startswith("\u2605 \u2192")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest -q tests/test_cli.py -k utf8 -p no:randomly`
Expected: FAIL - `AttributeError: ... has no attribute '_utf8_streams'`.

- [ ] **Step 3: Implement**

In `src/mc_jarvis/cli.py`, above `main`:

```python
def _utf8_streams() -> None:
    """Write UTF-8 whatever the platform chose.

    An agent reads this program through a pipe, and on Windows a pipe
    defaults to the ANSI code page: a card name outside it raised
    UnicodeEncodeError halfway through an answer. A stream that cannot be
    reconfigured - one a test or a host replaced - is left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
```

First line of `main`:

```python
def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    args = parse_args(argv)
```

- [ ] **Step 4: Run the test and the CLI suite**

Run: `uv run pytest -q tests/test_cli.py -p no:randomly`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/mc_jarvis/cli.py tests/test_cli.py
git commit   # "fix: write UTF-8 whatever the pipe defaults to"
```

### Task 4: The data directory on Windows

`paths.data_dir()` returns `~/.local/share/mc-jarvis` everywhere. On Windows the conventional place is `%LOCALAPPDATA%\mc-jarvis`. No Windows user has an index yet, so nothing needs migrating. Platform is read from `sys.platform`, not `os.name`: tests must be able to fake it, and faking `os.name` breaks `pathlib`.

**Files:**
- Modify: `src/mc_jarvis/paths.py` - `data_dir`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_paths.py`:

```python
def test_windows_keeps_its_data_under_localappdata(monkeypatch, tmp_path):
    from mc_jarvis import paths

    for var in ("MC_JARVIS_DATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / "mc-jarvis"


def test_an_explicit_choice_still_wins_on_windows(monkeypatch, tmp_path):
    from mc_jarvis import paths

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path / "mine"))
    assert paths.data_dir() == tmp_path / "mine"


def test_linux_and_macos_indexes_do_not_move(monkeypatch):
    """Existing indexes live in ~/.local/share. A Windows branch that
    leaked onto another platform would orphan every one of them."""
    from pathlib import Path

    from mc_jarvis import paths

    for var in ("MC_JARVIS_DATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "/should/not/be/used")
    for platform in ("linux", "darwin"):
        monkeypatch.setattr("sys.platform", platform)
        assert paths.data_dir() == Path.home() / ".local" / "share" / "mc-jarvis"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_paths.py -k "windows or localappdata or do_not_move" -p no:randomly`
Expected: the first test FAILS (returns `~/.local/share/mc-jarvis`); the other two pass already.

- [ ] **Step 3: Implement**

In `src/mc_jarvis/paths.py`, `data_dir`, between the `XDG_DATA_HOME` branch and the final return:

```python
    # Windows keeps per-user application data under %LOCALAPPDATA%, and
    # that is where a Windows user - or their backup tool - looks.
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "mc-jarvis"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_paths.py -p no:randomly`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/mc_jarvis/paths.py tests/test_paths.py
git commit   # "feat: keep the index under %LOCALAPPDATA% on Windows"
```

### Task 5: Build the skill bundle in Python

Replace `tools/build-skill-bundle.sh` with `tools/build_skill_bundle.py`. A bash script cannot run the same way on a Windows CI runner (`bash` there can resolve to the WSL stub), and a Python builder can be imported by the tests directly. Two defects are fixed in the move: the development symlinks in `src/mc_jarvis/_bundled/` (including a link to the whole `skill/` directory) are excluded, so a local build matches a CI build; and no `.gitignore` ships in the bundle or the wheel.

**Files:**
- Create: `tools/build_skill_bundle.py`
- Delete: `tools/build-skill-bundle.sh`
- Modify: `.github/workflows/release.yml` - the "Archive the skill folder" step
- Modify: `pyproject.toml` - wheel `exclude`
- Modify: `tests/test_packaging.py` - the `bundle` fixture, and new tests

**Interfaces:**
- Produces: `build(out: Path, root: Path = ROOT) -> Path`, returning the bundle directory (`out / "mc-jarvis"`). Run as `python tools/build_skill_bundle.py <output-dir>`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_packaging.py`, replace the `bundle` fixture:

```python
def _builder():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_skill_bundle", ROOT / "tools" / "build_skill_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """Built by the same code the release runs, so this tests the
    deliverable rather than a second description of it."""
    return _builder().build(tmp_path_factory.mktemp("bundle"))
```

Append:

```python
def test_the_bundle_holds_exactly_one_skill(bundle):
    """A checkout's `_bundled/` links to the whole skill directory for
    development. Followed during the build, it put a second SKILL.md
    inside the package, and a harness that scans skills recursively
    would register the skill twice."""
    assert [p.relative_to(bundle).as_posix()
            for p in bundle.rglob("SKILL.md")] == ["SKILL.md"]


def test_the_bundle_and_wheel_carry_no_gitignore(bundle, built):
    assert not list(bundle.rglob(".gitignore"))
    assert not [n for n in _wheel_names(built) if n.endswith(".gitignore")]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_packaging.py -p no:randomly`
Expected: FAIL - `tools/build_skill_bundle.py` does not exist.

- [ ] **Step 3: Write the builder**

Create `tools/build_skill_bundle.py`:

```python
"""Assemble the self-contained skill folder a release attaches.

The skill folder holds the tool: SKILL.md beside the package that runs
it, so it can be dropped into a skills directory and used the way skills
that ship scripts normally are. Config goes to `_bundled`, where
`paths.py` looks first - the same place a wheel puts it.

Python rather than a shell script so it runs the same on every platform
the tests run on, and so the tests can import it rather than describe it.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A checkout's `_bundled/` holds gitignored development symlinks - one of
# them to the whole skill directory - so it is rebuilt below rather than
# copied. Following those links is how a local build came to carry a
# second SKILL.md that a clean CI build did not.
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".gitignore",
                               "_bundled")


def build(out: Path, root: Path = ROOT) -> Path:
    bundle = Path(out) / "mc-jarvis"
    if bundle.exists():
        shutil.rmtree(bundle)
    # `symlinks=False` copies what a link points at: a checkout keeps
    # SKILL.md as a symlink into the repository, which would unpack on
    # someone else's machine pointing at nothing.
    shutil.copytree(root / "skill" / "mc-jarvis", bundle,
                    symlinks=False, ignore=_SKIP)
    package = bundle / "scripts" / "mc_jarvis"
    shutil.copytree(root / "src" / "mc_jarvis", package,
                    symlinks=False, ignore=_SKIP)
    bundled = package / "_bundled"
    bundled.mkdir()
    for config in sorted((root / "config").glob("*.yaml")):
        shutil.copyfile(config, bundled / config.name)
    shutil.copyfile(root / "LICENSE", bundle / "LICENSE")
    return bundle


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_skill_bundle.py <output-dir>")
    print(build(Path(sys.argv[1])))
```

Delete the shell builder: `git rm tools/build-skill-bundle.sh`.

`copytree` preserves the launcher's executable bit (`copy2` copies mode bits), so `scripts/mc-jarvis` stays executable in the bundle. `test_the_bundle_runs_with_nothing_installed` would fail if it did not.

- [ ] **Step 4: Exclude the `.gitignore` from the wheel**

In `pyproject.toml`, under `[tool.hatch.build.targets.wheel]`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/mc_jarvis"]
# The `_bundled/.gitignore` keeps development symlinks out of git. It is
# not part of the package.
exclude = ["src/mc_jarvis/_bundled/.gitignore"]
```

- [ ] **Step 5: Point the release workflow at the new builder**

In `.github/workflows/release.yml`, the "Archive the skill folder, tool included" step's `run:` becomes:

```yaml
        run: |
          uv run python tools/build_skill_bundle.py bundle
          ( cd bundle && zip -qr "../dist/mc-jarvis-skill-${version}.zip" mc-jarvis )
          unzip -l "dist/mc-jarvis-skill-${version}.zip" | tail -3
```

Also update any mention of `build-skill-bundle.sh` in `README.md` (`grep -rn "build-skill-bundle" README.md docs tools .github`).

- [ ] **Step 6: Run the packaging tests**

Run: `uv run pytest -q tests/test_packaging.py -p no:randomly`
Expected: all pass, including the two new tests and the existing `test_the_bundle_runs_with_nothing_installed`.

- [ ] **Step 7: Commit**

```bash
git add tools/build_skill_bundle.py pyproject.toml .github/workflows/release.yml tests/test_packaging.py README.md
git commit   # "fix: build the skill bundle in Python, without dev symlinks"
```

### Task 6: Launchers that work on Windows

Two launchers, because Windows users arrive two ways. **Claude Code on Windows runs its commands in Git Bash**, so it runs the shell launcher `scripts/mc-jarvis` - which calls `python3`, a name a Windows Python usually does not answer to, and which may be the Microsoft Store stub. **cmd, PowerShell and other harnesses** need `scripts\mc-jarvis.cmd`. The `.cmd` rather than a `.ps1`, because Windows blocks unsigned PowerShell scripts by default.

**Files:**
- Modify: `skill/mc-jarvis/scripts/mc-jarvis` (shell launcher)
- Create: `skill/mc-jarvis/scripts/mc-jarvis.cmd` (CRLF line endings)
- Create: `.gitattributes`
- Modify: `skill/mc-jarvis/SKILL.md` (line 93, and one line trimmed)
- Test: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `MC_JARVIS_INVOKED_AS` (read by `paths.invocation()`), `MC_JARVIS_PYTHON` (existing override).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_packaging.py`:

```python
import shutil as _shutil


def _fake_python_dir(tmp_path, *, stub_python3: bool):
    """A PATH holding only what the shell launcher needs: `sh` (its
    `#!/usr/bin/env sh` looks it up on PATH), `dirname`, `uname`, and a
    `python` that runs this test's interpreter. With
    `stub_python3`, also a `python3` that exits the way the Microsoft
    Store stub does."""
    bindir = tmp_path / "bin dir"          # a space, on purpose
    bindir.mkdir()
    for tool in ("sh", "dirname", "uname"):
        (bindir / tool).symlink_to(_shutil.which(tool))
    python = bindir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    if stub_python3:
        stub = bindir / "python3"
        stub.write_text("#!/bin/sh\nexit 9009\n")
        stub.chmod(0o755)
    return bindir


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell launcher")
def test_the_shell_launcher_skips_a_python_that_does_not_run(bundle, tmp_path):
    """On Windows `python3` is often the Microsoft Store stub: found on
    PATH, opens the Store, exits non-zero. A launcher that trusted
    `command -v` would hand every command to it."""
    home = tmp_path / "a home with spaces"
    _shutil.copytree(bundle, home / "mc-jarvis", symlinks=False)
    launcher = home / "mc-jarvis" / "scripts" / "mc-jarvis"
    bindir = _fake_python_dir(tmp_path, stub_python3=True)
    got = subprocess.run(
        [str(launcher), "card", "search", "tackle"],
        capture_output=True, text=True,
        env={"PATH": str(bindir), "HOME": str(tmp_path),
             "MC_JARVIS_DATA": str(tmp_path / "no-index")})
    # It ran mc_jarvis - which found no index - rather than the stub.
    assert "no index found" in (got.stdout + got.stderr), got.stderr
    # And named the launcher the reader typed, space and all.
    assert str(launcher) in (got.stdout + got.stderr)


def test_the_windows_launcher_ships_with_crlf(bundle):
    """cmd.exe misreads labels and `goto` in a batch file with LF
    endings. `.gitattributes` fixes the checkout; this pins the bundle."""
    data = (bundle / "scripts" / "mc-jarvis.cmd").read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
def test_the_windows_launcher_runs_from_a_folder_with_spaces(bundle, tmp_path):
    home = tmp_path / "a home with spaces"
    _shutil.copytree(bundle, home / "mc-jarvis", symlinks=False)
    launcher = home / "mc-jarvis" / "scripts" / "mc-jarvis.cmd"
    got = subprocess.run(
        [str(launcher), "card", "search", "tackle"],
        capture_output=True, text=True,
        env={**os.environ, "MC_JARVIS_PYTHON": sys.executable,
             "MC_JARVIS_DATA": str(tmp_path / "no-index")})
    assert "no index found" in (got.stdout + got.stderr), got.stderr
    assert "mc-jarvis.cmd" in (got.stdout + got.stderr)
```

Add `import os` to the file's imports if it is not there.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_packaging.py -k "launcher" -p no:randomly`
Expected on Linux: the shell test FAILS (the launcher execs the stub `python3`), the CRLF test FAILS (`mc-jarvis.cmd` does not exist), the Windows test is skipped.

- [ ] **Step 3: Rewrite the shell launcher**

Replace `skill/mc-jarvis/scripts/mc-jarvis` entirely (keep it executable; LF endings):

```sh
#!/usr/bin/env sh
# Run mc-jarvis from this skill folder.
#
# A release bundles the package beside this script, at scripts/mc_jarvis,
# so the skill folder holds the tool rather than pointing at one installed
# elsewhere. When the package is not here - a plain `install-skill` copies
# the skill and nothing else - this falls through to an installed
# `mc-jarvis`, so the same script works either way.
#
# Also the launcher Windows users reach first: Claude Code on Windows runs
# commands in Git Bash. cmd and PowerShell use mc-jarvis.cmd beside this.
#
# Dependencies are ordinary Python ones: PyYAML always, pypdf for `init`,
# `rulings` and `doctor`. `mc-jarvis doctor` names anything missing.
set -e
here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# The interpreter. `python3` is the POSIX name; a Windows Python usually
# answers to `python` or to the `py` launcher, and a `python3` found there
# may be the Microsoft Store stub, which opens the Store instead of
# running. So a candidate is chosen only once it has actually run.
python=""
pyflag=""
if [ -n "$MC_JARVIS_PYTHON" ]; then
    python="$MC_JARVIS_PYTHON"
else
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 \
                && "$candidate" -c "import sys" >/dev/null 2>&1; then
            python="$candidate"
            break
        fi
    done
    if [ -z "$python" ] && command -v py >/dev/null 2>&1 \
            && py -3 -c "import sys" >/dev/null 2>&1; then
        python="py"
        pyflag="-3"
    fi
fi
if [ -z "$python" ]; then
    echo "mc-jarvis: no working Python 3 found (tried python3, python, py -3)" >&2
    exit 127
fi

# Under Git Bash a native Windows Python reads PYTHONPATH as a Windows
# path list: backslashes, separated by ';'.
sep=":"
here_py="$here"
case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*) sep=";"; here_py="$(cygpath -w "$here")" ;;
esac

# `MC_JARVIS_INVOKED_AS` is how the reader typed it, so a message telling
# them what to run next names something that exists.
if [ -d "$here/mc_jarvis" ]; then
    MC_JARVIS_INVOKED_AS="$0" \
    PYTHONPATH="$here_py${PYTHONPATH:+$sep$PYTHONPATH}" \
        exec "$python" $pyflag -m mc_jarvis "$@"
fi

if command -v mc-jarvis >/dev/null 2>&1; then
    exec mc-jarvis "$@"
fi

exec "$python" $pyflag -m mc_jarvis "$@"
```

`$pyflag` is unquoted on purpose: empty, it disappears; `-3`, it is one word.

- [ ] **Step 4: Write the Windows launcher, with CRLF endings**

Write it with Python so the line endings are exact:

```bash
uv run python - <<'PY'
from pathlib import Path
lines = [
    "@echo off",
    "rem Run mc-jarvis from this skill folder (Windows cmd and PowerShell).",
    "rem A release bundles the package beside this file, at mc_jarvis\\.",
    "rem Without it, falls through to an installed mc-jarvis.",
    "rem MC_JARVIS_INVOKED_AS is how the reader typed it, so a message naming",
    "rem the next command names one that exists.",
    "setlocal",
    'set "MC_JARVIS_INVOKED_AS=%~f0"',
    'if not exist "%~dp0mc_jarvis\\__main__.py" goto installed',
    'set "PYTHONPATH=%~dp0;%PYTHONPATH%"',
    "goto choose",
    ":installed",
    "where mc-jarvis >nul 2>nul",
    "if errorlevel 1 goto choose",
    "mc-jarvis %*",
    "exit /b",
    ":choose",
    "if defined MC_JARVIS_PYTHON goto custom",
    "rem The py launcher first: `python` may be the Microsoft Store stub.",
    "where py >nul 2>nul",
    "if errorlevel 1 goto plain",
    "py -3 -m mc_jarvis %*",
    "exit /b",
    ":custom",
    '"%MC_JARVIS_PYTHON%" -m mc_jarvis %*',
    "exit /b",
    ":plain",
    "python -m mc_jarvis %*",
    "exit /b",
]
Path("skill/mc-jarvis/scripts/mc-jarvis.cmd").write_bytes(
    ("\r\n".join(lines) + "\r\n").encode("ascii"))
PY
```

- [ ] **Step 5: Pin line endings in git**

Create `.gitattributes`:

```
# The shell launcher must keep LF: a Windows checkout with CRLF breaks it
# under Git Bash. The batch launcher must keep CRLF: cmd.exe misreads
# labels and goto in a batch file with LF endings.
skill/mc-jarvis/scripts/mc-jarvis      text eol=lf
*.sh                                   text eol=lf
*.cmd                                  text eol=crlf
```

Then renormalise and confirm: `git add --renormalize . && git status --short` - only the files this task touches should appear.

- [ ] **Step 6: Tell the agent about the Windows launcher**

In `skill/mc-jarvis/SKILL.md`, replace line 93:

```
If `mc-jarvis` is not on PATH, it is `scripts/mc-jarvis` in this folder.
```

with:

```
If `mc-jarvis` is not on PATH, it is `scripts/mc-jarvis` in this folder
(`scripts\mc-jarvis.cmd` from cmd or PowerShell).
```

That adds a line; the file must stay under 500. Remove one by merging the two sentences of the Setup check paragraph (around line 77) - find it with `grep -n "nobody has run" skill/mc-jarvis/SKILL.md` - so the paragraph reads:

```
If any command reports "no index", nobody has run `init` yet. The tool is
in this folder, so run it yourself rather than handing the user a command:
```

Check: `wc -l skill/mc-jarvis/SKILL.md` prints 499.

- [ ] **Step 7: Run the tests**

```bash
uv run pytest -q tests/test_packaging.py tests/test_skill_install.py tests/test_paths.py -p no:randomly
uv run python -m mc_jarvis.policy; echo "policy exit=$?"
```
Expected: all pass (the Windows-only test skipped on Linux), `policy exit=0`.

- [ ] **Step 8: Commit**

```bash
git add skill/mc-jarvis/scripts/mc-jarvis skill/mc-jarvis/scripts/mc-jarvis.cmd .gitattributes skill/mc-jarvis/SKILL.md tests/test_packaging.py
git commit   # "feat: launchers that work on Windows"
```

### Task 7: Windows and macOS in CI

Tasks 3-6 are proven on Linux only until CI runs them where they matter. The release workflow already calls `checks.yml`, so once the matrix is in, no release can publish without passing on all three.

**Files:**
- Modify: `.github/workflows/checks.yml` - the `unit` job
- Modify: whichever tests the matrix shows assume POSIX (Step 3)

- [ ] **Step 1: Add the matrix**

In `.github/workflows/checks.yml`, the `unit` job:

```yaml
  unit:
    # Everything that needs neither the network nor a built index - on
    # each platform a player might use. Windows is where the launchers,
    # the output encoding and the data directory actually differ.
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra dev
      - name: Unit tests
        run: uv run pytest -q -m "not integration"
      - name: Package contents
        run: uv run pytest -q -m integration tests/test_packaging.py
```

`distribution-rule` stays on `ubuntu-latest` only: it tests the repository's contents, which do not vary by platform.

- [ ] **Step 2: Push to a branch and read the results**

```bash
git switch -c ci-matrix
git add .github/workflows/checks.yml
git commit   # "ci: run the unit and packaging jobs on Windows and macOS"
git push -u origin ci-matrix
```

Wait for the run (see Global Constraints on polling), then list the failures: `gh run view <run-id> --log-failed`. If `gh` reports 401, ask the user to run `! gh auth login` - logs need authentication.

- [ ] **Step 3: Triage every failure into one of two kinds**

- **A real defect** - behaviour a Windows or macOS user would hit (a path built with `/` joined as a string, a text read without `encoding=`, a command that needs a POSIX tool). Fix the code, add a test that fails without the fix, keep the test running on every platform.
- **A test that assumes POSIX** - it builds a POSIX path, or makes a symlink (Windows needs privileges for that), or runs a shell script. Known candidates: `tests/test_skill_install.py::test_link_mode_symlinks`, and `tests/test_packaging.py::test_the_bundle_runs_with_nothing_installed` (it uses `bin/python` and a `/usr/bin:/bin` PATH). Make the test platform-aware where the behaviour exists on that platform - for the bundle test, `Scripts/python.exe` and the `.cmd` launcher on Windows - and skip it with a reason that names the assumption only where the behaviour itself does not exist there:

```python
@pytest.mark.skipif(sys.platform == "win32",
                    reason="creating a symlink needs admin rights or developer mode on Windows")
```

Never skip a test to make a real defect pass.

- [ ] **Step 4: Iterate until all three platforms are green**

Commit each fix with a message naming what a user would have hit, push, re-check. Then merge: `git switch main && git merge --ff-only ci-matrix && git push origin main && git branch -d ci-matrix && git push origin --delete ci-matrix`. Check CI on `main`.

### Task 8: Ground-zero install on Windows (the user)

CI proves the code on Windows. It cannot prove an agent can install and drive it there. Same protocol as the Linux ground-zero test on 2026-09-20, and Claude should not touch the machine.

- [ ] **Step 1 (Claude): prepare a release candidate the user can download** - after Tasks 1-7 are merged, with the user's go-ahead, bump to `0.3.0rc1` in `pyproject.toml` (the README URL test requires the README wheel URL to match; update it too), and push tag `v0.3.0rc1`. Verify the four assets serve 200 and `SHA256SUMS` verifies.

  First, so a release candidate never becomes the "latest" release a README reader is sent to, mark it a prerelease: in `.github/workflows/release.yml`, the "Publish to the releases page" step, add before `gh release create`:

  ```bash
          pre=""
          case "${GITHUB_REF_NAME}" in *rc*|*a[0-9]*|*b[0-9]*) pre="--prerelease" ;; esac
  ```

  and add `$pre` to the `gh release create` arguments (unquoted, so it vanishes when empty). Commit that before tagging.
- [ ] **Step 2 (user): three installs on the Windows machine**, each from nothing - no `mc-jarvis` on PATH, no `%LOCALAPPDATA%\mc-jarvis`:
  1. **Claude Code in a terminal.** Unzip `mc-jarvis-skill-0.3.0rc1.zip` into `<project>\.claude\skills\`. Ask *"What does Black Panther do?"*.
  2. **Claude Desktop, Code session** against a fresh project folder (see Task 9), same zip, same question.
  3. **The launcher directly** from cmd: `.claude\skills\mc-jarvis\scripts\mc-jarvis.cmd doctor`, and from PowerShell: `& .\.claude\skills\mc-jarvis\scripts\mc-jarvis.cmd doctor`.
- [ ] **Step 3 (user): note for each** - the first command the agent tried; whether it ran `init` itself; whether any output was garbled or crashed; whether the answer was right. Then run the Smoke set from `docs/testing/live-trials.html` in one of them.
- [ ] **Step 4 (Claude): read the transcripts**, not only the notes (method note from spec §14.29). Claude Code keeps them under `%USERPROFILE%\.claude\projects\`; the user copies them over or pastes them. Every defect gets a test and a fix before v0.3.0.

---

## Phase 2b - Claude Desktop

### Task 9: Find out, and document, how mc-jarvis runs in Claude Desktop

Claude Desktop can mean two different things, and only one is known to fit this tool:

- **Desktop running Claude Code sessions against a local folder.** Expected to load `<folder>/.claude/skills/` the way the terminal does, with the same file system and network. Likely the way most Windows users will run it.
- **Desktop chat with an uploaded skill** (a zip added in Desktop's settings). That skill runs in a sandbox. Whether that sandbox can reach GitHub and FFG's CDN for `init`, and whether it keeps a ~80 MB index between conversations, is **unknown**. If it cannot do either, mc-jarvis cannot work there, and the README must say so rather than leave people to find out.

**Files:**
- Modify: `README.md` - a "Claude Desktop" subsection under Install (Task 10 writes the rest of Install)

- [ ] **Step 1 (Claude): check current documentation for both modes** - Desktop's Code sessions (how a session picks its folder; whether project skills load) and uploaded skills (network access, file persistence, size limits). Use the claude-code-guide agent if the user agrees to it, otherwise the published docs. Record what is documented and what is not.
- [ ] **Step 2 (user): test the Code-session mode** on Linux and on Windows (Windows is Task 8 Step 2.2): fresh folder, unzip the skill into `.claude/skills/`, open that folder in a Desktop Code session, ask a question without naming a command.
- [ ] **Step 3 (user): try the upload mode once** with the release zip, and ask the same question. Expected outcome is one of: it works; it cannot run `init` (no network); it runs `init` but loses the index next conversation. Note which.
- [ ] **Step 4 (Claude): write the README subsection** from Steps 1-3 - exact steps for what works, and for what does not, one sentence saying so and why. Nothing written from assumption: every claim traces to Step 1 documentation or a Step 2-3 observation.
- [ ] **Step 5: Commit**

```bash
git add README.md
git commit   # "docs: running mc-jarvis in Claude Desktop"
```

---

## Phase 3 - README

### Task 10: README truth pass

**Files:**
- Modify: `README.md` - Install, Status

- [ ] **Step 1: Install - say where the skill folder goes, per harness**

Replace the paragraph beginning "Or take the skill folder" with:

```markdown
**Or take the skill folder**, which carries the tool with it. Every
release attaches `mc-jarvis-skill-<version>.zip`: `SKILL.md` beside the
package that runs it. Unzip it into your project folder's skills
directory for your harness:

| Harness | Unzip into |
|---|---|
| Claude Code (terminal or Claude Desktop) | `<project>/.claude/skills/` |
| Codex | `<project>/.codex/skills/` |
| pi, opencode | `<project>/.agents/skills/` |

It needs Python 3.10+ with PyYAML, and pypdf unless `pdftotext` is
installed. The agent runs `scripts/mc-jarvis` (on Windows from cmd or
PowerShell, `scripts\mc-jarvis.cmd`) and runs `init` itself the first
time. `SHA256SUMS` covers every attachment.
```

- [ ] **Step 2: Install - say what it costs up front**

After the requirements line ("Requires Python 3.10+ and uv"), add:

```markdown
You also need an AI agent harness to talk to - Claude Code, Claude
Desktop, Codex, pi or opencode - most of which need a paid plan. The first
`init` downloads about 80 MB of card data and rulebooks.
```

- [ ] **Step 3: Status - replace the stale section**

Replace the Status section's body with:

```markdown
Everything in the table above works: card lookup, identity grouping,
encounter sets, rules lookup and search, the timing reference, designer
rulings, the skill installer, collection tracking, the deck pipeline
(import, legality, statistics), and scenario assessment - including
heroic levels, extra modular sets (`--add-modular`, which is how campaign
penalties are added), and the cross-reference against a deck.

**Tested with:** Claude Code and pi on Linux; Claude Code on Windows
(<fill from Task 8>); Claude Desktop (<fill from Task 9>). Codex and
opencode are expected to work - they read the same skill directories -
but have not been tested.

**Not built:** campaign progress tracking (a campaign's rules are read
from its own rulebook, fetched on demand), and a coverage check comparing
a pack's declared size with the cards published upstream.
```

The two `<fill from Task N>` markers are the only two blanks in this plan, and they are deliberate: they must be filled from what the user observed, not in advance. The test in Step 4 refuses to let them ship.

- [ ] **Step 4: A test that refuses unfilled markers**

Append to `tests/test_packaging.py`:

```python
def test_the_readme_has_no_unfilled_markers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<fill from" not in text
```

It fails until Tasks 8 and 9 are done - which is the point: v0.3.0 cannot be cut before the platforms are tested. Commit the README change and this test together only once the markers are filled.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest -q tests/test_packaging.py -p no:randomly
git add README.md tests/test_packaging.py
git commit   # "docs: README matches the tool, and says what was tested"
```

---

## Phase 4 - release and soft launch

### Task 11: A bug report template

- [ ] **Step 1 (user): turn on Issues** - repository Settings → General → Features → Issues. (Claude cannot check this: `gh` is not authenticated.)
- [ ] **Step 2 (Claude): create `.github/ISSUE_TEMPLATE/bug_report.yml`**

```yaml
name: Bug report
description: Something mc-jarvis got wrong, or would not do
labels: [bug]
body:
  - type: textarea
    id: what
    attributes:
      label: What happened
      description: What you asked, what came back, and what you expected.
    validations:
      required: true
  - type: textarea
    id: doctor
    attributes:
      label: Output of `mc-jarvis doctor`
      description: >-
        From the skill folder, `scripts/mc-jarvis doctor`
        (Windows cmd or PowerShell: `scripts\mc-jarvis.cmd doctor`).
      render: text
    validations:
      required: true
  - type: dropdown
    id: harness
    attributes:
      label: Harness
      options: [Claude Code (terminal), Claude Desktop, Codex, pi, opencode, Other]
    validations:
      required: true
  - type: dropdown
    id: os
    attributes:
      label: Operating system
      options: [Windows, macOS, Linux]
    validations:
      required: true
  - type: input
    id: version
    attributes:
      label: mc-jarvis version
      description: The release you installed, e.g. 0.3.0
  - type: markdown
    attributes:
      value: >-
        Please don't paste card or rulebook text - describe the card by
        name. This project ships none of FFG's material and keeps its
        issues that way too.
```

- [ ] **Step 3: Commit**

```bash
git add .github/ISSUE_TEMPLATE/bug_report.yml
git commit   # "chore: a bug report template that asks for doctor output"
```

### Task 12: Cut v0.3.0

- [ ] **Step 1:** Confirm every task above is merged, CI green on all three platforms, and `test_the_readme_has_no_unfilled_markers` passes.
- [ ] **Step 2:** Bump `pyproject.toml` to `0.3.0`, update the README wheel URL to `mc_jarvis-0.3.0-py3-none-any.whl`, `uv lock`, run the full suite and the empty-data rehearsal, commit, push, check CI.
- [ ] **Step 3: Ask the user in chat before tagging.** On a yes: `git tag -a v0.3.0 -m "v0.3.0 - launch candidate" && git push origin v0.3.0`.
- [ ] **Step 4:** Verify all four assets serve 200 (retry a 504 before concluding anything - on 2026-09-21 the sdist 504'd twice and then served), download them, `sha256sum -c SHA256SUMS`, and unzip the skill: one `SKILL.md`, both launchers present, the `.cmd` with CRLF.

### Task 13: Soft launch (the user)

- [ ] **Step 1:** Two or three community members - at least one on Windows, one on macOS - install v0.3.0 from the releases page with no help beyond the README.
- [ ] **Step 2:** Ask each for: their harness, their OS, whether install worked from the README alone, one question they asked and whether the answer was right, anything confusing.
- [ ] **Step 3 (Claude):** every report of a defect gets a test and a fix; every point of confusion gets a README change. Cut v0.3.1 if anything changed.

---

## Phase 5 - announce

### Task 14: Demo and announcement draft

- [ ] **Step 1 (user):** record one real exchange - a deck question or a scenario question - as a transcript or a short screen capture, in whichever harness you expect most readers to use.
- [ ] **Step 2 (Claude):** draft the announcement for the user to edit. It leads with what the community will ask first: *it downloads the rulebooks from FFG's own site to your machine and ships none of FFG's material*. Then what it does, the demo, how to install (link the README, not a copy of it), what it does not do, and where to report problems. No claims beyond what the Status section says was tested.
- [ ] **Step 3 (user):** edit, then post where you choose. Claude does not post.

---

## Self-review

- **Scope coverage:** Phase 1 → Tasks 1-2. Windows → Tasks 3-8 (encoding 3, data dir 4, launcher 6, CI 7, LF 6 Step 5, human test 8). Claude Desktop → Task 9, and Task 8 Step 2.2. README → Task 10 (Status, per-harness dirs, tested platforms, prerequisites). Phase 4 → Tasks 11-13. Phase 5 → Task 14. The two defects found while planning → Task 5.
- **Placeholders:** the two `<fill from Task N>` markers in Task 10 are deliberate and test-enforced; the sixteen notes in Task 1 are an audit whose method, rules and worked example are given. No other blanks.
- **Names used across tasks:** `USER_TABLES`, `_restore`, `unknown_owned` (Task 2); `_utf8_streams` (Task 3); `build(out, root=ROOT)` (Task 5), used by the fixture in Tasks 5-6 and by the workflow in Task 5 Step 5; `MC_JARVIS_INVOKED_AS` and `MC_JARVIS_PYTHON` (Task 6, consumed by the existing `paths.invocation()`).
- **Review Focus:** 1 and 2 → Task 6 Step 1; 3 → Task 2 Step 1; 4 → Task 3 Step 1; 5 → Task 4 Step 1.
