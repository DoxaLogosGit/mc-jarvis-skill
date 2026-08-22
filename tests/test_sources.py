import io
import json
import tarfile

import pytest

from mc_jarvis import sources


def _fake_tarball():
    """Shaped like GitHub's: one top-level prefix directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, body in [
            ("marvelsdb-json-data-master/pack/core.json",
             json.dumps([{"code": "01001a", "name": "Test Hero"}])),
            ("marvelsdb-json-data-master/pack/gmw.json",
             json.dumps([{"code": "02001", "name": "Test Ally"}])),
            ("marvelsdb-json-data-master/packs.json", json.dumps([])),
            ("marvelsdb-json-data-master/sets.json", json.dumps([])),
            ("marvelsdb-json-data-master/README.md", "ignore me"),
        ]:
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_extracts_and_strips_the_github_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "_download", lambda url: _fake_tarball())
    report = sources.fetch_card_data(tmp_path / "marvelsdb")
    assert (tmp_path / "marvelsdb" / "pack" / "core.json").is_file()
    assert (tmp_path / "marvelsdb" / "packs.json").is_file()
    assert report.pack_files == 2


def test_refuses_path_traversal_members(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"pwned"
        info = tarfile.TarInfo("marvelsdb-json-data-master/../../evil.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(sources, "_download", lambda url: buf.getvalue())
    with pytest.raises(ValueError, match="unsafe path"):
        sources.fetch_card_data(tmp_path / "marvelsdb")
    assert not (tmp_path.parent / "evil.json").exists()


def test_replaces_previous_contents(tmp_path, monkeypatch):
    dest = tmp_path / "marvelsdb"
    (dest / "pack").mkdir(parents=True)
    (dest / "pack" / "stale.json").write_text("[]")
    monkeypatch.setattr(sources, "_download", lambda url: _fake_tarball())
    sources.fetch_card_data(dest)
    assert not (dest / "pack" / "stale.json").exists()


@pytest.mark.integration
def test_real_tarball_has_the_expected_shape(tmp_path):
    report = sources.fetch_card_data(tmp_path / "marvelsdb")
    assert report.pack_files > 100          # 116 at time of writing
    assert report.bytes_downloaded < 5_000_000
