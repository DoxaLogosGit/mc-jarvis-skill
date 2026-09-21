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


def test_bundled_configs_resolve_without_the_symlinks(tmp_path, monkeypatch):
    """A fresh clone has an EMPTY `_bundled/`: the symlinks are gitignored
    and only exist on a machine that made them. Every config loader read
    `_bundled` directly, so a clean checkout raised
    `FileNotFoundError: _bundled/timing.yaml` - 79 CI failures, and the
    same for anyone following the README's `uv sync && uv run pytest`.

    `paths.bundled` prefers the installed layout and falls back to the
    repository's own `config/`, so both work.
    """
    from mc_jarvis import paths

    monkeypatch.setattr(paths, "_BUNDLED", tmp_path / "absent")
    for name in ("timing.yaml", "legality.yaml", "glyphs.yaml",
                 "keywords.yaml", "encounter_setup.yaml"):
        resolved = paths.bundled(name)
        assert resolved.exists(), name
        assert resolved.parent.name == "config", resolved

    skill = paths.bundled("skill", "mc-jarvis")
    assert (skill / "SKILL.md").exists(), skill


def test_every_repo_config_is_reachable_through_bundled():
    """A config added to `config/` without a `force-include` line works in
    a checkout and fails for anyone who installed the tool. This catches
    the checkout half; `test_the_wheel_carries_every_bundled_config`
    catches the wheel half."""
    from mc_jarvis import paths

    for config in (ROOT / "config").glob("*.yaml"):
        assert paths.bundled(config.name).exists(), config.name


# --- what the release workflow depends on -----------------------------

def _pyproject_version() -> str:
    line = [l for l in (ROOT / "pyproject.toml").read_text(
        encoding="utf-8").splitlines() if l.startswith("version = ")]
    assert len(line) == 1, line
    return line[0].split('"')[1]


def test_the_release_workflow_can_read_the_version():
    """The workflow refuses a tag that disagrees with `pyproject.toml`,
    and it reads the version with a `sed` expression rather than a TOML
    parser. Reformat that line - single quotes, an inline comment, a
    move out of the first table - and the check compares the tag against
    an empty string, failing every release until someone reads the log."""
    import re

    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    pattern = re.search(r"sed -n 's([^']*)' pyproject.toml", workflow)
    assert pattern, "the version-reading step is not where this test looks"
    # The same expression the workflow runs, applied to the real file.
    found = re.findall(r'^version = "(.*)"$',
                       (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                       re.M)
    assert found[:1] == [_pyproject_version()]


def test_the_release_gates_on_the_checks_rather_than_a_copy():
    """`release.yml` calls `checks.yml`, so the checks have one home. A
    reusable workflow needs `workflow_call` to be callable at all, and
    without it the release fails only once a tag is pushed."""
    checks = (ROOT / ".github" / "workflows" / "checks.yml").read_text(
        encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    assert "workflow_call:" in checks
    assert "uses: ./.github/workflows/checks.yml" in release


def test_the_skill_archive_has_something_to_archive():
    """The release attaches the skill on its own, for harnesses that want
    the file without the package. It is zipped from a path, so a rename
    would publish an empty archive."""
    skill = ROOT / "skill" / "mc-jarvis"
    assert (skill / "SKILL.md").exists()
    assert list(skill.rglob("*.md"))


def test_the_readme_install_url_names_the_current_version():
    """The README installs a wheel by URL, and the filename carries the
    version. Left behind at a release, it hands every new reader an
    install line for a version that is no longer the latest."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"mc_jarvis-{_pyproject_version()}-py3-none-any.whl" in readme


# --- the skill folder a release attaches ------------------------------

@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """Built by the same script the release runs, so this tests the
    deliverable rather than a second description of it."""
    out = tmp_path_factory.mktemp("bundle")
    subprocess.run([str(ROOT / "tools" / "build-skill-bundle.sh"), str(out)],
                   check=True, capture_output=True, text=True)
    return out / "mc-jarvis"


def test_the_skill_folder_carries_the_tool(bundle):
    """A skill that ships code puts the code in the folder. Shipping
    SKILL.md alone left a skill whose 45 commands all needed a package
    installed from somewhere else."""
    assert (bundle / "SKILL.md").is_file()
    assert (bundle / "references" / "browser-recipes.md").is_file()
    assert (bundle / "scripts" / "mc-jarvis").is_file()
    package = bundle / "scripts" / "mc_jarvis"
    assert (package / "cli.py").is_file()
    # The entry point `python -m` needs; without it the package imports
    # and exits 0 having done nothing.
    assert (package / "__main__.py").is_file()
    assert len(list(package.glob("*.py"))) > 30


def test_the_bundled_config_is_where_paths_looks_for_it(bundle):
    """`paths.py` prefers `_bundled` beside the package and falls back to
    the repository's `config/`, which is not in the bundle. Put the files
    anywhere else and every config loader fails on a clean unzip."""
    bundled = bundle / "scripts" / "mc_jarvis" / "_bundled"
    for name in ("legality.yaml", "timing.yaml", "glyphs.yaml",
                 "keywords.yaml", "encounter_setup.yaml"):
        assert (bundled / name).is_file(), name


def test_the_bundle_carries_files_rather_than_links(bundle):
    """A checkout keeps SKILL.md as a symlink into the repository. Zipped
    as a link, it unpacks on someone else's machine pointing at a path
    that does not exist."""
    assert not (bundle / "SKILL.md").is_symlink()
    assert (bundle / "SKILL.md").stat().st_size > 1000
    assert not any(p.is_symlink() for p in bundle.rglob("*")), "symlink"
    # Nobody needs the builder's bytecode.
    assert not list(bundle.rglob("__pycache__"))


def test_the_bundle_runs_with_nothing_installed(bundle, tmp_path):
    """The point of the folder: unzip it, and it works. Run against an
    interpreter that has PyYAML but has never heard of mc_jarvis."""
    import venv

    env = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env)
    python = env / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", "-q", "pyyaml"],
                   check=True, capture_output=True)
    absent = subprocess.run([str(python), "-c", "import mc_jarvis"],
                            capture_output=True, text=True)
    assert absent.returncode != 0, "the venv already has the package"

    got = subprocess.run(
        [str(bundle / "scripts" / "mc-jarvis"), "--help"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "MC_JARVIS_PYTHON": str(python)})
    assert got.returncode == 0, got.stderr
    assert "assess" in got.stdout
