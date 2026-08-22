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
