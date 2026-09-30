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
import os
import shutil
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

def _builder():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_skill_bundle", ROOT / "tools" / "build_skill_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """Built by the same code the release runs, so this tests the
    deliverable rather than a second description of it."""
    return _builder().build(tmp_path_factory.mktemp("bundle"))


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


@pytest.fixture(scope="module")
def bare_python(tmp_path_factory):
    """An interpreter with PyYAML that has never heard of mc_jarvis, so a
    launcher can only succeed by supplying the bundled package itself."""
    import venv

    env = tmp_path_factory.mktemp("venv")
    venv.EnvBuilder(with_pip=True).create(env)
    windows = sys.platform == "win32"
    python = env / ("Scripts" if windows else "bin") / (
        "python.exe" if windows else "python")
    subprocess.run([str(python), "-m", "pip", "install", "-q", "pyyaml"],
                   check=True, capture_output=True)
    absent = subprocess.run([str(python), "-c", "import mc_jarvis"],
                            capture_output=True, text=True)
    assert absent.returncode != 0, "the venv already has the package"
    return python


def test_the_bundle_runs_with_nothing_installed(bundle, bare_python, tmp_path):
    """The point of the folder: unzip it, and it works. Run against an
    interpreter that has PyYAML but has never heard of mc_jarvis."""
    windows = sys.platform == "win32"
    python = bare_python

    # The launcher each platform's user runs: the batch file on Windows,
    # the shell script elsewhere. `MC_JARVIS_PYTHON` pins the interpreter
    # that has never heard of mc_jarvis, so the bundle has to supply it.
    if windows:
        launcher = bundle / "scripts" / "mc-jarvis.cmd"
        run_env = {**os.environ, "MC_JARVIS_PYTHON": str(python)}
    else:
        launcher = bundle / "scripts" / "mc-jarvis"
        run_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                   "MC_JARVIS_PYTHON": str(python)}
    got = subprocess.run([str(launcher), "--help"],
                         capture_output=True, text=True, env=run_env)
    assert got.returncode == 0, got.stderr
    assert "assess" in got.stdout


def test_the_bundle_holds_exactly_one_skill(bundle):
    """A checkout's `_bundled/` links to the whole skill directory for
    development. Followed during the build, it put a second SKILL.md
    inside the package, and a harness that scans skills recursively
    would register the skill twice."""
    assert [p.relative_to(bundle).as_posix()
            for p in bundle.rglob("SKILL.md")] == ["SKILL.md"]


def test_the_bundle_and_wheel_carry_no_gitignore(bundle, built):
    assert not list(bundle.rglob(".gitignore"))
    assert not [n for n in _wheel_names(built) if n.endswith(".gitignore")]


def _fake_python_dir(tmp_path, *, stub_python3: bool):
    """A PATH holding only what the shell launcher needs: `sh` (its
    `#!/usr/bin/env sh` looks it up on PATH), `dirname`, `uname`, and a
    `python` that runs this test's interpreter. With `stub_python3`, also
    a `python3` that exits the way the Microsoft Store stub does."""
    bindir = tmp_path / "bin dir"          # a space, on purpose
    bindir.mkdir()
    for tool in ("sh", "dirname", "uname"):
        (bindir / tool).symlink_to(shutil.which(tool))
    python = bindir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    if stub_python3:
        stub = bindir / "python3"
        stub.write_text("#!/bin/sh\nexit 9009\n")
        stub.chmod(0o755)
    return bindir


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell launcher")
def test_the_shell_launcher_skips_a_python_that_does_not_run(bundle, tmp_path):
    """On Windows `python3` is often the Microsoft Store stub: found on
    PATH, opens the Store, exits non-zero. A launcher that trusted
    `command -v` would hand every command to it."""
    home = tmp_path / "a home with spaces"
    shutil.copytree(bundle, home / "mc-jarvis", symlinks=False)
    launcher = home / "mc-jarvis" / "scripts" / "mc-jarvis"
    bindir = _fake_python_dir(tmp_path, stub_python3=True)
    got = subprocess.run(
        [str(launcher), "card", "search", "tackle"],
        capture_output=True, text=True,
        env={"PATH": str(bindir), "HOME": str(tmp_path),
             "MC_JARVIS_DATA": str(tmp_path / "no-index")})
    # It ran mc_jarvis - which found no index - rather than the stub.
    assert "no index found" in (got.stdout + got.stderr), got.stderr
    # And named the launcher the reader typed, quoted so the space in its
    # path survives being pasted back into a shell.
    import shlex
    assert shlex.quote(str(launcher)) in (got.stdout + got.stderr)


