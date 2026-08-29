import pytest

from mc_jarvis import index, rules_chunk

GLYPH = ""
UNMAPPED = ""

PAGES = [
    "COVER",
    f"INDEXINDEX\nAether Surge ....................3\n"
    f"Amplify Icon ({GLYPH}) .............3\n"
    f'"Bolstered" ............. See Aether Surge\n'
    f"Cascade ........................4\n"
    f"Warding ........................4\n",
    "",
    f"GLOSSARYGLOSSARY\nAETHER SURGE\nWhen a card instructs you to surge\n"
    f"aether, add one token to the pool.\nSee also : Cascade, Warding\n"
    f"AMPLIFY ICON ({GLYPH})\nThe {GLYPH} icon marks an amplified effect.\n"
    f"Unknown glyph follows: {UNMAPPED}\n",
    "CASCADE\nA cascade resolves each effect in turn.\n"
    "WARDING\nWarding prevents the next point of damage.\n",
]


@pytest.fixture
def idx():
    return rules_chunk.parse_index(PAGES, scan_pages=2)


def test_index_yields_entries_with_pages(idx):
    assert ("Aether Surge", 3) in idx.entries
    assert ("Warding", 4) in idx.entries


def test_index_separates_redirects_from_entries(idx):
    assert any(t.strip('"“”') == "Bolstered" for t, _ in idx.redirects)
    assert not any(t.strip('"“”') == "Bolstered" for t, _ in idx.entries)


def test_glyph_names_are_derived_from_the_index(idx):
    assert idx.glyphs[GLYPH] == "Amplify Icon"


def test_quoted_and_icon_headers_are_not_rejected():
    """Requiring ^[A-Z] silently dropped 36 of 216 entries: every quoted
    term and every icon entry."""
    for header in ('“AFTER”', "ACCELERATION ICON ( )",
                   f"AMPLIFY ICON ({GLYPH})", "ALTER-EGO, ALTER-EGO FORM"):
        assert rules_chunk.HEADER_RE.match(header), repr(header)


def test_match_key_bridges_index_and_body_spellings():
    k = rules_chunk.match_key
    assert k("Delayed Effects") == k("DELAYED EFFECT")
    assert k(f"Boost, Boost Icon ({GLYPH})") == k("BOOST")
    assert k("Golden Rules") == k("THE GOLDEN RULES")
    assert k("Activation) Unique Icon") == k("UNIQUE ICON")


def test_entries_carry_body_and_page(idx):
    entries = rules_chunk.chunk_entries(PAGES, idx, source_doc="rr")
    surge = next(e for e in entries if e.term == "Aether Surge")
    assert "add one token" in " ".join(surge.body.split())
    assert surge.page == 3
    assert surge.entry_addressable is True


def test_see_also_handles_the_real_spacing_and_wrapping(idx):
    """The RR prints "See also :" with a space before the colon. A regex
    tuned to "See also:" matched nothing in the real document, and the
    failure was silent."""
    entries = rules_chunk.chunk_entries(PAGES, idx, source_doc="rr")
    surge = next(e for e in entries if e.term == "Aether Surge")
    assert surge.see_also == ["Cascade", "Warding"]
    assert "See also" not in surge.body


def test_an_entry_continues_across_a_page_break(idx):
    """ABILITY starts on one page and its timing chart is on the next.
    Stopping at the boundary would drop the chart with no error."""
    entries = rules_chunk.chunk_entries(PAGES, idx, source_doc="rr")
    amplify = next(e for e in entries if e.term.startswith("Amplify"))
    assert "amplified effect" in amplify.body


def test_wrapped_headers_are_rejoined_but_adjacent_ones_are_not():
    pages = ["", "", "",
             "PLAY RESTRICTIONS AND\nPERMISSIONS\nSome text here.\n"
             "GLOSSARY\nABILITY\nAn ability is game text.\n"]
    heads = [h for _, _, h in rules_chunk._headers(pages, first=3, last=4)]
    assert "PLAY RESTRICTIONS AND PERMISSIONS" in heads
    assert "ABILITY" in heads          # not swallowed by GLOSSARY


