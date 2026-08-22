"""Card data acquisition (spec §6, §11).

Fetched as a tarball rather than cloned: 1.5 MB versus 11 MB, and it
removes `git` as a requirement outright.
"""
from __future__ import annotations

import io
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CARD_DATA_URL = ("https://codeload.github.com/zzorba/marvelsdb-json-data/"
                 "tar.gz/refs/heads/master")
USER_AGENT = "mc-jarvis (+https://github.com/zzorba/marvelsdb-json-data)"


@dataclass
class FetchReport:
    pack_files: int
    bytes_downloaded: int
    dest: Path


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _safe_members(tf: tarfile.TarFile, root: Path):
    """Validate before writing. Extracting a downloaded archive is the
    classic path-traversal sink; 3.12 has `filter="data"` but the floor
    is 3.10, so the check is explicit."""
    root_resolved = str(root.resolve())
    for member in tf.getmembers():
        if not member.isfile():
            continue
        parts = Path(member.name).parts
        if len(parts) < 2:
            continue
        rel = Path(*parts[1:])          # strip GitHub's "<repo>-<ref>/"
        if ".." in rel.parts:
            raise ValueError(f"unsafe path in archive: {member.name}")
        if not str((root / rel).resolve()).startswith(root_resolved):
            raise ValueError(f"unsafe path in archive: {member.name}")
        yield member, rel


def fetch_card_data(dest: Path, *, url: str = CARD_DATA_URL) -> FetchReport:
    blob = _download(url)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    pack_files = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member, rel in _safe_members(tf, dest):
            if rel.suffix != ".json":
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            out.write_bytes(src.read())
            if rel.parts[0] == "pack":
                pack_files += 1

    return FetchReport(pack_files=pack_files, bytes_downloaded=len(blob),
                       dest=dest)
