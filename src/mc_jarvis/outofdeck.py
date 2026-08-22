"""Cards that sit outside the constructed deck, and the audit that keeps
the list honest (spec §10)."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "_bundled" / "legality.yaml"

# Prose on an identity card implying a card starts outside the deck.
SETUP_PATTERNS = [
    re.compile(r"set\s+(?:it|them|this card|the\s+[^.]{1,40}?)\s+aside", re.I),
    re.compile(r"set\s+aside", re.I),
    re.compile(r"begins?\s+the\s+game\s+with", re.I),
    re.compile(r"begin\s+the\s+game\s+with", re.I),
]


class AuditError(RuntimeError):
    """An identity implies an out-of-deck card that nothing covers."""


@dataclass
class AuditFinding:
    identity_key: str
    identity_name: str
    quote: str
    covered: bool
    covered_by: str | None = None


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def _exception_codes(config: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for entry in config.get("out_of_deck", {}).get("exceptions", []) or []:
        out[entry["identity"]] = list(entry.get("cards") or [])
    return out


def _sentence_around(text: str, pos: int) -> str:
    start = text.rfind(".", 0, pos) + 1
    end = text.find(".", pos)
    end = len(text) if end == -1 else end + 1
    return " ".join(text[start:end].split())


def _acknowledged(config: dict) -> dict[str, dict]:
    """Identities a human has examined, from either config list."""
    out: dict[str, dict] = {}
    section = config.get("out_of_deck", {})
    for entry in section.get("exceptions", []) or []:
        out[entry["identity"]] = {"reason": "config",
                                  "note": entry.get("note")}
    for entry in section.get("acknowledged", []) or []:
        out[entry["identity"]] = {"reason": entry.get("reason", "acknowledged"),
                                  "note": entry.get("note")}
    return out


def _reason_still_holds(conn, key: str, reason: str, special_type: str) -> bool:
    """Verify a stated reason against the data, so an acknowledgment cannot
    outlive the fact it rests on."""
    if reason in ("config", "acknowledged"):
        return True
    if reason == "hero_special":
        # A hero_special set is a DIFFERENT set from the identity's own
        # (identity `iceman` -> set `iceman_frostbite`), so it cannot be
        # found by set_code. Pack is the reliable join: verified
        # 2026-08-22, exact for all six hero_special sets.
        return conn.execute(
            "SELECT 1 FROM cards sp JOIN sets s ON s.code = sp.set_code "
            "WHERE s.card_set_type_code = ? AND sp.pack_code IN ("
            "  SELECT c.pack_code FROM identity_faces f "
            "  JOIN cards c ON c.code = f.code "
            "  WHERE f.identity_key = ?) LIMIT 1",
            (special_type, key)).fetchone() is not None
    if reason == "identity_grouping":
        # The Ironheart shape. More than one alter-ego face isolates it:
        # counting faces > 2 would blanket-exempt Angel, Ant-Man and Wasp,
        # which have a second *hero* form and must stay auditable.
        return conn.execute(
            "SELECT COUNT(*) FROM identity_faces f "
            "JOIN cards c ON c.code = f.code "
            "WHERE f.identity_key = ? AND c.type_code = 'alter_ego'",
            (key,)).fetchone()[0] > 1
    if reason == "permanent":
        return conn.execute(
            "SELECT 1 FROM cards WHERE set_code = ? AND permanent = 1 "
            "LIMIT 1", (key,)).fetchone() is not None
    return False


def setup_audit(conn: sqlite3.Connection, config: dict) -> list[AuditFinding]:
    """Scan identity text for set-aside language and report identities a
    human has not yet accounted for.

    Coverage is an explicit acknowledgment in `legality.yaml`, never an
    inference. Treating "this identity's set contains some permanent card"
    as coverage is too coarse: a hero with both a permanent card and an
    unmarked set-aside card would be silently passed, and the unmarked one
    is precisely what the audit exists to catch.

    The stated reason is then verified against the data, so an
    acknowledgment cannot outlive the fact it rests on.

    It deliberately does not resolve prose to a card code: Brunnhilde's
    text says "Death Glow" while the card is "Death-Glow", so exact-match
    resolution would silently miss it.
    """
    acknowledged = _acknowledged(config)
    special_type = config["out_of_deck"]["by_set_type"]

    findings: list[AuditFinding] = []
    for row in conn.execute(
        "SELECT f.identity_key, c.code, c.name, c.text "
        "FROM identity_faces f JOIN cards c ON c.code = f.code "
        "WHERE c.text IS NOT NULL AND c.text != '' ORDER BY c.code"
    ):
        match = next((p.search(row["text"]) for p in SETUP_PATTERNS
                      if p.search(row["text"])), None)
        if match is None:
            continue

        key = row["identity_key"]
        ack = acknowledged.get(key)
        covered = bool(ack) and _reason_still_holds(
            conn, key, ack["reason"], special_type)
        findings.append(AuditFinding(
            key, row["name"], _sentence_around(row["text"], match.start()),
            covered, ack["reason"] if ack else None))

    return findings


def classify(conn: sqlite3.Connection, config: dict, *,
             strict: bool = False) -> int:
    findings = setup_audit(conn, config)
    uncovered = [f for f in findings if not f.covered]
    if uncovered and strict:
        detail = "; ".join(f"{f.identity_name} ({f.identity_key}): {f.quote}"
                           for f in uncovered)
        raise AuditError(
            f"{len(uncovered)} identity(ies) imply out-of-deck cards that "
            f"nothing covers - find the card by eye and add it to "
            f"legality.yaml: {detail}")

    conn.execute("DELETE FROM out_of_deck")
    rows: list[tuple[str, str, str | None]] = []

    for r in conn.execute("SELECT code FROM cards WHERE permanent = 1"):
        rows.append((r["code"], "permanent", None))
    for r in conn.execute(
        "SELECT c.code FROM cards c JOIN sets s ON s.code = c.set_code "
        "WHERE s.card_set_type_code = ?",
        (config["out_of_deck"]["by_set_type"],)
    ):
        rows.append((r["code"], "hero_special", None))
    # Identity faces never count toward deck size (spec §8).
    for r in conn.execute("SELECT code FROM identity_faces"):
        rows.append((r["code"], "identity", None))
    for entry in config.get("out_of_deck", {}).get("exceptions", []) or []:
        for code in entry.get("cards") or []:
            rows.append((code, "config", entry.get("note")))

    conn.executemany(
        "INSERT OR REPLACE INTO out_of_deck (code, mechanism, note) "
        "VALUES (?, ?, ?)", rows)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM out_of_deck").fetchone()[0]
