"""Placing the skill for every harness (spec §7).

`install-skill`'s guard rails all fail silently when they fail: a skill in
the wrong directory simply never activates, and the user sees an agent
answering from memory rather than an error. So they get tests.
"""
import re
import subprocess
from pathlib import Path

import pytest

from mc_jarvis import skill_install as si


# --- workspace guards ------------------------------------------------

def test_home_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(si.WorkspaceError, match="home directory"):
        si.check_workspace(tmp_path)


def test_directory_inside_another_repository_is_refused(tmp_path):
    outer = tmp_path / "outer"
    (outer / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    with pytest.raises(si.WorkspaceError, match="inside"):
        si.check_workspace(outer / "sub")


def test_a_repository_root_is_accepted(tmp_path):
    """Its own root is fine - it is a nested one that gets cut off."""
    ws = tmp_path / "marvel"
    ws.mkdir()
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    si.check_workspace(ws)


def test_a_plain_directory_is_accepted(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    si.check_workspace(ws)


# --- placement -------------------------------------------------------

def test_install_places_the_skill_for_every_harness(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    placements = si.install(ws)
    got = {p.path.relative_to(ws).as_posix() for p in placements}
    assert got == {
        ".agents/skills/mc-jarvis",
        ".claude/skills/mc-jarvis",
        ".codex/skills/mc-jarvis",
    }
    for p in placements:
        assert (p.path / "SKILL.md").is_file()


def test_install_copies_by_default(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    for p in si.install(ws):
        assert not p.path.is_symlink()
        assert p.mode == "copy"


def test_link_mode_symlinks(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    for p in si.install(ws, link=True):
        assert p.path.is_symlink()
        assert p.mode == "link"


def test_install_initialises_git_so_the_boundary_is_defined(tmp_path):
    """Ancestor walking is bounded by the repository root; without a git
    root a workspace can be cut off from its own skill (spec §7)."""
    ws = tmp_path / "marvel"
    ws.mkdir()
    si.install(ws)
    assert (ws / ".git").is_dir()


def test_reinstall_replaces_rather_than_nesting(tmp_path):
    ws = tmp_path / "marvel"
    ws.mkdir()
    si.install(ws)
    si.install(ws)
    target = ws / ".claude" / "skills" / "mc-jarvis"
    assert not (target / "mc-jarvis").exists()


def test_reinstall_over_a_link_replaces_it_with_a_copy(tmp_path):
    """`shutil.rmtree` on a symlinked directory raises, and `unlink` on a
    real one raises too - so the replace has to test which it has."""
    ws = tmp_path / "marvel"
    ws.mkdir()
    si.install(ws, link=True)
    for p in si.install(ws):
        assert not p.path.is_symlink()
        assert (p.path / "SKILL.md").is_file()


def test_global_install_never_touches_the_workspace(tmp_path, monkeypatch):
    """--global is the escape hatch for someone who genuinely wants it
    everywhere. It must not also litter the current directory."""
    home = tmp_path / "home"
    home.mkdir()
    ws = tmp_path / "marvel"
    ws.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    placements = si.install(ws, global_=True)
    assert placements
    for p in placements:
        assert home in p.path.parents
    assert not (ws / ".claude").exists()
    assert not (ws / ".git").exists()


# --- the skill file itself -------------------------------------------

def _skill_text() -> str:
    return (si.SKILL_SOURCE / "SKILL.md").read_text(encoding="utf-8")


def test_frontmatter_has_the_required_fields_and_no_allowed_tools():
    text = _skill_text()
    assert text.startswith("---")
    front = text.split("---")[1]
    assert "name: mc-jarvis" in front
    assert "description:" in front
    assert "compatibility:" in front
    # Marked experimental with support varying between implementations,
    # which is exactly what breaks a one-file-everywhere design (spec §7).
    assert "allowed-tools" not in front


def test_skill_md_stays_under_the_length_limit():
    assert len(_skill_text().splitlines()) < 500


def test_browser_recipes_reference_exists_and_ends_every_path_the_same_way():
    """Whatever route a user takes to FFG's page, it lands on one
    command. A recipe that stops short of it has not helped."""
    text = (si.SKILL_SOURCE / "references" / "browser-recipes.md").read_text(
        encoding="utf-8")
    for harness in ("Claude Code", "Codex", "opencode", "pi"):
        assert harness in text, harness
    assert "Save Page As" in text
    assert text.count("mc-jarvis init --from-html") >= 5


def _skill_docs() -> list[str]:
    """Every file the skill ships. `references/` is read by the agent too,
    so it can drift from the CLI exactly like SKILL.md can."""
    return [p.read_text(encoding="utf-8")
            for p in sorted(si.SKILL_SOURCE.rglob("*.md"))]


def _subcommands(parser):
    return set(parser._subparsers._group_actions[0].choices)


def test_every_command_the_skill_names_actually_exists():
    """The draft named `deck stats`, which does not exist in this phase.
    A skill that tells an agent to run a missing command produces a
    confused agent, not an error."""
    from mc_jarvis import cli

    known = _subcommands(cli.build_parser())
    for text in _skill_docs():
        named = set(re.findall(r"`?mc-jarvis ([a-z-]+)", text))
        assert named <= known, named - known


def test_the_skill_names_every_command_a_player_would_ask_for():
    """The mirror of the test above, and the one that was missing: adding
    `rulings` to the parser and not to the skill left an agent unable to
    reach the feature at all. `named <= known` cannot catch that.

    Setup and diagnostics are excluded deliberately - the skill covers
    them in prose, not in its command table."""
    from mc_jarvis import cli

    setup_only = {"init", "update", "install-skill", "doctor"}
    known = _subcommands(cli.build_parser()) - setup_only - {"hero"}
    named = set()
    for text in _skill_docs():
        named |= set(re.findall(r"`?mc-jarvis ([a-z-]+)", text))
    assert known <= named, known - named


def test_two_level_commands_name_a_real_subcommand():
    """`rules show` and `card search` are two levels deep, which is where
    drift actually happens - the one-level check above passes on
    `mc-jarvis rules nonsense`."""
    from mc_jarvis import cli

    groups = cli.build_parser()._subparsers._group_actions[0].choices
    for text in _skill_docs():
        for parent, child in re.findall(r"mc-jarvis (card|rules) ([a-z]+)",
                                        text):
            assert child in _subcommands(groups[parent]), f"{parent} {child}"


def test_the_skill_names_at_least_one_two_level_command():
    """Guards the guard: a regex that matches nothing passes vacuously."""
    from mc_jarvis import cli

    groups = cli.build_parser()._subparsers._group_actions[0].choices
    assert "show" in _subcommands(groups["rules"])
    found = [m for text in _skill_docs()
             for m in re.findall(r"mc-jarvis (card|rules) ([a-z]+)", text)]
    assert len(found) >= 4, found


def test_the_skill_does_not_promise_flags_that_are_not_built():
    """--owned parses everywhere and is rejected at dispatch: the
    collection lands in a later phase."""
    for text in _skill_docs():
        assert "--owned" not in text


def test_the_skill_states_no_timing_rung_as_a_fact():
    """Trigger ordering has changed between Rules Reference versions. A
    SKILL.md is meant to be memorable enough that an agent repeats it,
    which is exactly what must not happen to a version-specific rung."""
    text = _skill_text()
    assert not re.search(r"rung \d", text, re.I)
    for claim in ("is a Forced Interrupt", "on rung", "outrank"):
        assert claim not in text, claim


def test_the_skill_teaches_the_citation_rule():
    text = _skill_text()
    assert "mc-jarvis status" in text
    assert "rr_version" in text


@pytest.mark.integration
def test_the_built_wheel_carries_the_whole_skill():
    """The distribution story runs entirely through this path: the repo
    ships no content, so `uv tool install mc-jarvis` has to deliver the
    skill and the configs. In a checkout `_bundled/skill` is a symlink and
    every other test reads through it, so nothing else would notice a
    force-include that stopped resolving - and `references/` was added to
    the skill long after that mapping was written.
    """
    import subprocess
    import zipfile

    repo = Path(__file__).resolve().parent.parent
    build = subprocess.run(["uv", "build", "--wheel"], cwd=repo,
                           capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    wheel = max((repo / "dist").glob("*.whl"), key=lambda p: p.stat().st_mtime)
    names = set(zipfile.ZipFile(wheel).namelist())
    for required in (
            "mc_jarvis/_bundled/skill/mc-jarvis/SKILL.md",
            "mc_jarvis/_bundled/skill/mc-jarvis/references/browser-recipes.md",
            "mc_jarvis/_bundled/timing.yaml",
            "mc_jarvis/_bundled/legality.yaml",
            "mc_jarvis/_bundled/glyphs.yaml"):
        assert required in names, required
