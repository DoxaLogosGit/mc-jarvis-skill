import copy
import json

import pytest

from mc_jarvis import deckrules, identity, index, outofdeck
from tests.fixtures import cards as fx

OVERRIDE_HERO = [
    fx.card("ovr01a", "Prism", type_code="hero", faction_code="hero",
            set_code="prism", back_link="ovr01b", deck_limit=None,
            quantity=1),
    fx.card("ovr01b", "Ada Prism", type_code="alter_ego",
            faction_code="hero", set_code="prism", deck_limit=None,
            quantity=1,
            text="Refracted — Choose two aspects instead of one during "
                 "deck-building."),
    # Noise: searches the deck, but does not change how it is built.
    fx.card("nsy01a", "Seeker", type_code="hero", faction_code="hero",
            set_code="seeker", back_link="nsy01b", deck_limit=None,
            quantity=1),
    fx.card("nsy01b", "Ola Seek", type_code="alter_ego",
            faction_code="hero", set_code="seeker", deck_limit=None,
            quantity=1,
            text="<b>Action</b>: Search your deck for a Tech upgrade and "
                 "add it to your hand."),
]

CONFIG = {
    "version": 1,
    "out_of_deck": {"by_keyword": "permanent",
                    "by_set_type": "hero_special",
                    "exceptions": [], "acknowledged": []},
    "deckbuilding_overrides": [
        {"identity": "prism", "aspects": 2, "equal_aspects": True,
         # Filled in by `_with_digest` from the fixture's own card text:
         # the config records a fingerprint, not the text (see
         # config/legality.yaml).
         "text_digest": None},
    ],
}


@pytest.fixture
def conn(tmp_path):
    root = tmp_path / "marvelsdb"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "tst.json").write_text(json.dumps(
        fx.PACK + OVERRIDE_HERO))
    (root / "packs.json").write_text("[]")
    (root / "sets.json").write_text("[]")
    c = index.connect(tmp_path / "mc.sqlite")
    index.load_cards(c, root)
    identity.build(c)
    return c


def test_scan_finds_a_composition_override(conn):
    assert "prism" in deckrules.scan(conn)


def test_scan_ignores_abilities_that_merely_search_the_deck(conn):
    """42 identity faces mention "your deck"; almost all are Action or
    Setup abilities, not deckbuilding rules."""
    assert "seeker" not in deckrules.scan(conn)


def test_an_unaccounted_override_fails_loudly(conn):
    bare = copy.deepcopy(CONFIG)
    bare["deckbuilding_overrides"] = []
    with pytest.raises(deckrules.OverrideAuditError, match="prism"):
        deckrules.check(conn, bare)


def _with_digest(conn, config=None):
    """Fill the override's digest from the identity text in `conn`."""
    cfg = copy.deepcopy(config or CONFIG)
    texts = {}
    for r in conn.execute(
            "SELECT f.identity_key, c.text FROM identity_faces f "
            "JOIN cards c ON c.code = f.code WHERE c.text IS NOT NULL"):
        texts.setdefault(r["identity_key"], "")
        texts[r["identity_key"]] += " " + deckrules._plain(r["text"])
    for entry in cfg["deckbuilding_overrides"]:
        entry["text_digest"] = deckrules._digest(texts.get(entry["identity"], ""))
    return cfg


def test_a_covered_override_passes(conn):
    assert deckrules.check(conn, _with_digest(conn)) == []


def test_a_reworded_card_fails_loudly(conn):
    """If the card is reworded, the encoded rule may no longer apply. The
    digest catches ANY change to the identity's text, where the quotation
    it replaced only caught a rewording of the sentence quoted."""
    stale = _with_digest(conn)
    stale["deckbuilding_overrides"][0]["text_digest"] = "0" * 32
    with pytest.raises(deckrules.OverrideAuditError, match="quote not found"):
        deckrules.check(conn, stale)


def test_for_identity_returns_the_encoded_rule(conn):
    rule = deckrules.for_identity(conn, CONFIG, "prism")
    assert rule["aspects"] == 2
    assert rule["equal_aspects"] is True
    assert deckrules.for_identity(conn, CONFIG, "seeker") is None


@pytest.mark.integration
def test_real_scan_returns_exactly_seven_overrides(real_index):
    """Verified 2026-08-22. Six are commonly remembered; Wonder Man is the
    one that gets missed."""
    keys = set(deckrules.scan(real_index))
    assert keys == {"spider_woman", "warlock", "cable", "cyclops",
                    "gam", "maria_hill", "wonder_man"}, sorted(keys)


@pytest.mark.integration
def test_real_overrides_are_all_accounted_for(real_index):
    config = outofdeck.load_config()
    assert deckrules.check(real_index, config) == []


@pytest.mark.integration
def test_the_two_multi_aspect_heroes_are_encoded(real_index):
    config = outofdeck.load_config()
    assert deckrules.for_identity(real_index, config,
                                  "spider_woman")["aspects"] == 2
    warlock = deckrules.for_identity(real_index, config, "warlock")
    assert warlock["aspects"] == 4
    assert warlock["equal_aspects"] is True
    assert warlock["max_copies_non_signature"] == 1


@pytest.mark.integration
def test_every_linked_card_is_classified_out_of_deck(real_index):
    """RR p.27. 14 player cards carry the keyword and none appears in any
    published deck, so only the rulebook could have surfaced this."""
    missing = [r["code"] for r in real_index.execute(
        "SELECT c.code FROM cards c LEFT JOIN out_of_deck o ON o.code = c.code "
        "WHERE c.text LIKE '%Linked (%' AND o.code IS NULL")]
    assert missing == [], missing

    n = real_index.execute(
        "SELECT COUNT(*) FROM out_of_deck WHERE mechanism = 'linked'"
    ).fetchone()[0]
    assert n == 14, n


@pytest.mark.integration
def test_card_text_outranks_the_rulebook_and_the_config_shows_it(real_index):
    """`Golden Rules` (RR p.4) puts card text above the Rules Reference,
    which is above Learn to Play. Every `deckbuilding_overrides` entry is
    that top tier in action: Spider-Woman's card beats the one-aspect
    rule, Warlock's beats both the aspect count and `deck_limit`.

    So they are SCANNED from the identity cards rather than hand-listed
    from a rulebook - the cards are where the higher authority lives. This
    asserts the scan still finds each one, because a hand-maintained list
    would silently fall behind a release.
    """
    from mc_jarvis import deckrules

    found = set(deckrules.scan(real_index))
    expected = {"spider_woman", "warlock", "cable", "cyclops", "wonder_man",
                "gam", "maria_hill"}
    assert expected <= found, expected - found


@pytest.mark.integration
def test_the_precedence_chain_is_stated_where_we_say_it_is(real_index):
    """The claim that a card beats a rulebook is load-bearing for this
    whole design, so it is checked against the reader's own copy rather
    than trusted. If the entry moves or is reworded, this says so."""
    row = real_index.execute(
        "SELECT body, page FROM rules_entries "
        "WHERE lower(term) = 'golden rules' LIMIT 1").fetchone()
    assert row is not None, "no Golden Rules entry in the indexed rulebook"
    body = " ".join(row["body"].split()).lower()
    assert "precedence" in body
    assert "learn to play" in body