def test_mapped_glyphs_become_readable_tokens():
    out, unmapped = rules_chunk.apply_glyphs(f"The {GLYPH} icon",
                                             {GLYPH: "amplify"})
    assert out == "The [amplify] icon"
    assert unmapped == set()


def test_unmapped_glyphs_are_preserved_and_reported():
    out, unmapped = rules_chunk.apply_glyphs(f"x {UNMAPPED} y", {})
    assert UNMAPPED in out          # preserved verbatim, never stripped
    assert unmapped == {UNMAPPED}


def test_non_rr_documents_chunk_by_page():
    entries = rules_chunk.chunk_pages(PAGES, source_doc="ltp")
    assert all(e.entry_addressable is False for e in entries)
    assert entries[0].page == 1


def test_extraction_report_accounts_for_every_index_entry(idx):
    rep = rules_chunk.extraction_report(PAGES, idx)
    assert rep["resolved"] + len(rep["unresolved"]) == rep["index_entries"]


def test_store_is_idempotent(tmp_path, idx):
    conn = index.connect(tmp_path / "mc.sqlite")
    entries = rules_chunk.chunk_entries(PAGES, idx, source_doc="rr")
    rules_chunk.store(conn, entries)
    assert rules_chunk.store(conn, entries) == len(entries)


def test_redirects_are_excluded_from_full_text_search(tmp_path, idx):
    """A redirect has no page, and a search hit with no page could not be
    cited (spec §9)."""
    conn = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(conn, rules_chunk.chunk_entries(
        PAGES, idx, source_doc="rr"))
    # COUNT(*) on an external-content FTS table reports the CONTENT
    # table's rows, not the indexed ones, so ask by searching.
    hits = [r["term"] for r in conn.execute(
        "SELECT e.term FROM rules_fts f JOIN rules_entries e "
        "ON e.id = f.rowid WHERE rules_fts MATCH ?", ('"Aether"',))]
    assert any("Aether Surge" == h for h in hits)
    assert not any("Bolstered" in h for h in hits)
    # the redirect is still reachable by name
    assert conn.execute(
        "SELECT COUNT(*) FROM rules_entries WHERE page IS NULL"
    ).fetchone()[0] >= 1


def test_declared_version_reads_the_documents_own_claim():
    assert rules_chunk.declared_version(["VeRsion 1.8 blah"]) == "1.8"
    assert rules_chunk.declared_version(["nothing here"]) is None


def test_a_mislabelled_rules_reference_is_refused():
    with pytest.raises(rules_chunk.VersionMismatch):
        rules_chunk.verify_version(["VeRsion 1.8"], "1.7")


@pytest.mark.integration
def test_real_extraction_resolves_almost_every_entry(rules_pdf):
    """The Task 13 gate.

    `resolved` is the one that governs lookups, and it is stable across
    editions: 216 of 217 on both v1.7 and v1.8, the exception being
    `Card Anatomy`, which is a diagram and is stored as a labelled
    pointer.

    `coverage` is the share of the document's text captured into entries,
    so it moves with how much of the book is glossary: 0.887 on v1.8 (71
    pages) and 0.862 on v1.7 (68 pages). The original 0.88 floor was
    measured on v1.8 alone and failed v1.7 - which reads as a lookup
    defect and is not one. The floor now sits below both measurements and
    names them.
    """
    from mc_jarvis import pdf
    pages = pdf.extract_pages(rules_pdf, backend="pypdf")
    idx = rules_chunk.parse_index(pages)
    rep = rules_chunk.extraction_report(pages, idx)
    assert rep["resolved"] >= 216, rep["unresolved"]
    assert len(idx.entries) - rep["resolved"] <= 1, rep["unresolved"]
    assert rep["coverage"] >= 0.85, rep["coverage"]


