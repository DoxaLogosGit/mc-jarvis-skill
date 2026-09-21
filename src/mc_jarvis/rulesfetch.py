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
        # A scenario or campaign: its pack's rulebook. "wrecking crew" is
        # the Wrecking Crew scenario pack; "kang" the Kang pack.
        from .assess import _set_key
        key = _set_key(ref)
        for row in conn.execute(
                "SELECT DISTINCT s.code, s.name AS set_name, p.name "
                "FROM cards c JOIN packs p ON p.code = c.pack_code "
                "JOIN sets s ON s.code = c.set_code "
                "WHERE s.card_set_type_code IN ('villain', 'main_scheme')"):
            if key in (row["code"], _set_key(row["set_name"] or "")):
                names.append(row["name"])
    wanted = []
    for n in names:
        slug = manifest.slugify(n)
        bare = slug.removeprefix("the-")
        for kind in ("rulesheet", "rulebook", "rulebook-and-campaign-log"):
            wanted += [f"{slug}-{kind}", f"{bare}-{kind}",
                       f"the-{bare}-{kind}"]
    hits = [by_slug[w] for w in wanted if w in by_slug]
    if not hits:
        # Last resort: every word asked for, in one rulebook's slug. A
        # live test asked for "Rise of Red Skull" and was told no document
        # existed while `the-rise-of-red-skull-rulebook` did.
        words = [w for w in manifest.slugify(ref).replace("_", "-")
                 .split("-") if w and w != "the"]
        hits = [d for d in docs if words and all(
            w in d.slug.split("-") for w in words)
            and ("rulebook" in d.slug or "rulesheet" in d.slug)]
        if len(hits) > 3:
            hits = []
    return list({d.slug: d for d in hits}.values()), label


def refresh(root, from_html=None) -> tuple[manifest.ManifestResult, list[str]]:
    """Re-read FFG's list; the slugs it added.

    From archive.org by default. A page the player saved from their own
    browser is newer than any capture, so it is taken as it is: the one
    route that sees a document posted since archive.org last looked."""
    path = root / "rules" / "manifest.json"
    old = manifest.read(path)
    if from_html:
        new = manifest.fetch_from_html(from_html)
        if not new.docs:
            raise RuntimeError(
                f"{from_html} lists no rules PDFs - save FFG's Marvel "
                f"Champions product page itself:\n  {manifest.PRODUCT_PAGE}")
        # Dated today, so a later archive.org capture older than the
        # player's own copy cannot replace it and drop what it added.
        new.captured = _dt.date.today().isoformat()
    else:
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
              f"`{paths.invocation()} init` first.")
        return 1
    have = {p.stem for p in (root / "rules" / "pdf").glob("*.pdf")}

    def reread():
        nonlocal known
        try:
            known, added = refresh(root, getattr(args, "from_html", None))
        except (RuntimeError, OSError) as exc:
            print(f"  could not refresh the list: {exc}")
            return False
        where = ("from your saved page" if known.source == "html"
                 else f"captured {known.captured}")
        print(f"  list refreshed ({where})"
              + (f"; new: {', '.join(added)}" if added else "; nothing new"))
        return True

    if args.refresh or getattr(args, "from_html", None):
        if not reread() and getattr(args, "from_html", None):
            return 1
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
    if not docs and not (args.refresh or getattr(args, "from_html", None)):
        # A product newer than the held list is the likely reason, and
        # the player has agreed to downloads: look again once.
        print(f"nothing for {label!r} in the list captured {captured}; "
              f"refreshing it...")
        if reread():
            captured = known.captured or captured
            docs, label = candidates(conn, known.docs, args.what)
    if not docs:
        print(f"mc-jarvis rules fetch: no rules document for {label!r} in "
              f"FFG's list as captured {captured}. If it is newer than "
              f"that, save FFG's product page from your browser and run "
              f"`{paths.invocation()} rules fetch {args.what} "
              f"--from-html <file>`:\n"
              f"  {manifest.PRODUCT_PAGE}\n"
              f"Core Set heroes and scenarios are covered by the Learn to "
              f"Play book and the Rules Reference.")
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
