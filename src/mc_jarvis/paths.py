"""Data directory resolution. Never alongside the package (spec §5)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

SUBDIRS = ("marvelsdb", "rules/pdf", "rules/txt", "meta")


def invocation() -> str:
    """How this copy was called, for a message that tells the reader to
    run something.

    Six messages said `mc-jarvis init`. Run from a skill folder with the
    package beside it and nothing on PATH - which is how a release is
    meant to be used - that names a command the reader does not have. A
    live test ended with the agent relaying exactly that, the user
    trying it, and it failing before anyone worked out the tool was
    already there.
    """
    # A launcher that execs `python -m mc_jarvis` knows the name the
    # reader typed; argv[0] by then is this package's `__main__.py`.
    told = os.environ.get("MC_JARVIS_INVOKED_AS")
    if told:
        return told
    argv0 = sys.argv[0] or ""
    name = os.path.basename(argv0)
    if name == "__main__.py":
        return "python -m mc_jarvis"
    # argv[0] is only evidence when it IS this tool. Imported as a
    # library - or under a test runner, which is how this was caught -
    # it names the host program, and the message told the reader to run
    # `pytest encounter the_hood`. The documented name is the safe
    # answer when the entry point is something else entirely.
    if name not in ("mc-jarvis", "mc_jarvis"):
        return "mc-jarvis"
    # An installed console script is on PATH, so its bare name is the
    # shortest true answer. Compared by real path rather than by name: a
    # bundle's launcher is also called `mc-jarvis`, and saying the bare
    # name there would point at whatever else the PATH happens to hold.
    found = shutil.which(name)
    try:
        if found and os.path.samefile(found, argv0):
            return name
    except OSError:
        pass
    return argv0


def data_dir() -> Path:
    explicit = os.environ.get("MC_JARVIS_DATA")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "mc-jarvis"
    return Path.home() / ".local" / "share" / "mc-jarvis"


def ensure_data_dir() -> Path:
    root = data_dir()
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def db_path() -> Path:
    return data_dir() / "mc.sqlite"


# Configuration and the skill ship INSIDE the wheel, under `_bundled`, so
# a `uv tool install` user with no checkout can still reach them. In a
# checkout those are symlinks to the repo root - and they are gitignored,
# so a FRESH CLONE has none of them.
#
# That broke every config loader on a clean checkout: CI failed 79 tests
# with `FileNotFoundError: _bundled/timing.yaml`, and so would anyone
# following the README's `uv sync && uv run pytest`. Falling back to the
# repo root fixes the clone, not just the CI runner.
_BUNDLED = Path(__file__).parent / "_bundled"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def bundled(*parts: str) -> Path:
    """A bundled config or skill path, wherever this copy keeps it.

    Prefers `_bundled` - the installed layout, and the only one that
    exists for a wheel user. Falls back to the repository's own `config/`
    and `skill/` so a source checkout works without a build step.
    """
    installed = _BUNDLED.joinpath(*parts)
    if installed.exists():
        return installed
    # `skill/...` sits at the repo root; everything else is a config file.
    root = _REPO_ROOT if parts[0] == "skill" else _REPO_ROOT / "config"
    source = root.joinpath(*parts)
    return source if source.exists() else installed
