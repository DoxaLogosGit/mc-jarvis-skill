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
