"""Trigger timing and priority (added 2026-08-21; not in the original spec).

The ordering is the RR's own Simultaneous Timing Priority chart, which sits
inside the ABILITY entry and therefore has no header of its own and no index
line. It is parsed from the indexed rules rather than transcribed, and
compared against `expected_chart` so a revision is reported.

Pages are read from `rules_entries`, never from config, so a citation here
cannot drift away from what `rules show <term>` prints.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "_bundled" / "timing.yaml"
_CONFIG: dict | None = None

TAG_RE = re.compile(r"<[^>]+>")
PAREN_RE = re.compile(r"^(.*?)\s*\((.*?)\)\s*$")
QUOTED_RE = re.compile(r'^["“](.*)["”]$')
# The full sentence wraps across two extracted lines, so the anchor is the
# fragment that fits on one.
CHART_HEAD_RE = re.compile(
    r"of abilities with the same triggering condition", re.I)
CHART_RUNG_RE = re.compile(r"^(\d)\.\s+(.*)$")
CHART_SUB_RE = re.compile(r"^([a-e])\.\s+(.*)$")
# The Round Overview is split on step boundaries, not on newlines: step 6's
# See: list wraps onto a second line, and splitting by line truncates it.
ROUND_SPLIT_RE = re.compile(r"\n(?=\d{1,2}\.\s)")
ROUND_SEE_RE = re.compile(r"^(\d{1,2})\.\s*(.+?)\.\s*See\s*:\s*(.+?)$",
                          re.I | re.S)
ROUND_STEP_RE = re.compile(r"^(\d{1,2})\.\s*(.+?)$", re.S)


@dataclass
class Trigger:
    raw: str
    qualifier: str | None
    forced: bool
    quoted: bool
    canonical: str
    rung: int | None
    sub: str | None


def load_config(path: Path | None = None) -> dict:
    global _CONFIG
    if path is not None:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    if _CONFIG is None:
        _CONFIG = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return _CONFIG


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip().rstrip(":").strip()


def tie_breaks(conn, config: dict | None = None) -> list[dict]:
    """The refinements the chart does not carry, worded by the RR itself.

    `about` is the maintainer's own note on what each entry settles. The
    WORDING is read from `rules_entries` - the Rules Reference on the
    user's own machine, fetched by `init` - so this repository carries no
    rulebook prose. The seven entries here used to be close paraphrases,
    which is still someone else's rulebook in a public repository.

    An entry missing from the index yields `text: None` rather than a
    fabricated sentence; `blocked` already refuses when the RR is absent.
    """
    config = config if config is not None else load_config()
    out = []
    for entry in config["tie_breaks"]:
        row = conn.execute(
            "SELECT body FROM rules_entries WHERE lower(term) = lower(?) "
            "LIMIT 1", (entry["rr_entry"],)).fetchone()
        out.append(dict(entry,
                        text=_locate(row["body"] if row else None,
                                     entry.get("match") or []),
                        rr_page=page(conn, entry["rr_entry"])))
    return out


def _locate(body: str | None, match: list[str]) -> str | None:
    """The one sentence in an entry that a tie-break points at.

    `match` is the maintainer's own search terms, not a quotation - the
    same role a grep pattern plays. Printing the whole entry instead would
    put four paragraphs under each of seven headings, and print the
    `Forced` entry twice over.

    Returns None when nothing matches, so a reworded entry drops to the
    citation rather than showing a sentence that is no longer the right
    one. `entry_digests` reports the rewording separately.
    """
    if not body:
        return None
    for piece in re.split(r"(?<=[.])\s+|•\s*•?\s*|»\s*", body):
        flat = " ".join(piece.split())
        if flat and all(m.lower() in flat.lower() for m in match):
            return flat
    return None


def digest(text: str) -> str:
    """A fingerprint of rules text, so a change can be detected without
    the repository carrying the text itself.

    This project ships code and configuration only - no card text, no
    rules text. Verification anchors used to be verbatim quotations, which
    worked but put ~380 words of someone else's rulebook in a public
    repository. A digest detects any change to the passage, which is
    strictly stronger than checking that one sentence still appears.
    """
    import hashlib

    return hashlib.sha256(_canon(text).encode("utf-8")).hexdigest()[:32]


def _canon(s: str) -> str:
    """Compare RR text ignoring curly quotes and the stray space the
    extractor leaves before a closing quote (`“Interrupt ”`)."""
    s = s.replace("“", '"').replace("”", '"')
    s = re.sub(r'\s+"', '"', s)
    return " ".join(s.split()).strip().lower()


# --- citations -------------------------------------------------------

def page(conn, term: str) -> int | None:
    """The indexed page for an RR entry, or None when the entry carries no
    page (46 of 263 rows do not)."""
    row = conn.execute(
        "SELECT page FROM rules_entries WHERE lower(term) = lower(?) "
        "ORDER BY page IS NULL, id LIMIT 1", (term,)).fetchone()
    return None if row is None else row["page"]


def cite(conn, term: str) -> str:
    p = page(conn, term)
    return f"[RR {term} p.{p}]" if p is not None \
        else f"[RR {term}, page not indexed]"


# --- the chart -------------------------------------------------------

def parse_chart(body: str) -> list[dict]:
    """Extract the numbered chart with its lettered sub-tiers.

    No line-wrap repair here on purpose: the chart's lines do not wrap in
    the extracted RR, and a wrap would leave the chart short, which
    `verify_chart` reports by name. Untested repair logic would not.
    """
    lines = [" ".join(l.split()) for l in body.split("\n")]
    try:
        first = next(i for i, l in enumerate(lines) if CHART_HEAD_RE.search(l))
    except StopIteration:
        return []

    rows: list[dict] = []
    rung: int | None = None
    for line in lines[first + 1:]:
        if not line:
            continue
        m = CHART_RUNG_RE.match(line)
        if m:
            rung = int(m.group(1))
            rows.append({"rung": rung, "sub": None, "text": m.group(2).strip()})
            continue
        m = CHART_SUB_RE.match(line)
        if m and rung is not None:
            rows.append({"rung": rung, "sub": m.group(1),
                         "text": m.group(2).strip()})
            continue
        break
    return rows


def chart(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT rung, sub, text FROM timing_chart "
        "ORDER BY rung, COALESCE(sub, '')")]


def orderable(conn) -> list[dict]:
    """The chart rows that actually order against one another.

    Rungs 2 and 4 print a bare category header over their lettered tiers
    ("Interrupts", "Responses"). Those are not slots anything occupies, so
    reporting them makes a Response "resolve after Responses". Dropping
    every un-lettered rung instead loses rungs 1 and 5, which are real.
    """
    rows = chart(conn)
    lettered = {r["rung"] for r in rows if r["sub"]}
    return [r for r in rows if r["sub"] or r["rung"] not in lettered]


def chart_shape(rows: list[dict]) -> list[list]:
    """The chart's structure - rung numbers and sub-tier letters, nothing
    the rulebook wrote. Kept in config alongside the digest so a mismatch
    can still say WHICH rung moved rather than only that something did."""
    return [[r["rung"], r["sub"]] for r in rows]


def verify_chart(conn, config: dict | None = None) -> list[str]:
    """Compare the parsed chart against the shape and digest recorded on
    2026-08-21.

    Two checks, because they fail differently. The shape catches a tier
    being added, removed or re-lettered and names it. The digest catches a
    rewording that leaves the structure intact.
    """
    config = config if config is not None else load_config()
    expected = config["expected_chart"]
    rows = chart(conn)

    problems = []
    got_shape = chart_shape(rows)
    want_shape = [list(x) for x in expected["shape"]]
    if got_shape != want_shape:
        problems.append(
            f"chart has {len(got_shape)} rows, expected {len(want_shape)}; "
            f"structure is {got_shape} against {want_shape}")

    got = digest("\n".join(r["text"] for r in rows))
    if got != expected["text_digest"]:
        problems.append(
            "the chart's wording has changed since this config was "
            "verified. Run `mc-jarvis rules show Ability` to read it as "
            "your own rulebook prints it.")
    return problems


# --- classification --------------------------------------------------

def _resolve(body: str, config: dict) -> tuple[str, dict, bool] | None:
    """Map a bare trigger name onto a chart slot.

    Returns (canonical, slot, forced). `Forced` is a modifier, not a prefix
    of its own - but the full name is checked first so `Forced Interrupt`
    and `Forced Response` keep the rungs the chart gives them instead of
    collapsing onto `Interrupt` and `Response`.
    """
    alias = config["aliases"].get(body)
    canonical = alias["canonical"] if alias else body

    if canonical in config["triggers"]:
        return canonical, config["triggers"][canonical], \
            canonical.startswith("Forced")
    if canonical in config["outside_chart"]:
        return canonical, {"rung": None, "sub": None}, False

    if canonical.startswith("Forced "):
        inner = _resolve(canonical[len("Forced "):].strip(), config)
        if inner is not None:
            return inner[0], inner[1], True
    return None


def classify(prefix: str) -> Trigger | None:
    """Split a printed bold prefix into qualifier, forced and quoted flags,
    and the chart rung it occupies. Returns None for bold text that is not
    a triggered ability."""
    config = load_config()
    raw = _norm(TAG_RE.sub("", prefix or ""))
    if not raw:
        return None
    if raw in config["not_triggers"]:
        return None
    if any(re.match(p, raw) for p in config["not_trigger_patterns"]):
        return None

    # Quoted BEFORE stripping: the quotes are the whole distinction.
    body, quoted = raw, False
    m = QUOTED_RE.match(body)
    if m:
        body, quoted = _norm(m.group(1)).rstrip("."), True

    qualifier = None
    m = PAREN_RE.match(body)
    if m:
        # Any parenthetical is kept verbatim, provided what is outside it
        # resolves. That covers (Hero), (Alter-Ego), identity names, and
        # the mis-set (Alter_Ego) without a list to maintain.
        body, qualifier = m.group(1).strip(), m.group(2).strip()

    for q in sorted(config["qualifiers"], key=len, reverse=True):
        if body.lower().startswith(q.lower() + " "):
            qualifier = qualifier or q
            body = body[len(q) + 1:].strip()
            break

    body = " ".join(config["misprints"].get(w, {}).get("correct", w)
                    for w in body.split())

    resolved = _resolve(body, config)
    if resolved is None:
        return None
    canonical, slot, forced = resolved

    return Trigger(raw=raw, qualifier=qualifier, forced=forced, quoted=quoted,
                   canonical=canonical, rung=slot["rung"], sub=slot["sub"])


def classify_all(prefix: str) -> list[Trigger]:
    """Every trigger a printed prefix carries.

    Almost always one. 59042 Hecate prints "When Revealed/Defeated", which
    is two abilities under one prefix and so gets a row for each - both
    keep the prefix exactly as printed.
    """
    config = load_config()
    raw = _norm(TAG_RE.sub("", prefix or ""))
    compound = compound_for(raw, config)
    if compound:
        out = []
        for part in compound["parts"]:
            t = classify(part)
            if t is not None:
                out.append(Trigger(raw=raw, qualifier=t.qualifier,
                                   forced=t.forced, quoted=t.quoted,
                                   canonical=t.canonical, rung=t.rung,
                                   sub=t.sub))
        return out
    t = classify(raw)
    return [t] if t is not None else []


def compound_for(raw: str, config: dict | None = None) -> dict | None:
    """The compound entry for a printed prefix, by name or by digest.

    A trigger name - "When Revealed/Defeated" - is functional
    identification and is keyed literally. A whole printed ability is
    FFG's prose, so it is keyed by digest instead: 21147 Hela's Crown's
    malformed bold tag swallows its entire ability text, and this
    repository ships no card text.
    """
    config = config if config is not None else load_config()
    compounds = config["compounds"]
    hit = compounds.get(raw)
    if hit is not None:
        return hit
    return compounds.get(f"digest:{digest(raw)}")


def is_bolded_prose(prefix: str) -> bool:
    """A bold span too long to be a trigger.

    Villain and scheme cards bold whole sentences for emphasis. The cutoff
    is measured, not assumed - see `max_prefix_chars` in timing.yaml.
    `compounds` keys are exempt: 21147 Hela's Crown's malformed markup
    produces an 81-character span that really does carry two triggers.
    """
    config = load_config()
    raw = _norm(TAG_RE.sub("", prefix or ""))
    return (len(raw) > config["max_prefix_chars"]
            and compound_for(raw, config) is None)


def is_known_non_trigger(prefix: str) -> bool:
    """Bold text this reference has decided is not a trigger. Distinct from
    "did not classify", which is a gap the real-data gate reports."""
    config = load_config()
    raw = _norm(TAG_RE.sub("", prefix or ""))
    return (not raw or raw in config["not_triggers"]
            or any(re.match(p, raw) for p in config["not_trigger_patterns"]))


# --- explain ---------------------------------------------------------

def explain(conn, trigger: str) -> dict:
    t = classify(trigger)
    if t is None:
        return {"query": trigger, "canonical": None,
                "message": f"{trigger!r} is not a timing trigger this "
                           f"reference knows. Run `mc-jarvis timing` for "
                           f"the chart."}
    config = load_config()
    before: list[dict] = []
    after: list[dict] = []
    if t.rung is not None:
        key = (t.rung, t.sub or "")
        rows = orderable(conn)
        before = [r for r in rows if (r["rung"], r["sub"] or "") > key]
        after = [r for r in rows if (r["rung"], r["sub"] or "") < key]
    # Cite the entry that actually governs. An Action is not on the chart,
    # so citing ABILITY for it points a player at a list their trigger is
    # absent from.
    governing = (config["chart_source"]["rr_entry"] if t.rung is not None
                 else config["outside_chart"][t.canonical]["rr_entry"])
    return {
        "query": trigger,
        "canonical": t.canonical,
        "governing_entry": governing,
        "governing_page": page(conn, governing),
        "qualifier": t.qualifier,
        "forced": t.forced,
        "quoted": t.quoted,
        "rung": t.rung,
        "sub": t.sub,
        "aliased_from": trigger if _norm(trigger) in config["aliases"] else None,
        "resolves_before": before,
        "resolves_after": after,
        "tie_breaks": tie_breaks(conn, config),
        "cards": _cards_with(conn, t.canonical) if conn is not None else [],
    }


def _cards_with(conn, canonical: str, limit: int = 15) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT DISTINCT c.code, c.name, t.raw_prefix "
        "FROM timing_triggers t JOIN cards c ON c.code = t.code "
        "WHERE t.canonical = ? AND t.quoted = 0 ORDER BY c.code LIMIT ?",
        (canonical, limit))]


def verify_citations(conn, config: dict | None = None) -> list[str]:
    """Every Rules Reference entry this config leans on must still say what
    it said when the mapping was written.

    Each entry is fingerprinted rather than quoted, so the repository
    carries no rulebook text. That also makes the check stronger: a
    quotation only catches a rewording of the sentence quoted, while a
    digest catches any change to the passage the mapping depends on.
    """
    config = config if config is not None else load_config()
    expected = config.get("entry_digests") or {}

    broken: list[str] = []
    for term, want in sorted(expected.items()):
        row = conn.execute(
            "SELECT body FROM rules_entries WHERE lower(term) = lower(?) "
            "LIMIT 1", (term,)).fetchone()
        if row is None:
            broken.append(f"no Rules Reference entry named {term!r}")
        elif digest(row["body"]) != want:
            broken.append(
                f"{term!r} {cite(conn, term)} has changed since this "
                f"config was verified against it")
    return broken


def rr_version(conn) -> str | None:
    row = conn.execute(
        "SELECT value FROM build_meta WHERE key = 'rr_version'").fetchone()
    return (row["value"] or None) if row else None


def blocked(conn) -> list[str]:
    """Why this reference must not answer against the indexed rulebook.

    The chart and the prefix mapping are version-specific, and the Rules
    Reference has changed both between releases: 1.7 lists eight flat rungs
    and puts "When Defeated" alongside Boost, while 1.8 lists five rungs
    with lettered tiers and makes it a Forced Interrupt. Answering from the
    wrong one produces a confident, cited, wrong ruling - which is worse
    than no answer at all.
    """
    return verify_chart(conn) + verify_citations(conn)


def _refuse(conn, problems: list[str]) -> int:
    """The normal reason to land here is a Rules Reference NEWER than this
    config, not an old one: `init` and `update` both take the current
    edition. So the message points at the config being behind the
    rulebook, which is the direction a maintainer needs to act in."""
    version = rr_version(conn) or "unknown"
    print(f"Your Rules Reference is version {version}, and this timing "
          f"reference has not been updated for it:\n")
    for b in problems:
        print(f"  {b}")
    print(f"\nYour rulebook is the authority - the chart below it is what "
          f"has gone stale. Trigger ordering has changed between Rules "
          f"Reference versions before, so answering from a chart built for "
          f"a different edition would cite version {version} for a rule it "
          f"does not contain.\n\n"
          f"  mc-jarvis rules show Ability   the chart as YOUR rulebook "
          f"prints it\n"
          f"  mc-jarvis timing --round       still works; the game round "
          f"is parsed separately\n\n"
          f"If version {version} is current, config/timing.yaml needs its "
          f"`expected_chart` and `entry_digests` brought up to it.")
    return 1


# --- build -----------------------------------------------------------

def build(conn: sqlite3.Connection) -> int:
    from .cardtext import BOLD_RE
    config = load_config()

    conn.execute("DELETE FROM timing_chart")
    row = conn.execute(
        "SELECT body FROM rules_entries WHERE lower(term) = lower(?) LIMIT 1",
        (config["chart_source"]["rr_entry"],)).fetchone()
    if row is not None:
        conn.executemany(
            "INSERT INTO timing_chart (rung, sub, text) VALUES (?, ?, ?)",
            [(r["rung"], r["sub"], r["text"]) for r in parse_chart(row["body"])])

    conn.execute("DELETE FROM timing_triggers")
    rows = []
    for card in conn.execute(
            "SELECT code, text FROM cards WHERE text IS NOT NULL"):
        ordinal = 0
        for prefix in BOLD_RE.findall(card["text"] or ""):
            norm = _norm(TAG_RE.sub("", prefix))
            if (not norm or is_known_non_trigger(norm)
                    or is_bolded_prose(norm)):
                continue
            # An unclassifiable prefix is still recorded, with a NULL
            # canonical, so the real-data gate can name it. Silence here
            # is how a new trigger would slip in unnoticed.
            for t in classify_all(norm) or [None]:
                rows.append((card["code"], ordinal, norm,
                             t.qualifier if t else None,
                             int(t.forced) if t else 0,
                             int(t.quoted) if t else 0,
                             t.canonical if t else None,
                             t.rung if t else None,
                             t.sub if t else None))
                ordinal += 1
    conn.executemany(
        "INSERT OR REPLACE INTO timing_triggers "
        "(code, ordinal, raw_prefix, qualifier, forced, quoted, canonical, "
        "rung, sub) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    _build_round_steps(conn)
    conn.commit()
    return len(rows)


def _build_round_steps(conn) -> None:
    """Parse the RR's Round Overview rather than hand-copying it."""
    row = conn.execute(
        "SELECT body, source_doc FROM rules_entries "
        "WHERE lower(term) = 'round overview' LIMIT 1").fetchone()
    conn.execute("DELETE FROM round_steps")
    if row is None:
        return
    steps = []
    for chunk in ROUND_SPLIT_RE.split(row["body"]):
        chunk = " ".join(chunk.split())
        m = ROUND_SEE_RE.match(chunk)
        if m:
            steps.append((int(m.group(1)), m.group(2).strip() + ".",
                          m.group(3).strip(), row["source_doc"]))
            continue
        # Step 10 names no glossary entry. It is still a step.
        m = ROUND_STEP_RE.match(chunk)
        if m:
            steps.append((int(m.group(1)), m.group(2).strip(), "",
                          row["source_doc"]))
    conn.executemany(
        "INSERT OR REPLACE INTO round_steps "
        "(step, description, see, source_doc) VALUES (?, ?, ?, ?)", steps)


