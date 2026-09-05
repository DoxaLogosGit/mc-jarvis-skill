from mc_jarvis import doctor


def test_fts5_detected_on_this_interpreter():
    assert doctor.has_fts5() is True


def test_pdf_backend_is_one_of_the_known_values():
    assert doctor.pdf_backend() in {"pdftotext", "pypdf", "none"}


def test_run_checks_offline_reports_no_network_checks():
    names = [c.name for c in doctor.run_checks(network=False)]
    assert "python" in names
    assert "sqlite-fts5" in names
    assert "data-dir" in names
    assert not any(n.startswith("network:") for n in names)


def test_run_checks_marks_missing_index_as_soft(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))
    check = next(c for c in doctor.run_checks(network=False)
                 if c.name == "index")
    assert check.ok is False
    assert check.hard is False   # no index yet is normal before init
    assert "init" in check.detail


def test_handle_returns_nonzero_only_on_hard_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))

    class Args:
        json = False
        network = False

    assert doctor.handle(Args()) == 0    # a missing index alone must not fail

    monkeypatch.setattr(doctor, "has_fts5", lambda: False)
    assert doctor.handle(Args()) == 1


def test_a_data_dir_that_does_not_exist_yet_is_not_a_failure(tmp_path,
                                                             monkeypatch):
    """`doctor` is the first command a new user runs, and on a machine
    where neither the data dir nor its parent existed it reported a hard
    FAIL. `init` creates the whole chain, so the question is whether the
    nearest existing ancestor is writable."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "never" / "made"))
    got = {c.name: c for c in doctor.run_checks(network=False)}
    assert got["data-dir"].ok
    assert "will be created" in got["data-dir"].detail


def test_an_unwritable_data_dir_is_still_a_failure(tmp_path, monkeypatch):
    """The relaxation must not swallow a real permissions problem."""
    monkeypatch.setenv("XDG_DATA_HOME", "/proc/nope")
    got = {c.name: c for c in doctor.run_checks(network=False)}
    assert not got["data-dir"].ok
