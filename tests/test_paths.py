from pathlib import Path

from mc_jarvis import paths


def test_explicit_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path / "custom"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.data_dir() == tmp_path / "custom"


def test_xdg_used_when_no_explicit_var(monkeypatch, tmp_path):
    monkeypatch.delenv("MC_JARVIS_DATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.data_dir() == tmp_path / "xdg" / "mc-jarvis"


def test_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("MC_JARVIS_DATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.data_dir() == Path.home() / ".local" / "share" / "mc-jarvis"


def test_ensure_creates_subdirectories(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path / "d"))
    root = paths.ensure_data_dir()
    assert (root / "marvelsdb").is_dir()
    assert (root / "rules" / "pdf").is_dir()
    assert (root / "rules" / "txt").is_dir()


# --- naming a command the reader actually has -------------------------

def test_the_invocation_is_the_one_the_reader_typed(monkeypatch):
    """Six messages hardcoded `mc-jarvis init`. From a skill folder with
    nothing on PATH that names a command the reader does not have, and a
    live test ended with the user trying it and it failing."""
    from mc_jarvis import paths

    monkeypatch.delenv("MC_JARVIS_INVOKED_AS", raising=False)
    # A launcher execs `python -m mc_jarvis`, so argv[0] is this package.
    # Left alone the message would name the exec rather than the reader's
    # command, so the launcher passes the name through.
    monkeypatch.setattr("sys.argv", ["/skills/mc-jarvis/scripts/mc_jarvis/__main__.py"])
    assert paths.invocation() == "python -m mc_jarvis"
    monkeypatch.setenv("MC_JARVIS_INVOKED_AS", "scripts/mc-jarvis")
    assert paths.invocation() == "scripts/mc-jarvis"


def test_an_installed_console_script_is_named_bare(monkeypatch, tmp_path):
    """A wheel install puts `mc-jarvis` on PATH, where the bare name is
    the shortest true answer. Printing its absolute path would be correct
    and unhelpful."""
    from mc_jarvis import paths

    monkeypatch.delenv("MC_JARVIS_INVOKED_AS", raising=False)
    binary = tmp_path / "mc-jarvis"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr("sys.argv", [str(binary)])
    monkeypatch.setattr("shutil.which", lambda name: str(binary))
    assert paths.invocation() == "mc-jarvis"
    # Same name, different file: a bundle's launcher is also `mc-jarvis`,
    # and the bare name there would point at whatever PATH holds.
    other = tmp_path / "elsewhere" / "mc-jarvis"
    other.parent.mkdir()
    other.write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda name: str(other))
    assert paths.invocation() == str(binary)


def test_no_message_hardcodes_the_installed_name():
    """The regression this exists to stop: a new message written with the
    command spelled out, correct only for a wheel install."""
    import pathlib

    src = pathlib.Path(paths_module_dir())
    offenders = []
    for path in src.glob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if "`mc-jarvis " not in line or "invocation" in line:
                continue
            # Prose in a comment or a docstring explains; only a string
            # with a quote on the same line is something a reader is told
            # to run.
            if stripped.startswith("#") or ('"' not in line and "'" not in line):
                continue
            offenders.append(f"{path.name}:{n}")
    assert not offenders, (
        "these name the installed command in a message; use "
        f"`{{paths.invocation()}}` so it is right from a skill folder too: "
        f"{offenders}")


def paths_module_dir() -> str:
    from mc_jarvis import paths
    import os
    return os.path.dirname(paths.__file__)


def test_a_foreign_entry_point_falls_back_to_the_documented_name(monkeypatch):
    """Caught by the suite: under pytest `argv[0]` is `pytest`, so a
    message read `pytest encounter the_hood`. argv[0] is evidence only
    when it is this tool; imported as a library it names the host."""
    from mc_jarvis import paths

    monkeypatch.delenv("MC_JARVIS_INVOKED_AS", raising=False)
    for host in ("pytest", "/usr/bin/pytest", "ipython", "gunicorn"):
        monkeypatch.setattr("sys.argv", [host])
        assert paths.invocation() == "mc-jarvis", host
