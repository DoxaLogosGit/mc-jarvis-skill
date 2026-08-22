import pytest

from mc_jarvis import pdf


@pytest.fixture
def column_ordered_pdf(tmp_path):
    """A two-column page whose content stream is ordered by column.

    That ordering is the point. pypdf extracts in content-stream order,
    so "reads two columns correctly" is a property of the DOCUMENT, not
    of the extractor: a page emitted row-by-row comes back interleaved
    from every backend. Real layout tools emit column by column, and the
    Rules Reference is one of them - which is why the real-corpus test
    below is the one that actually guards spec §9.
    """
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed (dev extra)")
    path = tmp_path / "two_col.pdf"
    c = canvas.Canvas(str(path))
    for i, y in enumerate(range(700, 500, -20)):
        c.drawString(60, y, f"LEFT{i}")
    for i, y in enumerate(range(700, 500, -20)):
        c.drawString(330, y, f"RIGHT{i}")
    c.showPage()
    c.drawString(60, 700, "PAGE2")
    c.save()
    return path


def test_pages_are_returned_one_per_page(column_ordered_pdf):
    pages = pdf.extract_pages(column_ordered_pdf, backend="pypdf")
    assert len(pages) == 2
    assert "PAGE2" in pages[1]


def test_a_column_ordered_stream_is_preserved(column_ordered_pdf):
    text = pdf.extract_pages(column_ordered_pdf, backend="pypdf")[0]
    assert text.index("LEFT0") < text.index("LEFT9") < text.index("RIGHT0")


def test_unknown_backend_is_rejected(column_ordered_pdf):
    with pytest.raises(pdf.PdfError, match="unknown backend"):
        pdf.extract_pages(column_ordered_pdf, backend="pdfplumber")


def test_available_backends_are_from_the_known_set():
    assert set(pdf.available_backends()) <= {"pdftotext", "pypdf"}
    assert pdf.available_backends()          # at least one must work


def test_missing_file_raises_clearly(tmp_path):
    with pytest.raises(pdf.PdfError, match="not found"):
        pdf.extract_pages(tmp_path / "nope.pdf")


def test_both_backends_agree_on_page_count(column_ordered_pdf):
    """The chunker assumes page indices are comparable between backends."""
    counts = {b: len(pdf.extract_pages(column_ordered_pdf, backend=b))
              for b in pdf.available_backends()}
    assert len(set(counts.values())) == 1, counts


@pytest.mark.integration
def test_the_real_rules_reference_reads_in_column_order(rules_pdf):
    """The guarantee spec §9 actually rests on: a glossary entry's body
    must follow its header contiguously, not be cut in half by text from
    the neighbouring column."""
    pages = pdf.extract_pages(rules_pdf, backend="pypdf")
    assert len(pages) > 60
    page = next(p for p in pages if "SIMULTANEOUS RESOLUTION" in p)
    head = page.index("SIMULTANEOUS RESOLUTION")
    # Normalise: extracted lines wrap mid-phrase, so a raw substring
    # search fails on text that is perfectly correct.
    body = " ".join(page[head:head + 320].split())
    assert "the first player determines the order in which the effects " \
           "resolve" in body


@pytest.mark.integration
def test_both_backends_agree_on_the_real_page_count(rules_pdf):
    counts = {b: len(pdf.extract_pages(rules_pdf, backend=b))
              for b in pdf.available_backends()}
    assert len(set(counts.values())) == 1, counts
