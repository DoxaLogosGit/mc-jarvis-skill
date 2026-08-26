"""Encounter-deck membership (assess spec §5.2, as corrected by §14.5-§14.8).

Set membership is the denominator of every average `assess` reports. Get it
wrong and all the numbers are wrong while looking entirely plausible.

The rules below run in decreasing confidence, and each carries the
measurement behind it. Two earlier passes concluded that no signal existed;
both were wrong, and both times the cause was searching a single spelling.
A negative result about text in this corpus is only as strong as the
variants tried.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict

DECK = "deck"
STARTS_IN_PLAY = "starts_in_play"
SETUP_ATTACHMENT = "setup_attachment"
SET_ASIDE = "set_aside"
OTHER_DECK = "other_deck"
NOT_ENCOUNTER = "not_encounter"

# Types that can be shuffled into an encounter deck.
DECK_TYPES = ("minion", "treachery", "side_scheme", "attachment",
              "environment", "obligation")
# In play from the start; never shuffled in.
IN_PLAY_TYPES = ("villain", "main_scheme")
# Player-side cards that happen to ship in encounter sets: rescued
# captives, campaign rewards. Never in the encounter deck (§14.2).
PLAYER_TYPES = ("ally", "upgrade", "event", "support", "resource",
                "player_side_scheme", "hero", "alter_ego")

# FFG writes "Setup" both as a bold trigger and as a bare sentence opener.
# Matching only `<b>Setup</b>` misses `Setup. Attach to the villain.`
# entirely, which is how this signal was missed the first time.
SETUP_RE = re.compile(r"<b>\s*Setup\s*</b>|(?<![A-Za-z])Setup\s*[.\[]", re.I)
WHEN_REVEALED_RE = re.compile(r"<b>\s*(?:Forced\s+)?When Revealed", re.I)
# Belonging to another deck, not merely mentioning one. Measured
# 2026-08-26: 24 cards name a `[[X]] deck`, but only 6 say they go into
# it — the Infinity Stones. The other 18 refer to it ("put the top card
# of", "shuffle the", "begins the game with"), and `Infinity Gauntlet` is
# the card that makes the difference matter: it is a setup attachment that
# happens to talk about the stone deck, and a mention-match files it as a
# member of it.
#
# Note this is the ONLY membership signal needed here. The invocation,
# sense, gift, labor and weather decks are whole `hero_special` sets, so
# their membership is a set property and `outofdeck` already handles it.
OTHER_DECK_RE = re.compile(
    r"(?:Place|Put)\s+this\s+card\s+(?:in|into)\s+the\s+"
    r"\[\[([^\]]+)\]\]\s*deck", re.I)

# The ADJECTIVE, hyphenated. `set aside` (the verb) appears on 5 cards in
# the whole corpus; `set-aside` appears on 91.
_ASIDE_TYPES = r"minion|environment|ally|attachment|side scheme|treachery"
ASIDE_TRAIT_RE = re.compile(
    rf"set-aside\s+\[\[([^\]]+)\]\]\s+({_ASIDE_TYPES})", re.I)
ASIDE_NAMED_RE = re.compile(
    rf"set-aside\s+([A-Z][A-Za-z'’ -]{{2,28}}?)\s+({_ASIDE_TYPES})")
# "the set-aside area for your nemesis" is the nemesis area, not a group.
NOT_A_GROUP_RE = re.compile(r"^area\b", re.I)


def classify_card(row: dict) -> tuple[str, bool]:
    """One card's role, and whether it can rejoin the encounter deck.

    Returns `(role, returns_to_deck)`. Scenario-specific asides are NOT
    decided here: they depend on which scenario is being played, and are
    applied separately from `set_aside_groups`.
    """
    kind = row.get("type_code") or ""
    text = row.get("text") or ""

    if kind in IN_PLAY_TYPES:
        return STARTS_IN_PLAY, False
    if kind in PLAYER_TYPES or kind not in DECK_TYPES:
        return NOT_ENCOUNTER, False

    # Belongs to a different deck entirely.
    if OTHER_DECK_RE.search(text):
        return OTHER_DECK, False

    if SETUP_RE.search(text):
        # `permanent` means "cannot be discarded from play", so a Setup
        # card that is also permanent can never reach the discard pile and
        # never rejoins the deck. This is the ONLY place `permanent` is
        # load-bearing: on its own it says nothing about deck membership,
        # because several permanent cards carry a When Revealed ability and
        # are therefore demonstrably drawn from the deck.
        if row.get("permanent"):
            role = SETUP_ATTACHMENT if kind == "attachment" else STARTS_IN_PLAY
            return role, False
        # Not permanent, so it can be discarded. A When Revealed ability or
        # a boost value proves it has a use FROM the deck: both are
        # meaningless for a card that never enters one.
        returns = (bool(WHEN_REVEALED_RE.search(text))
                   or row.get("boost") is not None)
        return STARTS_IN_PLAY, returns

    return DECK, True


def set_aside_groups(rows: list[dict]) -> dict[tuple[str, str], set[str]]:
    """Card groups that other cards describe as set aside.

    Keyed by `(trait_or_name, type_code)`, valued by the set codes whose
    text refers to them. Cross-checked elsewhere against the main scheme
    `Setup` blocks — two unrelated places in the data, so a disagreement is
    a signal rather than a coin flip.
    """
    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        text = row.get("text") or ""
        for rx in (ASIDE_TRAIT_RE, ASIDE_NAMED_RE):
            for m in rx.finditer(text):
                label = m.group(1).strip()
                if NOT_A_GROUP_RE.match(label) or "[[" in label:
                    continue
                kind = m.group(2).lower().replace(" ", "_")
                groups[(label, kind)].add(row.get("set_code") or "")
    return dict(groups)


def build(conn: sqlite3.Connection) -> dict[str, int]:
    rows = [dict(r) for r in conn.execute(
        "SELECT code, name, type_code, traits, text, permanent, boost, "
        "quantity, set_code FROM cards")]

    conn.execute("DELETE FROM encounter_role")
    counts: Counter = Counter()
    payload = []
    for row in rows:
        role, returns = classify_card(row)
        # Mirrors classify_card's precedence, so `decided_by` names the
        # rule that actually fired. Checking the text first would label a
        # main scheme "setup_text" because its Contents block says Setup,
        # when the type rule is what decided it.
        kind = row.get("type_code") or ""
        text = row.get("text") or ""
        if kind in IN_PLAY_TYPES or kind in PLAYER_TYPES \
                or kind not in DECK_TYPES:
            decided = "type"
        elif role == OTHER_DECK:
            decided = "other_deck_text"
        elif SETUP_RE.search(text):
            decided = "setup_text"
        else:
            decided = "type"
        payload.append((row["code"], role, int(returns), decided))
        counts[role] += 1

    conn.executemany(
        "INSERT OR REPLACE INTO encounter_role "
        "(code, role, returns_to_deck, decided_by) VALUES (?, ?, ?, ?)",
        payload)
    conn.commit()
    return {f"role_{k}": v for k, v in counts.items()}
