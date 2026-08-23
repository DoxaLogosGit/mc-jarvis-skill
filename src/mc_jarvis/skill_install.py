"""Place the skill for every harness (spec §7).

Workspace-scoped by default. Harnesses find a project skill by walking up
from the working directory, and that walk stops at the repository root -
so a skill installed at `$HOME` loads in every session on the machine,
and one installed in a directory nested inside an unrelated repository may
never load at all. Both failures are silent: the user sees an agent
answering from memory, not an error. Hence `check_workspace`.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SKILL_NAME = "mc-jarvis"
SKILL_SOURCE = Path(__file__).parent / "_bundled" / "skill" / SKILL_NAME

# Three workspace directories cover four harnesses: `.agents` is the
# vendor-neutral path pi and opencode read; Claude Code and Codex each
# read only their own.
HARNESS_DIRS = {
    "pi, opencode": (".agents/skills",),
    "Claude Code":  (".claude/skills",),
    "Codex":        (".codex/skills",),
}
GLOBAL_DIRS = {
    "pi, opencode": ("~/.agents/skills",),
    "Claude Code":  ("~/.claude/skills",),
    "Codex":        ("~/.codex/skills",),
}
NEEDS_TRUST = {"pi, opencode"}


class WorkspaceError(RuntimeError):
    pass


@dataclass
class Placement:
    harness: str
    path: Path
    mode: str
    needs_trust: bool


def _git_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return Path(out.stdout.strip()).resolve()


def check_workspace(path: Path) -> None:
    """Refuse the two placements that fail silently."""
    path = path.resolve()
    if path == Path.home().resolve():
        raise WorkspaceError(
            "refusing to install into your home directory: harnesses walk "
            "up to the git root, so a skill here would load in every "
            "session on this machine. Make a folder for your decks and run "
            "this there, or pass --global if you genuinely want it "
            "everywhere.")
    root = _git_root(path)
    if root is not None and root != path:
        raise WorkspaceError(
            f"{path} is inside the repository at {root}. Harnesses stop "
            f"walking up at the repository root, so the skill may not load "
            f"here. Choose a workspace outside it.")


def _replace(dest: Path) -> None:
    """Clear whatever is there. A symlinked directory needs `unlink` and a
    real one needs `rmtree`, and each raises on the other - so a reinstall
    that assumes one shape breaks on the mode it did not install."""
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)


def install(workspace: Path, *, link: bool = False,
            global_: bool = False) -> list[Placement]:
    if not SKILL_SOURCE.is_dir():
        raise WorkspaceError(f"bundled skill not found at {SKILL_SOURCE}")

    if global_:
        targets = [(h, Path(d).expanduser())
                   for h, dirs in GLOBAL_DIRS.items() for d in dirs]
    else:
        workspace = workspace.resolve()
        check_workspace(workspace)
        # Without a repository root the upward walk has no boundary, and
        # which directory the harness treats as "the project" becomes a
        # function of wherever the user happened to `cd` from.
        if not (workspace / ".git").exists():
            subprocess.run(["git", "init", "-q", str(workspace)], check=False)
        targets = [(h, workspace / d)
                   for h, dirs in HARNESS_DIRS.items() for d in dirs]

    placements: list[Placement] = []
    for harness, parent in targets:
        parent.mkdir(parents=True, exist_ok=True)
        dest = parent / SKILL_NAME
        _replace(dest)

        if link:
            dest.symlink_to(SKILL_SOURCE.resolve(), target_is_directory=True)
            mode = "link"
        else:
            shutil.copytree(SKILL_SOURCE, dest)
            mode = "copy"

        placements.append(Placement(harness, dest, mode,
                                    harness in NEEDS_TRUST))
    return placements


def run(args) -> int:
    from .cli import emit

    workspace = Path.cwd()
    try:
        placements = install(workspace, link=getattr(args, "link", False),
                             global_=getattr(args, "global_", False))
    except WorkspaceError as exc:
        print(f"mc-jarvis install-skill: {exc}")
        return 1

    if getattr(args, "json", False):
        emit([{"harness": p.harness, "path": str(p.path), "mode": p.mode,
               "needs_trust": p.needs_trust} for p in placements],
             as_json=True)
        return 0

    for p in placements:
        print(f"{p.mode:<5} {p.harness:<14} {p.path}")
    if any(p.needs_trust for p in placements):
        print("\nSome harnesses load project skills only after you trust "
              "the directory. If nothing activates, trust this folder in "
              "your agent and restart it.")
    if not getattr(args, "global_", False):
        print(f"\nAsk your agent a Marvel Champions question from "
              f"{workspace} to check it works.")
    return 0