@pytest.mark.integration
def test_real_timing_chart_survives_the_page_break(rules_pdf):
    """The chart lives inside ABILITY, which spans p.4-5. It has no
    header of its own, so a chunker that stops at the page boundary
    loses it silently."""
    from mc_jarvis import pdf
    pages = pdf.extract_pages(rules_pdf, backend="pypdf")
    idx = rules_chunk.parse_index(pages)
    entries = {e.term: e for e in rules_chunk.chunk_entries(
        pages, idx, source_doc="rr")}
    assert "Simultaneous Timing Priority" in entries["Ability"].body


@pytest.mark.integration
def test_every_real_glyph_is_named_by_the_index(rules_pdf):
    from mc_jarvis import pdf
    pages = pdf.extract_pages(rules_pdf, backend="pypdf")
    idx = rules_chunk.parse_index(pages)
    used = {c for p in pages for c in p if 0xE000 <= ord(c) <= 0xF8FF}
    assert used and not (used - set(idx.glyphs))


@pytest.mark.integration
def test_the_shipped_glyph_config_covers_the_real_document(rules_pdf):
    from mc_jarvis import pdf
    pages = pdf.extract_pages(rules_pdf, backend="pypdf")
    mapping = rules_chunk.load_glyphs()
    _, unmapped = rules_chunk.apply_glyphs("".join(pages), mapping)
    assert unmapped == set(), sorted(f"U+{ord(c):04X}" for c in unmapped)


# --- what happens to entries the chunker cannot resolve ---

MERGED_PAGES = [
    "COVER",
    "INDEXINDEX\nVariable Warding ....................4\n"
    "Card Anatomy ....................52\n",
    "",
    "GLOSSARYGLOSSARY\nWARDING\nWarding prevents the next point of damage.\n",
]


def test_a_merged_index_line_is_recovered_not_lost():
    """Two-column index lines weld a stray fragment onto a real entry:
    "Variable You, Your" is the p.49 entry "You, Your" with debris."""
    idx = rules_chunk.parse_index(MERGED_PAGES, scan_pages=2)
    entries = {e.term: e for e in rules_chunk.chunk_entries(
        MERGED_PAGES, idx, source_doc="rr")}
    assert "Warding" in entries
    assert "prevents the next point" in entries["Warding"].body
    assert entries["Warding"].entry_addressable is True


def test_an_unresolvable_entry_becomes_a_labelled_pointer():
    """Never a blank. A citation with no text still helps; an empty body
    presented as a rules entry reads as an answer."""
    idx = rules_chunk.parse_index(MERGED_PAGES, scan_pages=2)
    entries = {e.term: e for e in rules_chunk.chunk_entries(
        MERGED_PAGES, idx, source_doc="rr")}
    anatomy = entries["Card Anatomy"]
    assert anatomy.entry_addressable is False
    assert anatomy.page == 52
    assert anatomy.body                       # never empty
    assert "52" in anatomy.body


def test_pointers_are_excluded_from_full_text_search(tmp_path):
    idx = rules_chunk.parse_index(MERGED_PAGES, scan_pages=2)
    conn = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(conn, rules_chunk.chunk_entries(
        MERGED_PAGES, idx, source_doc="rr"))
    hits = [r["term"] for r in conn.execute(
        "SELECT e.term FROM rules_fts f JOIN rules_entries e "
        "ON e.id = f.rowid WHERE rules_fts MATCH ?", ('"Anatomy"',))]
    assert hits == []


def test_storing_a_blank_addressable_entry_fails_loudly(tmp_path):
    conn = index.connect(tmp_path / "mc.sqlite")
    with pytest.raises(rules_chunk.EmptyEntry, match="no body"):
        rules_chunk.store(conn, [rules_chunk.Entry(
            "Ghost", "", 12, "rr", entry_addressable=True)])


@pytest.mark.integration
def test_no_real_entry_is_stored_blank(rules_pdf, tmp_path):
    from mc_jarvis import pdf
    pages = pdf.extract_pages(rules_pdf, backend="pypdf")
    idx = rules_chunk.parse_index(pages)
    conn = index.connect(tmp_path / "mc.sqlite")
    rules_chunk.store(conn, rules_chunk.chunk_entries(
        pages, idx, source_doc="rr"))          # raises if any is blank
    assert conn.execute(
        "SELECT COUNT(*) FROM rules_entries WHERE body = ''"
    ).fetchone()[0] == 0


