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

# A keyword the card PRINTS, as against one it grants to something else.
# The distinction is load-bearing and the naive match gets it badly wrong:
# 261 encounter-deck cards mention `surge` and only 80 print it. Rhino's
# entire treachery suite says "this card gains surge" - conditional, and
# the condition is the point of the card - so a rule that counts the word
# reports an 86% surge rate for a deck whose printed rate is zero.
#
# The rule is FFG's own typography rather than a lookbehind window: a
# printed keyword stands as its own sentence, carrying nothing but
# keywords, their values, and icon tokens. Grants always carry a subject
# and a verb - `gains X`, `gains X and Y`, `loses X`, `attacks gain X` -
# and every one of those forms was measured in the corpus.
KEYWORD_ALT_RE = re.compile(
    rf"(?<![A-Za-z])({'|'.join(KEYWORDS)})\b", re.I)
# What may share a printed keyword's sentence without disqualifying it:
# its numeric value, a per-hero or resource icon, and `X`.
KEYWORD_FILLER_RE = re.compile(r"\[[^\]]*\]|\d+|\bX\b|[.,]")
# Reminder text is the publisher explaining a keyword, never a second one.
REMINDER_RE = re.compile(r"<i>.*?</i>", re.S)
BLOCK_SPLIT_RE = re.compile(r"\n|<hr\s*/?>")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.])\s+")


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


def render(text: str | None) -> str:
    """Card text as a person reads it.

    MarvelCDB stores presentation markup - `<b>Action</b>`, `<i>flavour</i>`
    - and marks trait references as `[[Trait]]`. Printing it raw means an
    agent quotes `<b>Action</b>:` back to the player. Icon tokens like
    `[amplify]` stay: they name an icon that has no plain-text form, and
    `glyphs.yaml` chose those spellings to be read aloud.

    `--json` keeps the raw text - anything computing on bold prefixes
    needs the markup that marks them.
    """
    if not text:
        return ""
    out = TRAIT_RE.sub(r"\1", text)
    return TAG_RE.sub("", out)


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


def parse_printed_keywords(text: str | None) -> list[str]:
    """Keywords the card itself carries, in `KEYWORDS` order.

    Everything before the first `<b>` trigger on a line is the card's own
    statement; anything after it is an ability, and a keyword there is
    granted or conditional. `Full Auto` is the card that makes this
    concrete - `<b>When Revealed (Alter-Ego)</b>: Surge.` surges only in
    alter-ego, so it does not print Surge.
    """
    if not text:
        return []
    found: set[str] = set()
    for block in BLOCK_SPLIT_RE.split(REMINDER_RE.sub(" ", text)):
        own = block.split("<b>")[0]
        for sentence in SENTENCE_SPLIT_RE.split(own):
            here = {m.group(1).lower()
                    for m in KEYWORD_ALT_RE.finditer(sentence)}
            if not here:
                continue
            rest = KEYWORD_FILLER_RE.sub(
                " ", KEYWORD_ALT_RE.sub(" ", sentence))
            # Anything left over is a subject or a verb, so the keyword is
            # being granted rather than printed.
            if rest.strip():
                continue
            found |= here
    return [k for k in KEYWORDS if k in found]


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
        printed = set(parse_printed_keywords(text))
        keywords.extend((code, k, int(k in printed))
                        for k in parse_keywords(text))
        clauses.extend(
            (code, c.ordinal, c.ability_type, c.qualifier, c.timing,
             c.cost, c.effect, int(c.ambiguous), c.raw)
            for c in parse_arrow(text))

    conn.executemany(
        "INSERT OR IGNORE INTO card_traits (code, trait) VALUES (?, ?)",
        traits)
    conn.executemany(
        "INSERT OR IGNORE INTO card_keywords (code, keyword, printed) "
        "VALUES (?, ?, ?)", keywords)
    conn.executemany(
        "INSERT OR REPLACE INTO cost_clauses "
        "(code, ordinal, ability_type, qualifier, timing, cost, effect, "
        " ambiguous, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", clauses)
    conn.commit()
    return {"traits": len(traits), "keywords": len(keywords),
            "clauses": len(clauses)}


