"""The battery to run before handing this to a live agent.

Everything here is combinatorial or contract surface: the shapes a host
model reaches that no single unit test owns. It is the last gate before a
real session, and it needs a built index, so it is marked `integration`
and **CI does not run it** -- CI runs `-m "not integration"` on a runner
with no index. This is a local gate, deliberately.

What is already covered elsewhere, and is not repeated here:

- `test_packaging.py` -- what the wheel and sdist actually contain
- `test_policy.py`    -- no card or rules text on the shipped surface
- `test_skill_install.py` -- agent-agnostic install, no global writes
- `test_init.py`, `test_index.py` -- building, schema version, staleness
- `test_doctor.py`    -- a data directory that does not exist yet

Run the lot with `uv run pytest -m integration -q`.
"""
import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from mc_jarvis import assess, timing

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill" / "mc-jarvis" / "SKILL.md"
# The console script, not `-m mc_jarvis`: the package has no `__main__`,
# so running it that way exits with an import error that matches none of
# the patterns below and every assertion here passes without testing
# anything. This is how a host model invokes the tool in any case.
CLI = Path(sys.executable).parent / "mc-jarvis"
# Commands that reach the network or write to the user's own data. A test
# that runs them rebuilds the index it is testing against, or quietly
# rewrites the collection of whoever ran the suite.
SIDE_EFFECTS = {("init",), ("update",), ("collection", "set")}

DIFFICULTIES = ["standard", "expert", "standard_ii", "expert_ii",
                "standard_iii"]

pytestmark = pytest.mark.integration


def _scenarios(conn):
    return [r["code"] for r in conn.execute(
        "SELECT DISTINCT set_code AS code FROM cards "
        "WHERE type_code = 'main_scheme' AND is_reprint = 0 ORDER BY 1")]


def _render(steps):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for step in steps:
            assess._line(step)
    return buf.getvalue()


# --- the combinatorial sweep -----------------------------------------

def test_every_scenario_renders_at_every_difficulty_and_table(real_index):
    """The sweep that catches a renderer reaching for a key some scenario
    does not have. It has to be re-run whenever `profile` gains a field:
    a KeyError here reaches the user as a stack trace mid-answer."""
    crashes, empty = [], []
    combinations = 0
    for code in _scenarios(real_index):
        for level in DIFFICULTIES:
            for players in (1, 4):
                try:
                    sc = assess.resolve(real_index, code, difficulty=level,
                                        players=players)
                except assess.UnknownScenario:
                    # A refusal is an answer: components, and scenarios
                    # whose sets cannot be inferred, are meant to refuse.
                    continue
                try:
                    if not _render(assess.trajectory(real_index, sc)).strip():
                        empty.append((code, level, players))
                    combinations += 1
                except Exception as exc:  # noqa: BLE001 - reporting the set
                    crashes.append((code, level, players, repr(exc)))
    assert not crashes, crashes[:5]
    assert not empty, empty[:5]
    assert combinations > 400, f"only {combinations} combinations ran"


def test_every_rendered_scenario_survives_strict_json(real_index):
    """`--json` is how another program consumes this. `json.dumps` without
    a `default=` fallback is the honest test: a stray non-serialisable
    value in one scenario's findings shows up nowhere else."""
    bad = []
    for code in _scenarios(real_index):
        for level in ("standard", "standard_iii"):
            try:
                sc = assess.resolve(real_index, code, difficulty=level)
            except assess.UnknownScenario:
                continue
            steps = assess.trajectory(real_index, sc)
            try:
                back = json.loads(json.dumps(
                    {"scenario": sc.scenario_set, "steps": steps}))
            except TypeError as exc:
                bad.append((code, level, str(exc)))
                continue
            assert back["steps"], (code, level)
    assert not bad, bad[:5]


def test_every_nemesis_set_leaves_the_opening_deck_alone(real_index):
    """All 69, not the one that was convenient. A nemesis set is set aside
    (RR p.30), so none of it is dealt; the invariant is that naming one
    changes nothing about the deck the players face at the start."""
    sets = [r["code"] for r in real_index.execute(
        "SELECT code FROM sets WHERE card_set_type_code = 'nemesis' "
        "ORDER BY code")]
    assert len(sets) > 60, f"only {len(sets)} nemesis sets found"
    baseline = len(assess.deck_cards(
        real_index, assess.resolve(real_index, "Rhino")))
    moved = []
    for code in sets:
        sc = assess.resolve(real_index, "Rhino", nemesis=[code])
        size = len(assess.deck_cards(real_index, sc))
        if size != baseline:
            moved.append((code, baseline, size))
        json.dumps({"steps": assess.trajectory(real_index, sc)})
    assert not moved, moved[:5]


def test_no_nemesis_set_is_reported_as_pulling_itself(real_index):
    """Every nemesis minion prints a parenthetical naming itself as one.
    A card inside the set cannot be what brings the set in -- it is only
    reachable once the set is already shuffled in."""
    sets = [r["code"] for r in real_index.execute(
        "SELECT code FROM sets WHERE card_set_type_code = 'nemesis'")]
    for code in sets:
        sc = assess.resolve(real_index, "Rhino", nemesis=[code])
        assert not [c for c in assess.nemesis_pull(real_index, sc)
                    if c["set"] == code], code


# --- input refusals ---------------------------------------------------

