"""What the deliverable package actually contains.

The repository's distribution rule is relaxed in exactly two places, and
both are deliberate: test fixtures carry real card text because a parser
test with invented input tests nothing, and the design documents quote
`Contents` blocks as the evidence for a measurement. Neither belongs in
a package someone installs.

`tests/test_policy.py` keeps FFG's words out of the shipped surface.
These tests keep the unshipped surface out of the package - the other
half of the same rule, and the half that was open: hatchling's default
sdist is everything git tracks, so it carried 28 test files.
"""
import glob
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Directories whose contents are for developing this project, not for
# running it.
UNSHIPPED = ("tests/", "docs/", ".claude/", "NIGHT-REPORT")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(out), str(ROOT)],
        capture_output=True, text=True)
    if result.returncode != 0:
        result = subprocess.run(
            ["uv", "build", "--out-dir", str(out)],
            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"cannot build a package here: {result.stderr[-300:]}")
    return out


def _sdist_names(out: Path) -> list[str]:
    with tarfile.open(glob.glob(str(out / "*.tar.gz"))[0]) as tar:
        return ["/".join(n.split("/")[1:]) for n in tar.getnames()]


def _wheel_names(out: Path) -> list[str]:
    return zipfile.ZipFile(glob.glob(str(out / "*.whl"))[0]).namelist()


@pytest.mark.integration
def test_the_sdist_ships_no_tests_or_design_documents(built):
    """Hatchling's default sdist is everything git tracks. `uv build` then
    builds the WHEEL FROM THE SDIST, so an unscoped sdist is the real
    deliverable and it carried 28 test files and the specs."""
    names = _sdist_names(built)
    leaked = [n for n in names
              if any(n.startswith(d) or d in n for d in UNSHIPPED)]
    assert leaked == [], leaked


@pytest.mark.integration
def test_the_wheel_ships_no_tests_or_design_documents(built):
    names = _wheel_names(built)
    leaked = [n for n in names
              if any(d.strip("/") in n for d in UNSHIPPED)]
    assert leaked == [], leaked


@pytest.mark.integration
def test_the_sdist_still_carries_what_the_wheel_needs(built):
    """The sdist's include list is a denylist's opposite, so trimming it
    can break the build rather than just shrink it: the wheel's
    force-include reads `config/` and `skill/` from the source tree, and
    `uv build` builds the wheel from the sdist."""
    names = set(_sdist_names(built))
    for needed in ("pyproject.toml", "README.md", "LICENSE"):
        assert needed in names, needed
    for prefix in ("src/mc_jarvis/", "config/", "skill/"):
        assert any(n.startswith(prefix) for n in names), prefix


@pytest.mark.integration
def test_the_wheel_carries_every_bundled_config(built):
    """`install-skill` and every gate read these from `_bundled`, so a
    config added to `config/` without a `force-include` line works in a
    checkout and fails for anyone who installed the tool."""
    bundled = {n.split("/")[-1] for n in _wheel_names(built)
               if "_bundled/" in n and n.endswith(".yaml")}
    expected = {p.name for p in (ROOT / "config").glob("*.yaml")}
    assert bundled == expected, expected - bundled


@pytest.mark.integration
def test_the_skill_is_in_the_wheel(built):
    """A `uv tool install` user has no checkout to install the skill
    from."""
    assert any("_bundled/skill/" in n and n.endswith("SKILL.md")
               for n in _wheel_names(built))
