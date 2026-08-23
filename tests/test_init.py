import json

import pytest

from mc_jarvis import index, init, outofdeck, update
from tests.fixtures import cards as fx
# The rules pages are borrowed rather than re-invented. They were shaped
# from the real Rules Reference index in Task 13, and a second fixture
# written from memory would encode an assumption instead of the document
# (Global Constraints).
from tests.test_rules_chunk import GLYPH, PAGES, UNMAPPED


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(
        fx.PACK + fx.MATCH_FAMILY + fx.OUT_OF_DECK + fx.ARROW_CARDS))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text(json.dumps(fx.SETS))
    (tmp_path / "rules" / "txt").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def covered(monkeypatch):
    monkeypatch.setattr(outofdeck, "load_config",
                        lambda path=None: fx.CONFIG_COVERING_EMBERLINE)


@pytest.fixture
def rules_txt(data_root, monkeypatch):
    """A rulebook that carries its own alphabetical index."""
    monkeypatch.setattr(init, "INDEX_MIN_ENTRIES", 3)
    (data_root / "rules" / "txt" / "rr.txt").write_text(
        "\f".join(PAGES), encoding="utf-8")
    return data_root


def test_rebuild_runs_every_stage(data_root, covered):
    conn = index.connect(data_root / "mc.sqlite")
    counts = init.rebuild_index(conn, data_root)
    for stage in ("cards", "player_cards", "fts", "identities",
                  "out_of_deck", "traits", "keywords", "clauses",
                  "play_limits", "deckbuilding_overrides"):
        assert stage in counts, stage
    assert counts["cards"] > 0


def test_rebuild_is_idempotent(data_root, covered):
    conn = index.connect(data_root / "mc.sqlite")
    first = init.rebuild_index(conn, data_root)
    second = init.rebuild_index(conn, data_root)
    assert first == second


def test_rebuild_records_build_metadata(data_root, covered):
    conn = index.connect(data_root / "mc.sqlite")
    init.rebuild_index(conn, data_root)
    meta = {r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM build_meta")}
    assert "built_at" in meta
    assert meta["card_count"] == str(
        conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0])


def test_a_rulebook_with_an_index_is_entry_addressable(rules_txt, covered):
    conn = index.connect(rules_txt / "mc.sqlite")
    counts = init.rebuild_index(conn, rules_txt)
    assert counts["rules_entries"] >= 4
    addressable = conn.execute(
        "SELECT COUNT(*) FROM rules_entries WHERE entry_addressable = 1"
    ).fetchone()[0]
    assert addressable >= 4


def test_a_rulebook_without_an_index_is_chunked_by_page(data_root, covered):
    """Learn to Play has no alphabetical index. It must still be
    searchable, just not addressable by entry (spec §9)."""
    (data_root / "rules" / "txt" / "ltp.txt").write_text(
        "COVER\fHow to play: shuffle the encounter deck.\f"
        "Then each player draws a hand.", encoding="utf-8")
    conn = index.connect(data_root / "mc.sqlite")
    counts = init.rebuild_index(conn, data_root)
    assert counts["rules_entries"] > 0
    assert conn.execute(
        "SELECT COUNT(*) FROM rules_entries WHERE entry_addressable = 1"
    ).fetchone()[0] == 0


def test_glyphs_are_mapped_after_chunking_not_before(rules_txt, covered):
    """Mapping whole pages before chunking silently breaks the chunker.

    `apply_glyphs` swaps one private-use codepoint for a multi-word
    bracketed token, which changes how both the index line and the body
    header parse. This entry then resolves to no body at all, and against
    the real Rules Reference the damage is wider: 13 of 217 terms are
    stored as `Icon ([amplify])` rather than `Amplify Icon ([amplify])`,
    and `parse_index` derives 0 glyph names instead of 13. The entry
    count is identical either way, so nothing raises.
    """
    conn = index.connect(rules_txt / "mc.sqlite")
    init.rebuild_index(conn, rules_txt)
    body = conn.execute(
        "SELECT body FROM rules_entries WHERE term LIKE 'Amplify Icon%'"
    ).fetchone()["body"]
    assert GLYPH not in body           # the codepoint was mapped
    assert "amplify" in body           # ...to its token, in the real body


def test_unmapped_glyphs_are_named_not_counted(rules_txt, covered):
    """A codepoint the map does not cover must be reportable as a
    codepoint, so it can be looked up and added."""
    conn = index.connect(rules_txt / "mc.sqlite")
    init.rebuild_index(conn, rules_txt)
    reported = conn.execute(
        "SELECT value FROM build_meta WHERE key = 'unmapped_glyphs'"
    ).fetchone()["value"]
    assert f"U+{ord(UNMAPPED):04X}" in reported


