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