# --- the appendices (spec §9) ----------------------------------------

APPENDIX_PAGES = [
    "APPENDIX I: DECK APPENDIX I: DECK CUSTOMIZATION CUSTOMIZATION\n"
    "PLAYER DECKS\n"
    "A player's deck consists of a minimum of 40 cards and a maximum of "
    "50 cards.\n"
    "51 Rules Reference",
    "APPENDIX II: APPENDIX II: SETUP SETUP\n"
    "To set up a game, perform the following steps in order:\n"
    "1. Select Identities. Each player selects one identity.\n",
    "APPENDIX IV: FAQ APPENDIX IV: FAQ\nGENERAL QUESTIONS\n"
    "Q: If my hero has a tough status card, what happens? "
    "A: The tough card is discarded.\n"
    "Q: Does Webbed Up prevent Spider-Sense from triggering? "
    "A: No, it does not.\n",
    "APPENDIX V: APPENDIX V:\nERRATA ERRATA\n"
    "LOKI (#28) Should read: “Forced Interrupt: When Loki would be "
    "defeated, discard the top card.”\n",
]


def test_an_appendix_becomes_an_addressable_entry():
    """`_headers` stopped at page 49 and Appendix I begins at 49, so every
    deckbuilding rule was unreachable - which is how this project came to
    claim the Rules Reference gives no deck size at all."""
    entries = rules_chunk.chunk_appendices(APPENDIX_PAGES, first=0,
                                           source_doc="rr")
    by_term = {e.term: e for e in entries}
    assert "Appendix I: Deck Customization" in by_term
    entry = by_term["Appendix I: Deck Customization"]
    assert "minimum of 40 cards" in entry.body
    assert entry.entry_addressable and entry.searchable


def test_a_doubled_appendix_heading_is_read_once():
    """The PDF renders each appendix title twice, interleaved:
    `APPENDIX I: DECK APPENDIX I: DECK CUSTOMIZATION CUSTOMIZATION`.
    Taken literally it produces a term no one would ever type."""
    assert rules_chunk.appendix_title(
        "APPENDIX I: DECK APPENDIX I: DECK CUSTOMIZATION CUSTOMIZATION"
    ) == "Appendix I: Deck Customization"
    assert rules_chunk.appendix_title(
        "APPENDIX II: APPENDIX II: SETUP SETUP") == "Appendix II: Setup"


def test_each_faq_question_is_its_own_entry():
    """69 Q&A pairs ship inside the Rules Reference. They are
    clarifications of what this edition already says - part of the rules,
    not designer rulings that postdate them - so they belong in
    `rules_entries` and are versioned with the document."""
    entries = rules_chunk.chunk_appendices(APPENDIX_PAGES, first=0,
                                           source_doc="rr")
    faq = [e for e in entries if e.term.startswith("FAQ:")]
    assert len(faq) == 2
    assert any("Webbed Up" in e.term for e in faq)
    hit = next(e for e in faq if "Webbed Up" in e.term)
    assert "No, it does not" in hit.body
    assert hit.searchable


def test_an_errata_entry_names_its_card():
    """Errata lives under its own `APPENDIX V: ERRATA` heading in the real
    document, so the parser reads it by structure rather than scanning
    every page for the phrase - a FAQ answer quoting "Should read" would
    otherwise become an errata entry."""
    entries = rules_chunk.chunk_appendices(APPENDIX_PAGES, first=0,
                                           source_doc="rr")
    errata = [e for e in entries if e.term.startswith("Errata:")]
    assert [e.term for e in errata] == ["Errata: Loki (#28)"]
    assert "Forced Interrupt" in errata[0].body