# Limits stated in card text. The distinction between them is the whole
# point: "Max 1 per deck" is a deckbuilding limit that `deck_limit`
# already encodes, while "Max 1 per player" restricts how many may be in
# play - and 80 cards saying it have deck_limit 3. Reading a text "Max 1"
# as a deck limit wrongly rejects legal decks.
PER_DECK_RE = re.compile(r"max(?:imum of)?\s+(\d+)\s+per\s+deck", re.I)
IN_PLAY_RE = re.compile(
    r"max(?:imum of)?\s+(\d+)\s*(?:\[\[)?([\w\- ]*?)(?:\]\])?\s*"
    r"(?:cards?\s+)?per\s+(player|ally|minion|character|enemy|scheme|"
    r"side scheme|hero)\b", re.I)
USE_RE = re.compile(
    r"limit\s+(once|twice|\d+\s+times?)\s+per\s+(round|phase|turn|activation)"
    r"(\s+per\s+player)?", re.I)


class LimitMismatch(RuntimeError):
    """A card states a per-deck limit that `deck_limit` does not agree
    with. Verified 2026-08-22: 70 cards state one and all 70 agree, so a
    disagreement means the structured field can no longer be trusted for
    deckbuilding."""


def parse_stated_deck_limit(text: str | None) -> int | None:
    if not text:
        return None
    m = PER_DECK_RE.search(TAG_RE.sub("", text))
    return int(m.group(1)) if m else None


def parse_limits(text: str | None) -> list[tuple[str, int | None, str, str]]:
    """Play-time limits: `(kind, count, scope, verbatim phrase)`.

    Deck limits are deliberately excluded - `deck_limit` owns those.
    """
    if not text:
        return []
    plain = " ".join(TAG_RE.sub("", text).split())
    out: list[tuple[str, int | None, str, str]] = []
    for m in IN_PLAY_RE.finditer(plain):
        qualifier = " ".join(m.group(2).split()).lower()
        scope = m.group(3).lower()
        out.append(("in_play", int(m.group(1)),
                    f"{qualifier} per {scope}".strip() if qualifier
                    else scope, m.group(0).strip()))
    for m in USE_RE.finditer(plain):
        word = m.group(1).lower()
        count = {"once": 1, "twice": 2}.get(word)
        if count is None:
            digits = re.match(r"(\d+)", word)
            count = int(digits.group(1)) if digits else None
        scope = m.group(2).lower() + (" per player" if m.group(3) else "")
        out.append(("use", count, scope, m.group(0).strip()))
    return out


def build_limits(conn: sqlite3.Connection) -> dict[str, int]:
    """Populate play_limits, and assert stated per-deck limits agree with
    `deck_limit` rather than re-deriving them from prose."""
    conn.execute("DELETE FROM play_limits")
    rows: list[tuple] = []
    checked = 0
    for r in conn.execute(
            "SELECT code, name, text, deck_limit FROM cards "
            "WHERE text IS NOT NULL AND text != ''"):
        stated = parse_stated_deck_limit(r["text"])
        if stated is not None:
            checked += 1
            if r["deck_limit"] != stated:
                raise LimitMismatch(
                    f"{r['code']} ({r['name']}) says 'Max {stated} per deck' "
                    f"but deck_limit is {r['deck_limit']}; deck_limit is the "
                    f"authority for deckbuilding and no longer agrees")
        rows.extend((r["code"], kind, count, scope, phrase)
                    for kind, count, scope, phrase in parse_limits(r["text"]))

    conn.executemany(
        "INSERT OR IGNORE INTO play_limits "
        "(code, kind, count, scope, phrase) VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    return {"play_limits": len(rows), "deck_limits_checked": checked}
