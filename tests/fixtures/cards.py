"""Hand-invented cards in marvelsdb shape. No FFG text appears here.

Each group exists to exercise a specific trap the design identified;
the comment on each says which.
"""


def card(code, name, **kw):
    base = {
        "code": code, "name": name, "type_code": "ally",
        "faction_code": "leadership", "pack_code": "tst",
        "set_code": "tester", "quantity": 3, "deck_limit": 3,
        "cost": 2, "text": "", "traits": "", "is_unique": False,
    }
    base.update(kw)
    return base


PACK = [
    card("tst01a", "Tester", type_code="hero", faction_code="hero",
         deck_limit=None, quantity=1, cost=None, back_link="tst01b",
         hand_size=5, health=10),
    card("tst01b", "Terry Tester", type_code="alter_ego",
         faction_code="hero", deck_limit=None, quantity=1, cost=None,
         hand_size=6, health=10),
    card("tst02", "Ordinary Ally", cost=3, quantity=3, deck_limit=3),
    card("tst03", "Limited Signature", faction_code="hero",
         deck_limit=None, quantity=2),
]

INVARIANT_VIOLATION = card("tst99", "Impossible Card",
                           quantity=1, deck_limit=3)

# RR p.45 unique-match. String equality fails in BOTH directions: it misses
# the ally that matches via subname, and falsely matches two heroes that
# share a title but have different alter-egos.
MATCH_FAMILY = [
    card("mtc01a", "Nightjar", type_code="hero", faction_code="hero",
         set_code="nightjar", is_unique=True, back_link="mtc01b",
         deck_limit=None, quantity=1),
    card("mtc01b", "Ada Vance", type_code="alter_ego", faction_code="hero",
         set_code="nightjar", is_unique=True, deck_limit=None, quantity=1),
    card("mtc02", "Ada Vance", type_code="ally", is_unique=True,
         deck_limit=1, quantity=1, set_code=None),
    card("mtc03", "Nightjar", subname="Ada Vance", type_code="ally",
         is_unique=True, deck_limit=1, quantity=1, set_code=None),
    card("mtc04a", "Nightjar", type_code="hero", faction_code="hero",
         set_code="nightjar2", is_unique=True, back_link="mtc04b",
         deck_limit=None, quantity=1),
    card("mtc04b", "Jo Reyes", type_code="alter_ego", faction_code="hero",
         set_code="nightjar2", is_unique=True, deck_limit=None, quantity=1),
]

# The Archangel shape: a third face with back_link None.
EXTRA_FORMS = [
    card("frm01a", "Skyward", type_code="hero", faction_code="hero",
         set_code="skyward", back_link="frm01b", deck_limit=None,
         quantity=1, hand_size=5),
    card("frm01b", "Nell Cross", type_code="alter_ego", faction_code="hero",
         set_code="skyward", deck_limit=None, quantity=1, hand_size=6),
    card("frm01c", "Skyward Ascendant", type_code="hero",
         faction_code="hero", set_code="skyward", back_link=None,
         deck_limit=None, quantity=1, hand_size=4),
]

# The Ironheart shape: three complete identity cards, six faces.
MULTI_IDENTITY = [
    c for i in (1, 2, 3) for c in (
        card(f"mid0{i}a", f"Cascade Mk{i}", type_code="hero",
             faction_code="hero", set_code="cascade", back_link=f"mid0{i}b",
             deck_limit=None, quantity=1, hand_size=3 + i),
        card(f"mid0{i}b", "Wren Bell", type_code="alter_ego",
             faction_code="hero", set_code="cascade", deck_limit=None,
             quantity=1, hand_size=6),
    )
]

# Three out-of-deck mechanisms, one of which is no marking at all.
OUT_OF_DECK = [
    card("ood01", "Bonded Blade", type_code="upgrade", faction_code="hero",
         set_code="edge", permanent=True, deck_limit=1, quantity=1),
    card("ood02", "Channelled Spark", type_code="event", faction_code="hero",
         set_code="edge_special", deck_limit=1, quantity=1),
    card("ood03", "Kindling", type_code="upgrade", faction_code="hero",
         set_code="edge", deck_limit=1, quantity=1),
    card("ood00a", "Emberline", type_code="hero", faction_code="hero",
         set_code="edge", back_link="ood00b", deck_limit=None, quantity=1,
         text="Setup: Set the Kindling upgrade aside, out of play."),
    card("ood00b", "Sasha Vane", type_code="alter_ego", faction_code="hero",
         set_code="edge", deck_limit=None, quantity=1),
    card("ood04", "Ordinary Signature", type_code="event",
         faction_code="hero", set_code="edge", deck_limit=3, quantity=3),
]

# Sp//dr: a hero face and a permanent support sharing a title, so
# out-of-deck classification must run before unique-match.
SPDR = [
    card("spd01a", "Loomcore Rig", type_code="hero", faction_code="hero",
         set_code="loom", back_link="spd01b", is_unique=True,
         deck_limit=None, quantity=1),
    card("spd01b", "Pilot Wren", type_code="alter_ego", faction_code="hero",
         set_code="loom", is_unique=True, deck_limit=None, quantity=1),
    card("spd02", "Loomcore Rig", type_code="support", faction_code="hero",
         set_code="loom", permanent=True, is_unique=True,
         deck_limit=1, quantity=1),
]

SETS = [
    {"code": "edge", "name": "Edge", "card_set_type_code": "hero"},
    {"code": "edge_special", "name": "Edge Special",
     "card_set_type_code": "hero_special"},
    {"code": "loom", "name": "Loom", "card_set_type_code": "hero"},
]

CONFIG_COVERING_EMBERLINE = {
    "version": 1,
    "out_of_deck": {
        "by_keyword": "permanent",
        "by_set_type": "hero_special",
        "exceptions": [{"identity": "edge", "cards": ["ood03"],
                        "note": "test"}],
    },
}

ARROW_CARDS = [
    card("arw01", "Simple Trade", type_code="event",
         text="<b>Action:</b> Discard a card → draw a card."),
    card("arw02", "Timed Guard", type_code="upgrade",
         text="<b>Interrupt:</b> When a character would take damage, "
              "exhaust an [[Aerial]] character you control → prevent 2 "
              "of that damage."),
    card("arw03", "Conditional Swing", type_code="upgrade",
         text="<b>Action:</b> If you are in [[Tiny]] hero form, exhaust "
              "Conditional Swing → deal 1 damage."),
    card("arw04", "Double Deal", type_code="event",
         text="<b>Action:</b> Spend 1 resource → draw a card. "
              "<b>Response:</b> After you draw, discard a card → heal 1."),
    card("arw05", "Sturdy Wall", type_code="ally", traits="Tech.",
         text="Toughness. Retaliate 1. Protects [[S.H.I.E.L.D.]] allies."),
]

# A reprint stub: code, pack, quantity, and duplicate_of - nothing else.
# 351 rows in the real corpus look like this, and 341 resolve to player
# cards, contrary to spec §8.
REPRINTS = [
    card("rp001", "Field Medic", type_code="event", faction_code="basic",
         pack_code="core", quantity=3, deck_limit=3, cost=1,
         text="Heal 2 damage.", traits="Aid."),
    {"code": "rp002", "pack_code": "hero_pack", "position": 19,
     "quantity": 2, "duplicate_of": "rp001"},
]
