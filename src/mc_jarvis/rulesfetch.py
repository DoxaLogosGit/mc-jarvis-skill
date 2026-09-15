"""Fetch one hero's or product's rules document on demand.

`init` fetches three rulebooks. A hero whose kit rests on a mechanic its
cards only point at - Doctor Strange's Invocation deck, Storm's Weather
deck - is set up by that hero's own rules insert, and a deck evaluation
that cannot read it guesses. FFG publishes one per hero pack and one per
campaign box, about 80 in all, so they are fetched when a question needs
one rather than all up front.

Like every rulebook, the PDF and its text live in the data directory and
never in the repository.
"""
from __future__ import annotations

import datetime as _dt

from . import init, index, manifest, paths, pdf


def _docs(root) -> manifest.ManifestResult:
    return manifest.read(root / "rules" / "manifest.json")


def candidates(conn, docs: list[manifest.RuleDoc], ref: str) -> tuple[list, str]:
    """The documents `ref` names, and what it was read as.

    A slug names itself. An identity is looked up by its hero's name and
    its pack's name, since a campaign-box hero is covered by the box's
    rulebook rather than a sheet of its own."""
    by_slug = {d.slug: d for d in docs}
    if ref in by_slug:
        return [by_slug[ref]], ref
    from .cards import identity
    found = identity(conn, ref)
    names: list[str] = []
    label = ref
    if found["identity"]:
        label = found["identity"]
        hero = found["faces"][0]
        names.append(hero["name"])
        pack = conn.execute("SELECT name FROM packs WHERE code = ?",
                            (hero["pack_code"],)).fetchone()
        if pack:
            names.append(pack["name"])
    else:
        names.append(ref)
    wanted = [f"{manifest.slugify(n)}-{kind}" for n in names
              for kind in ("rulesheet", "rulebook")]
    hits = [by_slug[w] for w in wanted if w in by_slug]
    return list({d.slug: d for d in hits}.values()), label


def refresh(root) -> tuple[manifest.ManifestResult, list[str]]:
    """Re-read FFG's list from archive.org; the slugs it added."""
    path = root / "rules" / "manifest.json"
    old = manifest.read(path)
    new = manifest.fetch_from_wayback()
    if old.captured and new.captured and new.captured < old.captured:
        return old, []
    manifest.write(new, path)
    return new, [slug for slug, what in manifest.diff(old.docs, new.docs)
                 if what == "added"]


def fetch(conn, root, doc: manifest.RuleDoc) -> bool:
    """Download and extract `doc`. False when it was already here."""
    target = root / "rules" / "pdf" / f"{doc.slug}.pdf"
    if target.exists():
        return False
    pdf.download(doc.url, target)
    pages = pdf.extract_pages(target)
    txt = root / "rules" / "txt"
    txt.mkdir(parents=True, exist_ok=True)
    (txt / f"{doc.slug}.txt").write_text("\f".join(pages), encoding="utf-8")
    return True


def handle(args) -> int:
    root = paths.data_dir()
    known = _docs(root)
    if not known.docs:
        print("mc-jarvis rules fetch: no list of rulebooks yet - run "
              "`mc-jarvis init` first.")
        return 1
    have = {p.stem for p in (root / "rules" / "pdf").glob("*.pdf")}

    def reread():
        nonlocal known
        try:
            known, added = refresh(root)
        except RuntimeError as exc:
            print(f"  could not refresh the list: {exc}")
            return False
        print(f"  list refreshed (captured {known.captured})"
              + (f"; new: {', '.join(added)}" if added else "; nothing new"))
        return True

    if args.refresh:
        reread()
    captured = known.captured or "an unknown date"

    if not args.what:
        print(f"{len(known.docs)} documents FFG listed (captured "
              f"{captured}); * = downloaded")
        for d in known.docs:
            print(f"  {'*' if d.slug in have else ' '} {d.slug}")
        return 0

    from .cards import _open
    conn = _open()
    docs, label = candidates(conn, known.docs, args.what)
    if not docs and not args.refresh:
        # A product newer than the held list is the likely reason, and
        # the player has agreed to downloads: look again once.
        print(f"nothing for {label!r} in the list captured {captured}; "
              f"refreshing it...")
        if reread():
            captured = known.captured or captured
            docs, label = candidates(conn, known.docs, args.what)
    if not docs:
        print(f"mc-jarvis rules fetch: no rules document for {label!r} in "
              f"FFG's list as captured {captured}. `mc-jarvis rules fetch` "
              f"with no argument lists what is. Core Set heroes are "
              f"covered by the Learn to Play book and the Rules Reference.")
        return 1

    fetched = []
    for doc in docs:
        try:
            if fetch(conn, root, doc):
                fetched.append(doc)
                print(f"downloaded {doc.title}")
            else:
                print(f"already have {doc.title}")
        except pdf.PdfError as exc:
            print(f"mc-jarvis rules fetch: {exc}")
            return 1
    if fetched:
        print("rebuilding the index...")
        conn.close()
        conn = index.connect(paths.db_path(), rebuild=True)
        init.rebuild_index(conn, root)
        conn.execute(
            "INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)",
            ("built_at", _dt.datetime.now(_dt.timezone.utc).isoformat()))
        conn.commit()
    print(f"search it with: mc-jarvis rules search <text>  "
          f"(results cite {', '.join(d.slug for d in docs)})")
    return 0
