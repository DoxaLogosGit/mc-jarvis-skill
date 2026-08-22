"""Rules Reference parsing (spec §9).

Task 13 adds the index parse, glyph mapping and entry chunker. What is
here now is the version check, needed early because it is what lets a
mirrored copy of the Rules Reference be trusted: the document states its
own version, so a claim made by whatever page linked it does not have to
be taken on faith.
"""
from __future__ import annotations

import re

# The Rules Reference prints its own version on page 1, next to the
# summary of notable changes.
VERSION_RE = re.compile(r"V\s*e\s*R?\s*sion\s*(\d+\.\d+)", re.I)


def declared_version(pages: list[str]) -> str | None:
    """The version the document states about itself.

    This is what makes a mirrored copy safe to use: the file proves its
    own identity, so a claim made by whatever page linked it does not have
    to be taken on trust.
    """
    if not pages:
        return None
    m = VERSION_RE.search(pages[0])
    return m.group(1) if m else None


class VersionMismatch(RuntimeError):
    """A downloaded Rules Reference is not the version it was said to be."""


def verify_version(pages: list[str], expected: str | None) -> str | None:
    found = declared_version(pages)
    if expected and found and found != expected:
        raise VersionMismatch(
            f"downloaded Rules Reference declares version {found}, but was "
            f"listed as {expected}; refusing to index it")
    return found