def test_card_anatomy_is_not_chunked_by_header():
    """Pages 51-55 are card art. Their fragments match the header pattern
    - ALLY, ATK, JUSTICE, MATT MURDOCK - which is why the scan stopped
    before them. They must not become entries."""
    art = ["APPENDIX III: APPENDIX III: CARD ANATOMY CARD ANATOMY\n"
           "1. Title. The name of this card.\n",
           "IDENTITY (HERO)\nATK\nDEF\nMATT MURDOCK\nJUSTICE\n"]
    entries = rules_chunk.chunk_appendices(art, first=0, source_doc="rr")
    terms = [e.term for e in entries]
    assert "Appendix III: Card Anatomy" in terms
    for noise in ("ATK", "DEF", "MATT MURDOCK", "JUSTICE"):
        assert noise not in terms


def test_a_wrapped_appendix_title_is_read_whole():
    """The title is rendered twice AND wrapped, each line doubled on its
    own. Reading only the first line gives `Appendix I: Deck`, a name for
    nothing - which is what the first implementation produced against the
    real document."""
    assert rules_chunk.appendix_title(
        "APPENDIX I: DECK APPENDIX I: DECK",
        following=["CUSTOMIZATION CUSTOMIZATION", "PLAYER DECKS"],
    ) == "Appendix I: Deck Customization"


def test_a_section_header_is_not_mistaken_for_a_title_continuation():
    """`PLAYER DECKS` sits directly under the title and is also all-caps.
    What separates them is that a continuation is one phrase printed
    twice and a section header is not."""
    assert rules_chunk._is_doubled("CARD ANATOMY CARD ANATOMY")
    assert not rules_chunk._is_doubled("PLAYER DECKS")
    assert not rules_chunk._is_doubled("GENERAL QUESTIONS")


def test_an_acronym_survives_title_casing():
    assert rules_chunk.appendix_title(
        "APPENDIX IV: FAQ APPENDIX IV: FAQ") == "Appendix IV: FAQ"


def test_each_faq_answer_cites_the_page_it_is_printed_on():
    """The FAQ spans nine pages. Citing the appendix's first page for all
    of them is a citation for none of them, and this project's whole
    rules discipline is that a page can be checked."""
    pages = ["APPENDIX IV: FAQ APPENDIX IV: FAQ\nQ: First? A: Yes.\n",
             "Q: Second? A: Also yes.\n"]
    entries = rules_chunk.chunk_appendices(pages, first=56, source_doc="rr")
    faq = {e.term: e.page for e in entries if e.term.startswith("FAQ:")}
    assert faq["FAQ: First?"] == 56
    assert faq["FAQ: Second?"] == 57


def test_the_doubled_heading_is_not_left_in_the_body():
    pages = ["APPENDIX I: DECK APPENDIX I: DECK\nCUSTOMIZATION CUSTOMIZATION\n"
             "PLAYER DECKS\nA deck is 40 cards.\n"]
    entry = rules_chunk.chunk_appendices(pages, first=49,
                                         source_doc="rr")[0]
    assert "APPENDIX I: DECK APPENDIX" not in entry.body
    assert entry.body.startswith("PLAYER DECKS")


def test_an_answer_does_not_absorb_the_next_cards_heading():
    """The FAQ lists a card heading, then its questions. An answer runs
    straight into the next card's name, which reads as though the answer
    discussed it."""
    assert rules_chunk._trim_answer(
        "Yes, it is a replacement effect. JENNIFER WALTERS (#19B)"
    ) == "Yes, it is a replacement effect."


def test_a_product_heading_is_trimmed_but_a_single_term_is_not():
    """The FAQ is laid out product by product, so an answer runs into the
    next section's name: `... CORE SET`, `... WASP HERO PACK`. Two or
    more all-caps words in a row at the end is a heading; one is a game
    term the answer needs - `+1 ATK` must survive."""
    assert rules_chunk._trim_answer(
        "No. Only excess damage taken by the ally counts. CORE SET"
    ) == "No. Only excess damage taken by the ally counts."
    assert rules_chunk._trim_answer(
        "Machine Man gets +1 THW and +1 ATK"
    ) == "Machine Man gets +1 THW and +1 ATK"
