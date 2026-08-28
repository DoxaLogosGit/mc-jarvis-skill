"""Data directory resolution. Never alongside the package (spec §5)."""
from __future__ import annotations

import os
from pathlib import Path

SUBDIRS = ("marvelsdb", "rules/pdf", "rules/txt", "meta")


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
