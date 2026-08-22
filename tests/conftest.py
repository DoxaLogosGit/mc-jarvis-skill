import pytest

from mc_jarvis import index, paths


@pytest.fixture
def real_index():
    db = paths.db_path()
    if not db.exists():
        pytest.skip("no built index; run `mc-jarvis init`")
    return index.connect(db)
