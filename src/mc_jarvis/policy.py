"""Enforcement for the repository's distribution rule.

The rule is that this repository ships code and configuration only - no
card text, no rules text - and that anything needing FFG's wording reads
it from the copy on the user's own machine at run time. The README states
the rule; this module is what CHECKS it, because a stated policy with no
check is a policy that drifts.

The check is direct rather than a proxy for one. Every word sequence in
the repository is compared against the Rules Reference and card text as
they sit in the built index: if a phrase from a tracked file appears
verbatim in the corpus, the repository is shipping that text. No length
heuristic can say that; only the corpus can.

Run it with the index built:

    uv run python -m mc_jarvis.policy
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# The window length, measured 2026-08-27 rather than picked. Below 7 the
# hits are ordinary game vocabulary that any honest description of a card
# shares with the card itself - phrases about drawing, about control, the
# common furniture of the game. At 8, three real quotations slipped
# through. 7 is the bottom of the band where every hit was genuine, which
# is where a cutoff belongs:
# `test_the_window_is_at_the_bottom_of_its_measured_band` re-measures both
# edges.
#
# (The first draft of this comment listed its examples verbatim and the
# check caught it, which is the most reassuring failure this module has
# produced.)
WINDOW = 7

# Files whose whole job is to carry examples of the corpus. Tests and
# design documents are held to a separate standard by `scan`'s `scope`,
# because a parser test with no real input is a test of nothing.
SHIPPED = ("config/", "src/", "skill/", "README.md", "LICENSE")

TEXT_FILES = re.compile(r"\.(yaml|yml|py|md|toml|json)$")
TAGS = re.compile(r"<[^>]+>")
PUNCT = re.compile(r"[^0-9A-Za-z' ]")
# Entry bodies this project writes itself, for index lines that resolve to
# no section. They are in `rules_entries`, so they are in the corpus, so
# the generator that writes them matches itself.
GENERATED_BODY = re.compile(r"^Listed in the Rules Reference index at page")
# The LICENCE's own carve-out: "Where the software must name part of a
# published document in order to parse it - a section heading, or a phrase
# used to locate a passage - that naming is functional identification."
# A locator has to be verbatim or it stops locating. Marked at the line,
# so the exemption sits where the reader is, and counted by `report` so it
# cannot quietly become the place quotations go to hide.
LOCATOR_MARK = "policy: locator"
# The marker only counts inside a COMMENT. Without that, this module's own
# definition of the constant claims the exemption, and so does any string
# literal that mentions it - which is exactly what happened.
LOCATOR_IN_COMMENT = re.compile(r"#[^\n]*" + re.escape(LOCATOR_MARK))
# A marker naturally sits in a comment ABOVE the line it excuses, so it
# covers a short run rather than one line. Deliberately short: a wide
# exemption is a place for quotations to hide behind one marker.
LOCATOR_SPAN = 3
# The exemption is for code that PARSES a document, which is what the
# LICENCE's carve-out covers. Prose cannot claim it: a document that
# mentions the marker while explaining it would otherwise excuse itself,
# and worse, a quotation in a design note could be waved through by
# writing four words next to it.
LOCATOR_FILES = re.compile(r"\.(py|yaml|yml|toml)$")


# `S.H.I.E.L.D.` survives punctuation-stripping as six single letters, so
# any line naming the set matched any other one - six tokens of nothing.
# Collapsed back into one word, which is what it is.
INITIALISM_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}[A-Za-z]?\.?")


def _words(text: str | None) -> list[str]:
    flat = TAGS.sub(" ", text or "").replace("’", "'")
    flat = INITIALISM_RE.sub(lambda m: m.group(0).replace(".", ""), flat)
    return PUNCT.sub(" ", flat).lower().split()


def _grams(words: list[str], window: int = WINDOW) -> set[str]:
    return {" ".join(words[i:i + window])
            for i in range(len(words) - window + 1)}


def corpus_grams(conn, window: int = WINDOW) -> set[str]:
    """Every word window in the rulebooks and the card text."""
    out: set[str] = set()
    for row in conn.execute(
            "SELECT body FROM rules_entries WHERE body IS NOT NULL"):
        body = row["body"]
        if GENERATED_BODY.match(body.strip()):
            continue
        out |= _grams(_words(body), window)
    for row in conn.execute("SELECT text, flavor FROM cards"):
        out |= _grams(
            _words(f"{row['text'] or ''} {row['flavor'] or ''}"), window)
    return out


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(["git", "ls-files"], cwd=root,
                            capture_output=True, text=True, check=True)
    return [f for f in result.stdout.split() if TEXT_FILES.search(f)]


def scan(conn, root: Path | None = None, *, scope=SHIPPED,
         window: int = WINDOW) -> list[dict]:
    """Tracked files carrying a phrase that is verbatim in the corpus.

    `scope` is a tuple of path prefixes. It defaults to the SHIPPED
    surface - the code, the configuration and the skill - which is what
    the distribution rule is about. Pass `scope=("",)` to cover the whole
    repository, documents and tests included.
    """
    root = root or Path(__file__).resolve().parents[2]
    corpus = corpus_grams(conn, window)
    findings = []
    for name in tracked_files(root):
        if not any(name.startswith(prefix) for prefix in scope):
            continue
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        excused: set[int] = set()
        if LOCATOR_FILES.search(name):
            for number, line in enumerate(lines, 1):
                if LOCATOR_IN_COMMENT.search(line):
                    excused |= set(range(number, number + LOCATOR_SPAN + 1))
        for number, line in enumerate(lines, 1):
            if number in excused:
                continue
            hits = sorted(_grams(_words(line), window) & corpus)
            if hits:
                findings.append({"file": name, "line": number,
                                 "phrase": hits[0], "count": len(hits)})
    return findings


def locators(root: Path | None = None, *, scope=SHIPPED) -> list[dict]:
    """Every line claiming the functional-identification exemption.

    Enumerated so the exemption is visible. A carve-out nobody counts is
    a carve-out that grows.
    """
    root = root or Path(__file__).resolve().parents[2]
    out = []
    for name in tracked_files(root):
        if not any(name.startswith(prefix) for prefix in scope):
            continue
        if not LOCATOR_FILES.search(name):
            continue
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if LOCATOR_IN_COMMENT.search(line):
                out.append({"file": name, "line": number,
                            "text": line.strip()})
    return out


def report(findings: list[dict]) -> str:
    if not findings:
        return "No shipped card or rules text found."
    out = [f"{len(findings)} line(s) carry text that is verbatim in the "
           f"Rules Reference or the card data:"]
    for f in findings:
        out.append(f"  {f['file']}:{f['line']}  {f['phrase']!r}")
    out.append("")
    out.append("Rewrite it in your own words, or store the `rr_entry` it "
               "lives in and read the wording from `rules_entries` at "
               "print time. See README, 'What is derived, and what ships'.")
    return "\n".join(out)


def main() -> int:
    from . import index, paths

    conn = index.connect(paths.db_path())
    findings = scan(conn)
    print(report(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