@pytest.mark.parametrize("flag", ["modular", "nemesis"])
def test_an_unknown_set_is_refused(real_index, flag):
    """The failure an agent makes constantly: a guessed set code. An
    unknown code joins no cards, so silently accepting it reports a deck
    nobody plays."""
    with pytest.raises(assess.UnknownScenario) as err:
        assess.resolve(real_index, "Rhino", **{flag: ["not_a_real_set"]})
    assert "no set named" in str(err.value)


@pytest.mark.parametrize("argv,bad", [
    (["assess", "rhino", "--players", "0"], "players"),
    (["assess", "rhino", "--players", "9"], "players"),
    (["assess", "rhino", "--heroic", "-5"], "heroic"),
    (["assess", "rhino", "--difficulty", "nope"], "difficulty"),
    (["assess", "rhino", "--modular", "not_a_real_set"], "modular"),
])
def test_the_cli_refuses_bad_input(argv, bad):
    if not CLI.exists():
        pytest.skip("console script not installed")
    p = subprocess.run([str(CLI), *argv], capture_output=True, text=True)
    assert p.returncode != 0, f"{bad} accepted: {p.stdout[:200]}"


# --- the contract the host model reads --------------------------------

PLACEHOLDERS = {
    "scenario": "rhino", "villain-or-set": "rhino",
    "leader set": "iron_man_leader", "name-or-code": "Tackle",
    "query": "tackle", "name": "Spider-Man", "entry": "Ability",
    "keyword": "permanent", "term": "Ability", "text": "guard",
    "trigger": "when revealed", "pack": "core",
}
# Filled at collection time with a deck written to a temp file, so the
# deck commands are exercised without reaching marvelcdb.
DECK_PLACEHOLDERS = ("file", "deck", "id-or-url-or-file")


def _skill_commands(deck_path):
    """Read the command lines out of SKILL.md rather than listing them.

    Hardcoding the list means the next edit to the skill file silently
    stops being checked, which is the failure this test exists to catch.
    A placeholder with no value is reported rather than skipped, so a new
    one shows up as a gap instead of quietly narrowing the battery.
    """
    values = dict(PLACEHOLDERS)
    values.update({k: str(deck_path) for k in DECK_PLACEHOLDERS})
    runnable, unfillable = [], []
    for raw in sorted(set(re.findall(r"`(mc-jarvis [^`]+)`",
                                     SKILL.read_text(encoding="utf-8")))):
        # `[--flag ...]` marks optional extras rather than a literal, and
        # a trailing `...` marks a repeatable argument.
        line = re.sub(r"\[[^\]]*\]", "", raw).replace("...", "").strip()
        # Placeholders can hold spaces, so they are matched whole rather
        # than found by splitting the line first.
        parts = re.split(r"<([^>]+)>", line)
        filled, ok = [], True
        for i, part in enumerate(parts):
            if i % 2:
                if part not in values:
                    ok = False
                    break
                filled.append(values[part])
            else:
                filled.extend(part.split())
        args = filled[1:]
        if ok and not any(tuple(args[:len(p)]) == p for p in SIDE_EFFECTS):
            runnable.append((raw, args))
        elif ok:
            pass  # deliberately skipped; see SIDE_EFFECTS
        else:
            unfillable.append(raw)
    return runnable, unfillable


@pytest.fixture
def deck_file(tmp_path, real_index):
    """A minimal deck on disk, so the deck commands run without network."""
    hero = real_index.execute(
        "SELECT code FROM cards WHERE type_code = 'hero' AND is_reprint = 0 "
        "ORDER BY code LIMIT 1").fetchone()["code"]
    slots = {r["code"]: 3 for r in real_index.execute(
        "SELECT code FROM cards WHERE type_code = 'event' "
        "AND faction_code = 'basic' AND is_reprint = 0 ORDER BY code LIMIT 5")}
    path = tmp_path / "deck.json"
    path.write_text(json.dumps(
        {"name": "preflight", "hero_code": hero, "slots": slots}),
        encoding="utf-8")
    return path


def test_every_command_the_skill_file_shows_still_parses(deck_file):
    """SKILL.md is what the host model follows. A flag that no longer
    exists fails there at integration time and no unit test covers it.

    Only parsing is asserted, never the result: "no matches" is a correct
    answer, and a suite that treated it as failure would go red the day
    someone adds a card.
    """
    runnable, unfillable = _skill_commands(deck_file)
    assert not unfillable, f"no value for placeholders in: {unfillable}"
    assert len(runnable) > 15, f"only {len(runnable)} commands parsed"
    if not CLI.exists():
        pytest.skip("console script not installed")
    broken = []
    for raw, args in runnable:
        p = subprocess.run([str(CLI), *args], capture_output=True, text=True)
        out = (p.stdout or "") + (p.stderr or "")
        if re.search(r"unrecognized arguments|invalid choice|Traceback"
                     r"|^usage: mc-jarvis", out, re.M):
            broken.append((raw, out.strip().splitlines()[:2]))
    assert not broken, broken


def test_every_charted_trigger_answers_to_lower_case():
    """A person types `when revealed`; the chart prints `When Revealed`.
    Refusing the typed form is a lookup failure dressed as an answer."""
    config = timing.load_config()
    for name in list(config["triggers"]) + list(config["outside_chart"]):
        found = timing.classify(timing.recase(name.lower()))
        assert found is not None, name
        assert found.canonical == name


def test_recasing_still_refuses_something_that_is_not_a_trigger():
    assert timing.classify(timing.recase("nonsense here")) is None
