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
         "quote": "Choose two aspects instead of one during deck-building"},
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


def test_a_covered_override_passes(conn):
    assert deckrules.check(conn, CONFIG) == []


def test_a_stale_quote_fails_loudly(conn):
    """If the card is reworded, the encoded rule may no longer apply."""
    stale = copy.deepcopy(CONFIG)
    stale["deckbuilding_overrides"][0]["quote"] = "Choose three aspects"
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
