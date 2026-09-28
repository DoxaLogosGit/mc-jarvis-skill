import os

import pytest

from mc_jarvis import index, paths


@pytest.fixture
def real_index():
    db = paths.db_path()
    if not db.exists():
        pytest.skip("no built index; run `mc-jarvis init`")
    return index.connect(db)


@pytest.fixture
def rules_pdf():
    """The Rules Reference on disk, if init has fetched it."""
    from mc_jarvis import paths
    candidates = sorted((paths.data_dir() / "rules" / "pdf").glob("*.pdf"))
    match = [p for p in candidates if "rules-reference" in p.name]
    if not match:
        pytest.skip("no Rules Reference fetched; run `mc-jarvis init`")
    return match[0]


def _escape(text: str, *, prop: bool) -> str:
    """GitHub workflow-command escaping: `%`, CR and LF everywhere, and
    `:` and `,` inside a property - a test id is full of `::`."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def pytest_terminal_summary(terminalreporter):
    """On GitHub Actions, name each failure as an annotation.

    Downloading a run's log needs admin rights on the repository; its
    annotations are public. Without this, a failure on a platform nobody
    here runs read only "Process completed with exit code 1".
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    stats = terminalreporter.stats
    for rep in stats.get("failed", []) + stats.get("error", []):
        lines = str(rep.longrepr).splitlines()
        detail = [l for l in lines if l.startswith("E ")][:4] or lines[-1:]
        terminalreporter.write_line(
            f"::error title={_escape(rep.nodeid, prop=True)}::"
            + _escape("\n".join(detail)[:900], prop=False))
