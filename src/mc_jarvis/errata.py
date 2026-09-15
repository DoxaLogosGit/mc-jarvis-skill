"""Whether each Rules Reference erratum is reflected in the card text.

The design once recorded errata as provenance only, because four cards
checked had the correction applied. Checked across all of them, the card
data is mixed: some cards carry the corrected wording and some still
print the original. So a card's text cannot be trusted or distrusted as a
class - each erratum is checked, and the answer is stored per card.

The check reads the erratum's own gloss - `(Changed "X" to "Y".)`,
`(Added "Z".)`, `(Removed "W".)` - and tests that change alone. Comparing
the whole corrected text instead flagged cards differing only in a
plural or a word order. Where the gloss names no testable change, the
erratum is `unverified`, never guessed.
"""
from __future__ import annotations

import re

from . import manifest

Q = r"[\u201c\"\u2018']([^\u201d\"\u2019]+?)[\u201d\"\u2019]"
_TERM_RE = re.compile(r"^Errata: (.+?) \(#([^,)]+(?:, #[^,)]+)*)(?:, (.+))?\)$")
_GLOSS_RE = re.compile(r"[\u201d\"]\s*\((.+)\)\s*$")
_CHANGED_RE = re.compile(rf"(?:Changed|Replaced) (?:the )?{Q} (?:to|with) {Q}")
_ARROW_RE = re.compile(r"(?:Changed|Replaced) (?:the )?cost arrow (?:to|with) " + Q)
_ADDED_RE = re.compile(rf"Added (?:the )?{Q}")
_REMOVED_RE = re.compile(rf"Removed (?:the )?{Q}")


def _norm(text: str | None) -> str:
    text = re.sub(r"<[^>]+>|\[\[|\]\]", "", text or "")
    text = text.replace("\u2192", " arrow ").replace("\u2019", "'")
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def verdict(gloss: str, card_text: str | None) -> str:
    """`applied`, `not_applied`, or `unverified`."""
    have = _norm(card_text)
    results = []
    for old, new in _CHANGED_RE.findall(gloss):
        old, new = _norm(old), _norm(new)
        if not old.strip() and not new.strip():
            continue
        if old.strip() and old in new:
            # "Interrupt" to "Forced Interrupt": the old wording survives
            # inside the new, so only the new can be tested for.
            results.append("applied" if new in have else "not_applied")
            continue
        if new.strip() and new in have and old not in have:
            results.append("applied")
        elif old.strip() and old in have and new not in have:
            results.append("not_applied")
        else:
            results.append("unverified")
    for new in _ARROW_RE.findall(gloss):
        new = _norm(new)
        if " arrow " in have and new not in have:
            results.append("not_applied")
        elif " arrow " not in have:
            results.append("applied")
        else:
            results.append("unverified")
    for added in _ADDED_RE.findall(gloss):
        results.append("applied" if _norm(added) in have else "not_applied")
    for removed in _REMOVED_RE.findall(gloss):
        results.append("not_applied" if _norm(removed) in have else "applied")
    if "not_applied" in results:
        return "not_applied"
    if results and all(r == "applied" for r in results):
        return "applied"
    return "unverified"


def _cards_for(conn, name: str, numbers: str, pack: str | None) -> list[str]:
    wanted = _norm(name)
    codes = []
    for number in re.findall(r"\d+[A-Z]?(?:-\d+)?", numbers):
        first, _, last = number.partition("-")
        span = range(int(re.sub(r"\D", "", first)),
                     int(last or re.sub(r"\D", "", first)) + 1)
        side = re.sub(r"\d", "", first).lower()
        for pos in span:
            rows = conn.execute(
                "SELECT c.code, c.name, p.name AS pack FROM cards c "
                "LEFT JOIN packs p ON p.code = c.pack_code "
                "WHERE json_extract(c.raw, '$.position') = ? "
                "AND c.faction_code IS NOT NULL", (pos,)).fetchall()
            rows = [r for r in rows
                    if _norm(r["name"]) in wanted
                    or wanted.strip().startswith(_norm(r["name"]).strip())]
            # The Rules Reference numbers some identities by the other
            # face - `ANNA MARIE (#1A)` is 38001b here - so the side letter
            # narrows only when it agrees with the name.
            sided = [r for r in rows if side and r["code"].endswith(side)]
            rows = sided or rows
            if len(rows) > 1 and pack:
                narrowed = [r for r in rows if r["pack"] and
                            manifest.slugify(r["pack"]) in manifest.slugify(pack)]
                rows = narrowed or rows
            codes += [r["code"] for r in rows]
    return codes


def build(conn) -> dict[str, int]:
    conn.execute("DELETE FROM errata")
    counts = {"applied": 0, "not_applied": 0, "unverified": 0,
              "no_card": 0}
    for entry in conn.execute(
            "SELECT id, term, body, page, source_doc FROM rules_entries "
            "WHERE term LIKE 'Errata:%'").fetchall():
        m = _TERM_RE.match(entry["term"])
        if not m:
            continue  # a rulebook correction: no card to check
        name, numbers, pack = m.groups()
        codes = _cards_for(conn, name, numbers, pack)
        if not codes:
            counts["no_card"] += 1
            continue
        g = _GLOSS_RE.search(entry["body"])
        for code in codes:
            text = conn.execute("SELECT text FROM cards WHERE code = ?",
                                (code,)).fetchone()["text"]
            status = verdict(g.group(1) if g else "", text)
            counts[status] += 1
            conn.execute(
                "INSERT OR REPLACE INTO errata (code, entry_id, page, "
                "source_doc, status) VALUES (?, ?, ?, ?, ?)",
                (code, entry["id"], entry["page"], entry["source_doc"],
                 status))
    conn.commit()
    return {f"errata_{k}": v for k, v in counts.items()}
