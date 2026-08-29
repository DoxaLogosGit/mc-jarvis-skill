"""Fetch published decklists as a regression corpus for `legality.yaml`.

    uv run python tools/deck_corpus.py --days 30

FETCHED DATA. It lands under `data/` (gitignored) and never under
`tests/`. The policy gate does not cover `tests/`, so this one is on the
author rather than on the checker.

`by_date` returns complete decks - the same keys as the single-deck
endpoint - so this costs one request per day, not one per deck.
"""
import argparse
import datetime as dt
import json

from mc_jarvis import deckfetch, paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--end", default=None,
                        help="last day to fetch (default: yesterday)")
    args = parser.parse_args()

    end = (dt.date.fromisoformat(args.end) if args.end
           else dt.date.today() - dt.timedelta(days=1))
    out = deckfetch.corpus_path()
    out.mkdir(parents=True, exist_ok=True)

    total = existing = 0
    for offset in range(args.days):
        day = (end - dt.timedelta(days=offset)).isoformat()
        target = out / f"{day}.json"
        if target.exists():
            existing += 1
            continue
        decks = deckfetch.fetch_by_date(day)
        target.write_text(json.dumps(decks), encoding="utf-8")
        total += len(decks)
    print(f"{total} decks fetched into {out} ({existing} day(s) already held)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
