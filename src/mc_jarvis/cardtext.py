"""Build-time card-text parsing (spec §10).

The parse enriches, it never replaces. `cards.raw` and `cost_clauses.raw`
hold the original text and are what the CLI quotes back; the split powers
structured questions the raw text cannot answer.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

ARROW = "→"

TRAIT_RE = re.compile(r"\[\[(.+?)\]\]")
BOLD_RE = re.compile(r"<b>(.*?)</b>", re.S)
TAG_RE = re.compile(r"<[^>]+>")

# The RR excludes interrupt/response timing text from the cost.
TIMING_RE = re.compile(r"^\s*(When|After)\b(.*?),\s*(.+)$", re.S | re.I)
# A trigger with no cost at all: everything before the arrow is timing,
# and there is nothing to pay. `<b>Hero Response</b>: After your hero
# defends ... -> discard this card.`
TIMING_ONLY_RE = re.compile(r"^\s*(When|After)\b.*$", re.S | re.I)
# `If ...` is undecided by the rules text - flag, do not guess.
CONDITION_RE = re.compile(r"^\s*If\b", re.I)

KEYWORDS = (
    "surge", "toughness", "retaliate", "piercing", "overkill", "guard",
    "stalwart", "steady", "ranged", "permanent", "patrol", "quickstrike",
    "uppercut", "peril", "hinder", "restricted", "incite", "villainous",
)
KEYWORD_RE = {k: re.compile(rf"\b{k}\b", re.I) for k in KEYWORDS}


# `<b>Hero Interrupt</b> (defense): ...` - the parenthetical names which
# basic power the ability attaches to. Real game information, not noise.
QUALIFIER_RE = re.compile(r"^\s*\(([^)]{1,24})\)\s*:?\s*")


@dataclass
class CostClause:
    ordinal: int
    ability_type: str | None
    qualifier: str | None
    timing: str | None
    cost: str
    effect: str
    ambiguous: bool
    raw: str


def parse_traits(text: str | None) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for t in TRAIT_RE.findall(text):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_keywords(text: str | None) -> list[str]:
    if not text:
        return []
    plain = TAG_RE.sub(" ", text)
    return [k for k in KEYWORDS if KEYWORD_RE[k].search(plain)]


def _strip(s: str) -> str:
    return TAG_RE.sub("", s).strip().strip(".").strip()


def _split_multiple_arrows(segment: str) -> list[str]:
    if segment.count(ARROW) <= 1:
        return [segment]
    parts: list[str] = []
    buf = ""
    for sentence in re.split(r"(?<=\.)\s+", segment):
        buf = f"{buf} {sentence}".strip()
        if ARROW in buf:
            parts.append(buf)
            buf = ""
    if buf and ARROW in buf:
        parts.append(buf)
    return parts or [segment]


def parse_arrow(text: str | None) -> list[CostClause]:
    """Split `pay cost -> resolve effect`, honouring the RR's exclusion of
    interrupt and response timing text from the cost.

    Splitting on the arrow alone reports the timing clause as something the
    player must pay; that applies to roughly a third of all arrows.
    """
    if not text or ARROW not in text:
        return []

    segments = re.split(r"(?=<b>)", text)
    if len(segments) == 1:
        segments = [text]

    clauses: list[CostClause] = []
    ordinal = 0
    for segment in segments:
        if ARROW not in segment:
            continue
        for piece in _split_multiple_arrows(segment):
            before, _, after = piece.partition(ARROW)

            bold = BOLD_RE.search(before)
            ability_type = None
            if bold:
                ability_type = bold.group(1).strip().rstrip(":").strip()
                # Real markup puts the colon OUTSIDE the tag -
                # `<b>Interrupt</b>: When ...` - so it survives removing
                # the bold span and blocks the timing match. Verified
                # 2026-08-22: leaving it in drops timing extraction from
                # 282 player interrupt/response clauses to 24.
                before = before[bold.end():]

            # Both `<i>(attack)</i>:` and `(<i>defense</i>):` occur in the
            # corpus - the emphasis tags sit outside the parentheses on
            # some cards and inside on others. Dropping the tags first
            # handles both; they carry no information the parenthetical
            # does not already give.
            before = TAG_RE.sub("", before).lstrip(" :\u2014-")

            qualifier = None
            qm = QUALIFIER_RE.match(before)
            if qm:
                qualifier = qm.group(1).strip()
                before = before[qm.end():].lstrip(" :\u2014-")

            timing = None
            ambiguous = False
            body = before.strip()

            if CONDITION_RE.match(TAG_RE.sub("", body).strip()):
                # The RR exempts *timing* text for interrupts and
                # responses. It says nothing about a condition on an
                # Action, so this split is undecided by the rules.
                ambiguous = True
            else:
                m = TIMING_RE.match(body)
                if m:
                    timing = _strip(f"{m.group(1)}{m.group(2)}")
                    body = m.group(3)
                elif TIMING_ONLY_RE.match(body):
                    # No comma, so no cost was ever stated. Reporting the
                    # trigger as a cost would tell the player to pay for
                    # something that is free.
                    timing = _strip(body)
                    body = ""

            clauses.append(CostClause(
                ordinal=ordinal, ability_type=ability_type,
                qualifier=qualifier, timing=timing,
                cost=_strip(body), effect=TAG_RE.sub("", after).strip(),
                ambiguous=ambiguous, raw=piece.strip()))
            ordinal += 1
    return clauses


def build(conn: sqlite3.Connection) -> dict[str, int]:
    for table in ("card_traits", "card_keywords", "cost_clauses"):
        conn.execute(f"DELETE FROM {table}")

    traits: list[tuple] = []
    keywords: list[tuple] = []
    clauses: list[tuple] = []
    for row in conn.execute(
            "SELECT code, text FROM cards WHERE text IS NOT NULL"):
        code, text = row["code"], row["text"]
        traits.extend((code, t) for t in parse_traits(text))
        keywords.extend((code, k) for k in parse_keywords(text))
        clauses.extend(
            (code, c.ordinal, c.ability_type, c.qualifier, c.timing,
             c.cost, c.effect, int(c.ambiguous), c.raw)
            for c in parse_arrow(text))

    conn.executemany(
        "INSERT OR IGNORE INTO card_traits (code, trait) VALUES (?, ?)",
        traits)
    conn.executemany(
        "INSERT OR IGNORE INTO card_keywords (code, keyword) VALUES (?, ?)",
        keywords)
    conn.executemany(
        "INSERT OR REPLACE INTO cost_clauses "
        "(code, ordinal, ability_type, qualifier, timing, cost, effect, "
        " ambiguous, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", clauses)
    conn.commit()
    return {"traits": len(traits), "keywords": len(keywords),
            "clauses": len(clauses)}
