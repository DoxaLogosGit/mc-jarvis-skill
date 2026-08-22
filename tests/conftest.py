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
