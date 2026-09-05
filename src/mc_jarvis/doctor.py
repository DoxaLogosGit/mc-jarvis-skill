"""Runtime prerequisite checks (spec §6).

Requirements are checked at runtime rather than assumed, because this runs
under agents we do not control, on machines we have never seen.
"""
from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from . import paths
from .cli import emit

PYTHON_FLOOR = (3, 10)
UPSTREAMS = {
    "network:card-data": "https://codeload.github.com",
    "network:ffg-cdn": "https://images-cdn.fantasyflightgames.com",
}
POPPLER_HINT = {
    "Linux": "your package manager, e.g. `sudo dnf install poppler-utils`",
    "Darwin": "`brew install poppler`",
    "Windows": "not required - pypdf is used",
}
STALE_DAYS = 14


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hard: bool


def has_fts5() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        conn.close()
        return True
    except sqlite3.Error:
        return False


def pdf_backend() -> str:
    if shutil.which("pdftotext"):
        return "pdftotext"
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        return "none"


def _playwright_present() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _reachable(url: str, timeout: float = 5.0) -> bool:
    req = urllib.request.Request(url, method="HEAD")
    try:
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True          # a status code means the host answered
    except Exception:
        return False


def run_checks(*, network: bool = True) -> list[Check]:
    checks: list[Check] = []

    v = sys.version_info
    checks.append(Check("python", v[:2] >= PYTHON_FLOOR,
                        f"{v.major}.{v.minor}.{v.micro} (need >= 3.10)",
                        hard=True))

    fts = has_fts5()
    checks.append(Check(
        "sqlite-fts5", fts,
        f"SQLite {sqlite3.sqlite_version}" + ("" if fts else
        " - built without FTS5; a full CPython build is required"),
        hard=True))

    backend = pdf_backend()
    checks.append(Check(
        "pdf-backend", backend != "none",
        backend if backend != "none" else
        "neither pdftotext nor pypdf found; install poppler via "
        + POPPLER_HINT.get(platform.system(), "your package manager"),
        hard=True))

    root = paths.data_dir()
    # Walk to the nearest ancestor that exists, rather than looking one
    # level up. `init` creates the whole chain with `parents=True`, so the
    # question is whether the first real directory above it is writable.
    # Probing only the parent reported a hard FAIL on any machine where
    # neither the data dir nor its parent existed yet -- a fresh container,
    # or a custom XDG_DATA_HOME - which is the state `doctor` exists to
    # inspect, and it is the first command a new user runs.
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    checks.append(Check("data-dir", os.access(probe, os.W_OK),
                        str(root) + ("" if root.exists()
                                     else "  - will be created by `init`"),
                        hard=True))

    db = paths.db_path()
    if db.exists():
        age = (time.time() - db.stat().st_mtime) / 86400
        checks.append(Check(
            "index", True,
            f"{db} ({age:.0f} days old)"
            + ("  - stale, run `mc-jarvis update`" if age > STALE_DAYS else ""),
            hard=False))
    else:
        checks.append(Check("index", False,
                            "not built - run `mc-jarvis init`", hard=False))

    for name, present in (("git", shutil.which("git") is not None),
                          ("playwright", _playwright_present())):
        checks.append(Check(f"optional:{name}", present,
                            "present" if present else "absent (not required)",
                            hard=False))

    if network:
        for name, url in UPSTREAMS.items():
            checks.append(Check(name, _reachable(url), url, hard=False))

    return checks


def handle(args) -> int:
    # Network probing is opt-out so tests (and offline machines) can run
    # the same code path without reaching the network.
    checks = run_checks(network=getattr(args, "network", True))
    if getattr(args, "json", False):
        emit([asdict(c) for c in checks], as_json=True)
    else:
        for c in checks:
            mark = "ok  " if c.ok else ("FAIL" if c.hard else "--  ")
            print(f"{mark} {c.name}: {c.detail}")
    return 1 if any(c.hard and not c.ok for c in checks) else 0
