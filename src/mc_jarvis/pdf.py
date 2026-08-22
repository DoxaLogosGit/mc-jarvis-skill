"""PDF acquisition and text extraction (spec §6, §9).

Only two extractors read the two-column Rules Reference in the correct
column order: pypdf, and `pdftotext -raw`. `pdftotext -layout` and
pdfplumber interleave the columns into unusable text - do not add them.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path

PAGE_BREAK = "\f"
USER_AGENT = "mc-jarvis"


class PdfError(RuntimeError):
    pass


def available_backends() -> list[str]:
    backends = []
    if shutil.which("pdftotext"):
        backends.append("pdftotext")
    try:
        import pypdf  # noqa: F401
        backends.append("pypdf")
    except ImportError:
        pass
    return backends


def download(url: str, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            dest.write_bytes(resp.read())
    except Exception as exc:
        raise PdfError(f"could not download {url}: {exc}") from exc
    return dest


def extract_pages(path: Path, *, backend: str | None = None) -> list[str]:
    path = Path(path)
    if not path.exists():
        raise PdfError(f"PDF not found: {path}")

    if backend is None:
        backend = "pdftotext" if shutil.which("pdftotext") else "pypdf"
    if backend not in ("pdftotext", "pypdf"):
        raise PdfError(
            f"unknown backend {backend!r}; only 'pypdf' and 'pdftotext' "
            f"read the two-column Rules Reference in the correct order")

    return (_extract_pdftotext(path) if backend == "pdftotext"
            else _extract_pypdf(path))


def _extract_pdftotext(path: Path) -> list[str]:
    # -raw preserves reading order and the sub-bullet marker.
    proc = subprocess.run(["pdftotext", "-raw", str(path), "-"],
                          capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise PdfError(f"pdftotext failed: {proc.stderr.decode()[:400]}")
    pages = proc.stdout.decode("utf-8", errors="replace").split(PAGE_BREAK)
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _extract_pypdf(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfError("pypdf is not installed") from exc
    return [(page.extract_text() or "") for page in PdfReader(str(path)).pages]