def test_init_refuses_on_a_hard_doctor_failure(data_root, monkeypatch):
    from mc_jarvis import doctor
    monkeypatch.setattr(doctor, "has_fts5", lambda: False)

    class Args:
        json = False
        from_html = None
        browser = False
    assert init.run(Args()) == 1


def test_status_reports_a_missing_index(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MC_JARVIS_DATA", str(tmp_path))

    class Args:
        json = False
    assert update.status(Args()) == 1
    assert "init" in capsys.readouterr().out


def test_status_reports_counts_from_the_built_index(data_root, covered,
                                                    capsys):
    conn = index.connect(data_root / "mc.sqlite")
    init.rebuild_index(conn, data_root)
    conn.close()

    class Args:
        json = True
    assert update.status(Args()) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cards"] > 0
    assert payload["stale"] is False
    assert payload["built_at"]


def test_status_calls_an_old_index_stale(data_root, covered, capsys,
                                         monkeypatch):
    conn = index.connect(data_root / "mc.sqlite")
    init.rebuild_index(conn, data_root)
    conn.close()
    monkeypatch.setattr(
        update, "_age_days",
        lambda path: float(update.STALE_DAYS + 1))

    class Args:
        json = True
    update.status(Args())
    assert json.loads(capsys.readouterr().out)["stale"] is True


def test_extracting_rules_text_is_a_no_op_without_pdfs(data_root):
    assert init.extract_rules_text(data_root) == 0


@pytest.mark.integration
def test_real_entries_keep_the_words_before_a_mapped_glyph(real_index):
    """The fixture cannot show this truncation; the real document can.

    13 Rules Reference entries name an icon in their own title, and each
    must keep the words that identify it. Mapping glyphs before chunking
    clips every one of them to its last word -- `Icon ([amplify])`,
    `Damage ([consequential-damage])`, `Resource ([mental])` -- which
    raises nothing and leaves 13 entries unfindable by name.
    """
    named = [r["term"] for r in real_index.execute(
        "SELECT term FROM rules_entries WHERE term LIKE '%([%'")]
    # One per mapped codepoint in glyphs.yaml; a drop means terms are
    # being lost, not that the document changed.
    assert len(named) >= 12, named
    for term in named:
        prefix = term.split(" ([")[0]
        assert prefix not in ("Icon", "Damage", "Resource"), term


@pytest.mark.integration
def test_the_real_rules_reference_carries_enough_index_to_be_addressable():
    """The threshold that routes a rulebook to entry-chunking rather than
    page-chunking. The Rules Reference gives 217; Learn to Play gives 0."""
    from mc_jarvis import paths, pdf, rules_chunk
    src = paths.data_dir() / "rules" / "pdf"
    rr = src / "marvel-champions-rules-reference.pdf"
    if not rr.exists():
        pytest.skip("no Rules Reference PDF; run `mc-jarvis init`")
    entries = rules_chunk.parse_index(pdf.extract_pages(rr)).entries
    assert len(entries) > init.INDEX_MIN_ENTRIES
    assert 200 < len(entries) < 260


def test_status_reports_resolved_entries_not_just_rows(
        tmp_path, monkeypatch, capsys):
    """263 rows, 216 of them answerable. Printing only the total reads as
    "263 terms you can look up", which is the same "reads as an answer"
    problem the blank entries had, one layer up."""
    from types import SimpleNamespace

    from mc_jarvis import index, paths, update

    db = tmp_path / "mc.sqlite"
    conn = index.connect(db)
    conn.executemany(
        "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
        [("built_at", "2026-08-22T00:00:00+00:00"), ("card_count", "4379"),
         ("rules_resolved", "216")])
    conn.commit()
    conn.close()
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "db_path", lambda: db)
    assert update.status(SimpleNamespace(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rules_resolved"] == 216
    assert "rules_entries" in payload


def test_status_names_a_missing_rulebook(tmp_path, monkeypatch, capsys):
    """`update` only re-extracts what is on disk, so a data directory that
    never completed an `init` stays a rulebook short indefinitely. No total
    reveals which one is absent - it has to be named."""
    from types import SimpleNamespace

    from mc_jarvis import index, paths, rules_chunk, update

    db = tmp_path / "mc.sqlite"
    conn = index.connect(db)
    rules_chunk.store(conn, [rules_chunk.Entry(
        "Ability", "text", 4, "marvel-champions-rules-reference")])
    conn.commit()
    conn.close()
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "db_path", lambda: db)
    assert update.status(SimpleNamespace(json=False)) == 0
    out = capsys.readouterr().out
    assert "learn-to-play" in out
    assert "marvel-champions-rules-reference" not in out.split(
        "No rules indexed from:")[1]


def test_a_superseded_manifest_takes_the_current_rules_reference(monkeypatch):
    """The latest Rules Reference is the authority. The archive.org
    capture the manifest comes from lags FFG by months, so left alone
    `init` indexes a superseded rulebook and cites every answer to it."""
    from mc_jarvis import init as init_mod
    from mc_jarvis import manifest

    result = manifest.ManifestResult(
        docs=[manifest.RuleDoc(
            title="Rules Reference",
            url="https://cdn.example.invalid/mc_rulesreference_v17-web.pdf",
            slug="marvel-champions-rules-reference")],
        source="wayback")
    monkeypatch.setattr(manifest, "current_rr_from_mirror",
                        lambda *a, **k: manifest.MirrorLookup(
                            "ok", version="1.8",
                            url="https://mirror.example.invalid/rr_v18.pdf"))
    verdict = init_mod._current_rr(result)
    assert verdict["status"] == "behind"
    assert verdict["have"] == "1.7"
    assert verdict["current"] == "1.8"
    assert verdict["url"].endswith("rr_v18.pdf")


def test_a_current_manifest_is_left_alone(monkeypatch):
    from mc_jarvis import init as init_mod
    from mc_jarvis import manifest

    result = manifest.ManifestResult(
        docs=[manifest.RuleDoc(
            title="Rules Reference",
            url="https://cdn.example.invalid/mc_rulesreference_v18-web.pdf",
            slug="marvel-champions-rules-reference")],
        source="wayback")
    monkeypatch.setattr(manifest, "current_rr_from_mirror",
                        lambda *a, **k: manifest.MirrorLookup(
                            "ok", version="1.8", url="https://x.invalid/a.pdf"))
    assert init_mod._current_rr(result) is None


def test_an_unreadable_mirror_never_reads_as_current(monkeypatch, capsys):
    """A broken oracle must not silently disable the check. It reports
    that it could not confirm, and `init` keeps the archived edition."""
    from mc_jarvis import init as init_mod
    from mc_jarvis import manifest

    result = manifest.ManifestResult(
        docs=[manifest.RuleDoc(
            title="Rules Reference",
            url="https://cdn.example.invalid/mc_rulesreference_v17-web.pdf",
            slug="marvel-champions-rules-reference")],
        source="wayback")
    monkeypatch.setattr(manifest, "current_rr_from_mirror",
                        lambda *a, **k: manifest.MirrorLookup(
                            "nav_missing", detail="site redesigned"))
    assert init_mod._current_rr(result) is None
    assert "could not confirm" in capsys.readouterr().err


def test_a_mirrored_rulebook_must_declare_its_own_version(tmp_path, monkeypatch):
    """The only thing that makes a mirror safe is that the document states
    its version on page 1. One that will not say is refused."""
    from mc_jarvis import init as init_mod
    from mc_jarvis import pdf, rules_chunk

    target = tmp_path / "rr.pdf"
    target.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pdf, "extract_pages", lambda *a, **k: ["no version"])
    with pytest.raises(rules_chunk.VersionMismatch):
        init_mod._verify_rr(target, "1.8")

    monkeypatch.setattr(pdf, "extract_pages", lambda *a, **k: ["VeRsion 1.7"])
    with pytest.raises(rules_chunk.VersionMismatch):
        init_mod._verify_rr(target, "1.8")

    monkeypatch.setattr(pdf, "extract_pages", lambda *a, **k: ["VeRsion 1.8"])
    init_mod._verify_rr(target, "1.8")


def test_a_mirror_behind_the_manifest_is_not_taken(monkeypatch):
    """`--from-html` reads FFG's own current list, so it can be ahead of
    the mirror. Latest wins in both directions - the mirror is not
    privileged, it is just usually fresher than the archive."""
    from mc_jarvis import init as init_mod
    from mc_jarvis import manifest

    result = manifest.ManifestResult(
        docs=[manifest.RuleDoc(
            title="Rules Reference",
            url="https://cdn.example.invalid/mc_rulesreference_v19-web.pdf",
            slug="marvel-champions-rules-reference")],
        source="html")
    monkeypatch.setattr(manifest, "current_rr_from_mirror",
                        lambda *a, **k: manifest.MirrorLookup(
                            "ok", version="1.8",
                            url="https://mirror.example.invalid/rr_v18.pdf"))
    assert init_mod._current_rr(result) is None
