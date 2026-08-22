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