def round_structure(conn) -> list[dict]:
    return [{"step": r["step"], "description": r["description"],
             "see": [s.strip() for s in r["see"].split(",") if s.strip()],
             "source_doc": r["source_doc"]}
            for r in conn.execute(
                "SELECT * FROM round_steps ORDER BY step")]


# --- cli -------------------------------------------------------------

def handle(args) -> int:
    from .cards import _open
    from .cli import emit
    conn = _open()
    config = load_config()
    chart_cite = cite(conn, config["chart_source"]["rr_entry"])

    if getattr(args, "round", False):
        steps = round_structure(conn)
        if args.json:
            emit(steps, as_json=True)
            return 0 if steps else 1
        if not steps:
            print("round structure not indexed - run `mc-jarvis status`")
            return 1
        print(f"The game round {cite(conn, 'Round Overview')}:\n")
        for s in steps:
            print(f"{s['step']:>2}. {s['description']}")
            if s["see"]:
                print(f"    see: {', '.join(s['see'])}")
        return 0

    # The round structure is parsed from its own entry and does not depend
    # on the chart, so it is still answerable when the chart is not.
    problems = blocked(conn)

    if getattr(args, "trigger", None):
        if problems:
            if args.json:
                emit({"query": args.trigger, "canonical": None,
                      "blocked": problems,
                      "rr_version": rr_version(conn)}, as_json=True)
                return 1
            return _refuse(conn, problems)
        result = explain(conn, args.trigger)
        if args.json:
            emit(result, as_json=True)
            return 0 if result["canonical"] else 1
        if not result["canonical"]:
            print(result["message"])
            return 1
        slot = (f"rung {result['rung']}{result['sub'] or ''}"
                if result["rung"] else "not on the priority chart")
        print(f"{args.trigger}  ->  {result['canonical']}  ({slot})  "
              f"{cite(conn, result['governing_entry'])}")
        if result["forced"]:
            print("  Forced: it is not optional, and it takes priority over "
                  "a non-forced ability on the same triggering condition.")
        if result["aliased_from"]:
            print(f"  The RR defines this as equivalent to "
                  f"{result['canonical']}.")
        if result["qualifier"]:
            print(f"  Form restriction: {result['qualifier']}")
        if result["quoted"]:
            print("  Quoted: this refers to other abilities with that "
                  "trigger; the card does not have one.")
        for label, rows in (("Resolves after", result["resolves_after"]),
                            ("Resolves before", result["resolves_before"])):
            if rows:
                print(f"  {label}: " + ", ".join(r["text"] for r in rows))
        if result["cards"]:
            print("\n  Example cards:")
            for c in result["cards"][:8]:
                print(f"    {c['code']:<8} {c['name']:<28} {c['raw_prefix']}")
        return 0

    if problems:
        if args.json:
            emit({"chart": [], "blocked": problems,
                  "rr_version": rr_version(conn)}, as_json=True)
            return 1
        return _refuse(conn, problems)

    rows = chart(conn)
    refinements = tie_breaks(conn, config)
    if args.json:
        emit({"chart": rows, "tie_breaks": refinements,
              "source": dict(config["chart_source"],
                             rr_page=page(conn,
                                          config["chart_source"]["rr_entry"]))},
             as_json=True)
        return 0
    if not rows:
        print("timing chart not indexed - run `mc-jarvis status`")
        return 1
    print(f"Simultaneous timing priority, for one triggering condition "
          f"{chart_cite}:\n")
    for r in rows:
        label = f"{r['rung']}{r['sub'] or ''}."
        indent = "   " if r["sub"] else ""
        print(f"  {indent}{label:<4} {r['text']}")
    print("\nTie-breaks and refinements:")
    for tb in refinements:
        print(f"  - {tb['about']}")
        if tb["text"]:
            print(f"    {' '.join(tb['text'].split())}")
        print(f"    {cite(conn, tb['rr_entry'])}")
    return 0