def test_the_windows_launcher_ships_with_crlf(bundle):
    """cmd.exe misreads labels and `goto` in a batch file with LF
    endings. `.gitattributes` fixes the checkout; this pins the bundle."""
    data = (bundle / "scripts" / "mc-jarvis.cmd").read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
def test_the_windows_launcher_runs_from_a_folder_with_spaces(bundle, tmp_path):
    home = tmp_path / "a home with spaces"
    shutil.copytree(bundle, home / "mc-jarvis", symlinks=False)
    launcher = home / "mc-jarvis" / "scripts" / "mc-jarvis.cmd"
    got = subprocess.run(
        [str(launcher), "card", "search", "tackle"],
        capture_output=True, text=True,
        env={**os.environ, "MC_JARVIS_PYTHON": sys.executable,
             "MC_JARVIS_DATA": str(tmp_path / "no-index")})
    assert "no index found" in (got.stdout + got.stderr), got.stderr
    # Quoted, so `C:\Users\Jay Atkinson\...` survives being pasted back.
    assert f'"{launcher}"' in (got.stdout + got.stderr)
    # A failure has to reach the caller as a failure: an agent reads the
    # exit code, and "no index" is exit 1.
    assert got.returncode == 1


@pytest.mark.skipif(sys.platform == "win32", reason="runs the workflow's sh")
@pytest.mark.parametrize("tag,expected", [
    ("v0.3.0rc1", "--prerelease"), ("v0.3.0a1", "--prerelease"),
    ("v0.3.0b2", "--prerelease"), ("v0.3.0", ""), ("v1.0.0", ""),
])
def test_a_release_candidate_is_published_as_a_prerelease(tag, expected):
    """The README sends readers to /releases/latest. A release candidate
    published as an ordinary release would become "latest", and every
    new reader would install it. The workflow's own shell decides."""
    import re

    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    snippet = re.search(r'^\s*(pre="".*?esac)\s*$', workflow, re.S | re.M)
    assert snippet, "the prerelease decision is not in the publish step"
    got = subprocess.run(
        ["sh", "-c", snippet.group(1) + '\nprintf %s "$pre"'],
        capture_output=True, text=True, env={"GITHUB_REF_NAME": tag,
                                             "PATH": os.environ["PATH"]})
    assert got.stdout == expected


def _git_sh():
    """Git for Windows' own sh, which is what Claude Code runs commands
    in on Windows. Not a bare `bash`: that can resolve to the WSL stub."""
    git = shutil.which("git")
    if not git:
        return None, None
    root = Path(git).resolve().parents[1]
    sh, usr_bin = root / "bin" / "sh.exe", root / "usr" / "bin"
    return (sh, usr_bin) if sh.exists() else (None, None)


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash on Windows")
def test_the_shell_launcher_works_under_git_bash(bundle, bare_python, tmp_path):
    """The route most Windows users take first, and the only one that
    rewrites PYTHONPATH into Windows form for a native Python. Run with
    an interpreter that lacks mc_jarvis, so success means the bundled
    package was found through that rewrite."""
    sh, usr_bin = _git_sh()
    if sh is None:
        pytest.skip("Git for Windows not found")
    home = tmp_path / "a home with spaces"
    shutil.copytree(bundle, home / "mc-jarvis", symlinks=False)
    launcher = home / "mc-jarvis" / "scripts" / "mc-jarvis"
    got = subprocess.run(
        [str(sh), launcher.as_posix(), "card", "search", "tackle"],
        capture_output=True, text=True, timeout=180,
        env={**os.environ,
             "PATH": f"{usr_bin};{os.environ['PATH']}",
             "MC_JARVIS_PYTHON": str(bare_python),
             "MC_JARVIS_DATA": str(tmp_path / "no-index")})
    assert "no index found" in (got.stdout + got.stderr), got.stderr
    assert got.returncode == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
def test_the_windows_launcher_does_not_call_itself(tmp_path):
    """An `install-skill` copy has the launchers but no bundled package,
    so the .cmd looks for an installed mc-jarvis. Run from `scripts\\`,
    `where mc-jarvis` found the extensionless shell script there and
    `mc-jarvis %*` then resolved to the .cmd itself - forever."""
    skill = tmp_path / "skill"
    shutil.copytree(ROOT / "skill" / "mc-jarvis", skill, symlinks=False)
    scripts = skill / "scripts"
    got = subprocess.run(
        [str(scripts / "mc-jarvis.cmd"), "--help"],
        cwd=str(scripts), capture_output=True, text=True, timeout=120,
        env={**os.environ, "MC_JARVIS_PYTHON": sys.executable})
    assert got.returncode == 0, got.stderr
    assert "assess" in got.stdout
