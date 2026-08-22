"""Hero-specific deckbuilding overrides (not covered by spec §10).

Almost every hero follows the normal rule: choose one aspect, or none and
play all basic. A handful override it, and the override is stated only in
prose on the alter-ego card - `deck_requirements` is null on every
identity, so nothing structural marks them.

Like the setup audit, this is a scan plus an explicit acknowledgment, not
a hand-maintained list: a new release that adds an override fails the
build instead of being silently validated against the wrong rules.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

TAG_RE = re.compile(r"<[^>]+>")

# Deckbuilding overrides are constant abilities about deck COMPOSITION.
# The discriminator matters: 42 identity faces mention "your deck", but
# almost all are Action or Setup abilities that search it.
OVERRIDE_RE = re.compile(
    r"deck-?building|you may include|your deck must include|"
    r"cannot include|choose two aspects|instead of one", re.I)


class OverrideAuditError(RuntimeError):
    """An identity states a deckbuilding override nothing accounts for."""


@dataclass
class Override:
    identity_key: str
    identity_name: str
    quote: str
    covered: bool
    quote_verified: bool


def _plain(text: str) -> str:
    return " ".join(TAG_RE.sub("", text or "").split())


def scan(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """Identities whose text states a deckbuilding override.

    Returns `{identity_key: (identity_name, sentence)}`.
    """
    found: dict[str, tuple[str, str]] = {}
    for r in conn.execute(
        "SELECT f.identity_key, c.name, c.text FROM identity_faces f "
        "JOIN cards c ON c.code = f.code "
        "WHERE c.text IS NOT NULL AND c.text != '' ORDER BY f.identity_key"
    ):
        text = _plain(r["text"])
        m = OVERRIDE_RE.search(text)
        if not m or r["identity_key"] in found:
            continue
        start = text.rfind(".", 0, m.start()) + 1
        end = text.find(".", m.end())
        sentence = text[start:end + 1 if end > 0 else len(text)].strip()
        found[r["identity_key"]] = (r["name"], sentence)
    return found


def audit(conn: sqlite3.Connection, config: dict) -> list[Override]:
    """Every scanned identity must have a config entry, and each entry's
    quote must still appear in that identity's text."""
    entries = {e["identity"]: e
               for e in config.get("deckbuilding_overrides", []) or []}
    texts = {}
    for r in conn.execute(
        "SELECT f.identity_key, c.text FROM identity_faces f "
        "JOIN cards c ON c.code = f.code WHERE c.text IS NOT NULL"
    ):
        texts.setdefault(r["identity_key"], "")
        texts[r["identity_key"]] += " " + _plain(r["text"])

    out = []
    for key, (name, sentence) in scan(conn).items():
        entry = entries.get(key)
        verified = False
        if entry:
            quote = " ".join(str(entry.get("quote", "")).split()).lower()
            verified = bool(quote) and quote in texts.get(key, "").lower()
        out.append(Override(key, name, sentence, entry is not None, verified))

    # A config entry for an identity the scan no longer finds is also a
    # problem: the card was reworded and the rule may no longer apply.
    for key in entries:
        if key not in {o.identity_key for o in out}:
            out.append(Override(key, key, "(scan no longer finds this "
                                "identity)", True, False))
    return out


def check(conn: sqlite3.Connection, config: dict, *,
          strict: bool = True) -> list[Override]:
    problems = [o for o in audit(conn, config)
                if not o.covered or not o.quote_verified]
    if problems and strict:
        detail = "; ".join(
            f"{o.identity_name} ({o.identity_key}): "
            + ("no config entry" if not o.covered else "quote not found")
            + f" - {o.quote[:90]}" for o in problems)
        raise OverrideAuditError(
            f"{len(problems)} deckbuilding override(s) unaccounted for. A "
            f"hero validated against the wrong rules produces wrong advice "
            f"with no error: {detail}")
    return problems


def for_identity(conn, config: dict, identity_key: str) -> dict | None:
    for entry in config.get("deckbuilding_overrides", []) or []:
        if entry["identity"] == identity_key:
            return entry
    return None
