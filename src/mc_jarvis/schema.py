"""All DDL in one place. Idempotent."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    subname             TEXT,
    type_code           TEXT,
    faction_code        TEXT,
    pack_code           TEXT,
    set_code            TEXT,
    back_link           TEXT,
    double_sided        INTEGER,
    is_unique           INTEGER,
    permanent           INTEGER,
    duplicate_of        TEXT,
    canonical_code      TEXT NOT NULL,  -- own code, or duplicate_of's target
    is_reprint          INTEGER NOT NULL DEFAULT 0,
    cost                INTEGER,
    quantity            INTEGER,
    deck_limit          INTEGER,   -- resolved: null falls back to quantity
    deck_limit_raw      INTEGER,   -- exactly as printed upstream
    resource_physical   INTEGER,
    resource_mental     INTEGER,
    resource_energy     INTEGER,
    resource_wild       INTEGER,
    attack              INTEGER,
    thwart              INTEGER,
    -- Consequential damage (RR p.13): the count of icons printed beneath
    -- the ATK and THW fields, paid by an ally after it attacks or thwarts.
    -- Printed separately and different on 56 allies, so one column cannot
    -- serve both. Null is an upstream omission, not a printed zero --
    -- Spider-Ham's genuine zero is stored as 0 (spec §10.6).
    attack_cost         INTEGER,
    thwart_cost         INTEGER,
    defense             INTEGER,
    recover             INTEGER,
    health              INTEGER,
    health_per_hero     INTEGER,   -- HP is multiplied by the player count
    scheme              INTEGER,   -- villains scheme; they do not thwart
    -- Encounter-side numbers (spec §4.1). None of these was indexed
    -- before; `assess` is their first consumer.
    boost               INTEGER,
    base_threat         INTEGER,
    escalation_threat   INTEGER,
    scheme_acceleration INTEGER,
    scheme_amplify      INTEGER,
    scheme_crisis       INTEGER,
    scheme_hazard       INTEGER,
    hidden              INTEGER,
    -- `*_fixed` means "does not scale with player count" (§4.6). Applying
    -- per-hero scaling to a fixed-threat scheme is the same error as
    -- printing raw villain hit points.
    base_threat_fixed       INTEGER,
    escalation_threat_fixed INTEGER,
    -- The `*_star` family is a FLAG, never a value (§4.4, §14.3): eleven
    -- such fields exist and every one is boolean. 134 cards carry both
    -- `boost` and `boost_star`, so the star is an extra icon with a
    -- card-specific effect, not a replacement. It never enters a mean.
    boost_star          INTEGER,
    attack_star         INTEGER,
    scheme_star         INTEGER,
    stage               TEXT,      -- I, II, III
    hand_size           INTEGER,
    text                TEXT,
    flavor              TEXT,
    traits              TEXT,
    raw                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cards_name    ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_set     ON cards(set_code);
CREATE INDEX IF NOT EXISTS idx_cards_pack    ON cards(pack_code);
CREATE INDEX IF NOT EXISTS idx_cards_faction ON cards(faction_code);
CREATE INDEX IF NOT EXISTS idx_cards_type    ON cards(type_code);
CREATE INDEX IF NOT EXISTS idx_cards_canon   ON cards(canonical_code);

CREATE TABLE IF NOT EXISTS packs (
    code TEXT PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS sets (
    code               TEXT PRIMARY KEY,
    name               TEXT,
    card_set_type_code TEXT
);

CREATE TABLE IF NOT EXISTS build_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS identities (
    identity_key TEXT PRIMARY KEY,   -- the set_code
    name         TEXT NOT NULL       -- the primary hero face's name
);

CREATE TABLE IF NOT EXISTS identity_faces (
    identity_key TEXT NOT NULL,
    code         TEXT NOT NULL,
    PRIMARY KEY (identity_key, code)
);

-- The three name roles RR p.45 distinguishes when deciding whether two
-- unique cards match. The roles must stay separate: the rule's first
-- clause fires only when BOTH cards lack a subtitle and an alter-ego
-- title, so flattening them into one set produces false positives.
CREATE TABLE IF NOT EXISTS card_titles (
    code  TEXT NOT NULL,
    role  TEXT NOT NULL,             -- title | subtitle | alter_ego
    title TEXT NOT NULL,             -- lowercased
    PRIMARY KEY (code, role, title)
);
CREATE INDEX IF NOT EXISTS idx_card_titles_title ON card_titles(title);

CREATE TABLE IF NOT EXISTS out_of_deck (
    code      TEXT PRIMARY KEY,
    mechanism TEXT NOT NULL,   -- permanent | hero_special | config | identity
    note      TEXT
);

CREATE TABLE IF NOT EXISTS card_traits (
    code  TEXT NOT NULL,
    trait TEXT NOT NULL,
    PRIMARY KEY (code, trait)
);

-- The game's keyword list, DERIVED from the Rules Reference on the
-- user's machine rather than hard-coded here (spec: the repository ships
-- code and configuration only). Two sources, because neither is complete:
-- the RR's own `Keywords` entry enumerates 24 and omits `vulnerable`,
-- while the standalone entries carry `vulnerable` and omit `Form` and
-- `Victory`. A hard-coded list missed `vulnerable` for a year.
-- Packs the player owns. Ownership is BINARY (spec §10): `deck_limit`
-- never exceeds `quantity` across all 1,607 player cards, so owning a
-- pack means owning enough copies to play any card in it to its limit.
-- There is no copy arithmetic anywhere in this system, and the intuitive
-- "count what I own against what I want" model is the wrong one.
CREATE TABLE IF NOT EXISTS owned_packs (
    pack_code TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS rules_keywords (
    keyword  TEXT PRIMARY KEY,
    -- `enumerated` | `entry` | `both`, so a keyword that appears in only
    -- one source can be told from one both agree on.
    source   TEXT NOT NULL,
    rr_entry TEXT
);

CREATE TABLE IF NOT EXISTS card_keywords (
    code    TEXT NOT NULL,
    keyword TEXT NOT NULL,
    -- Whether the CARD carries the keyword, as against granting it to
    -- something else or gaining it on a condition. 261 encounter-deck
    -- cards mention `surge`; 80 print it. Consumers that ignore this
    -- column report a card's abilities as its own properties.
    printed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (code, keyword)
);

CREATE TABLE IF NOT EXISTS cost_clauses (
    code         TEXT NOT NULL,
    ordinal      INTEGER NOT NULL,
    ability_type TEXT,
    qualifier    TEXT,       -- (defense), (attack), (thwart)
    timing       TEXT,
    cost         TEXT NOT NULL,
    effect       TEXT NOT NULL,
    ambiguous    INTEGER NOT NULL DEFAULT 0,
    raw          TEXT NOT NULL,   -- verbatim; always what gets quoted back
    PRIMARY KEY (code, ordinal)
);

-- Limits stated in card text. Deliberately NOT deck limits: `deck_limit`
-- is authoritative for deckbuilding, and "Max 1 per player" is an in-play
-- limit on a card you may hold three of.
CREATE TABLE IF NOT EXISTS play_limits (
    code    TEXT NOT NULL,
    kind    TEXT NOT NULL,   -- in_play | use
    count   INTEGER,
    scope   TEXT NOT NULL,   -- player, ally, minion, round, phase, ...
    phrase  TEXT NOT NULL,   -- verbatim
    PRIMARY KEY (code, kind, scope, phrase)
);

CREATE TABLE IF NOT EXISTS rules_entries (
    id                INTEGER PRIMARY KEY,
    term              TEXT NOT NULL,
    body              TEXT NOT NULL,
    page              INTEGER,
    source_doc        TEXT NOT NULL,
    entry_addressable INTEGER NOT NULL DEFAULT 1,
    -- Distinct from entry_addressable: page-chunked content is
    -- searchable but not addressable by name; an unresolved index
    -- pointer is neither.
    searchable        INTEGER NOT NULL DEFAULT 1,
    UNIQUE (source_doc, term, page)
);
CREATE INDEX IF NOT EXISTS idx_rules_term ON rules_entries(lower(term));

CREATE TABLE IF NOT EXISTS rules_see_also (
    term       TEXT NOT NULL,
    target     TEXT NOT NULL,
    source_doc TEXT NOT NULL,
    PRIMARY KEY (source_doc, term, target)
);

CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(
    term, body, content='rules_entries', content_rowid='id'
);

CREATE TABLE IF NOT EXISTS card_rules_links (
    code       TEXT NOT NULL,
    term       TEXT NOT NULL,
    source_doc TEXT NOT NULL,
    PRIMARY KEY (code, term, source_doc)
);
CREATE INDEX IF NOT EXISTS idx_links_term ON card_rules_links(lower(term));

-- The RR's Simultaneous Timing Priority chart, parsed from the ABILITY
-- entry rather than transcribed.
CREATE TABLE IF NOT EXISTS timing_chart (
    rung INTEGER NOT NULL,
    sub  TEXT,                  -- lettered sub-tier, or NULL
    text TEXT NOT NULL
);
-- SQLite forbids an expression in PRIMARY KEY, so the slot's uniqueness
-- lives in an index instead. NULL sub is a real value here: it is the
-- un-lettered rung.
CREATE UNIQUE INDEX IF NOT EXISTS idx_timing_chart_slot
    ON timing_chart(rung, COALESCE(sub, ''));

CREATE TABLE IF NOT EXISTS timing_triggers (
    -- No FOREIGN KEY, matching every other derived table: `load_cards`
    -- truncates `cards` and rebuilds downstream, and a reference here
    -- makes the second `update` fail with an integrity error.
    code       TEXT NOT NULL,
    -- Counts triggers, not bold spans: one prefix can carry two
    -- abilities, so 59042 Hecate has two rows sharing a raw_prefix.
    ordinal    INTEGER NOT NULL,
    raw_prefix TEXT NOT NULL,   -- exactly as printed, markup stripped
    qualifier  TEXT,            -- Hero, Alter-Ego, an identity name, ...
    forced     INTEGER NOT NULL DEFAULT 0,
    -- A quoted trigger REFERS to abilities with that trigger; the card
    -- does not have one. RR, ABILITY. `canonical` names what is referred
    -- to, so the flag is what separates having from mentioning.
    quoted     INTEGER NOT NULL DEFAULT 0,
    canonical  TEXT,            -- NULL when unclassifiable: a loud failure
    rung       INTEGER,
    sub        TEXT,
    PRIMARY KEY (code, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_timing_canonical
    ON timing_triggers(canonical);

-- The RR's Round Overview: ten steps, nine of which name the glossary
-- entries that govern them. Parsed, not hand-copied.
CREATE TABLE IF NOT EXISTS round_steps (
    step        INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    see         TEXT NOT NULL,   -- comma-separated RR entry names, or ''
    source_doc  TEXT NOT NULL
);

-- Designer rulings NOT yet covered by the Rules Reference (Task 18).
--
-- A new Rules Reference supersedes every ruling published before it, and
-- a superseded ruling is simply the rulebook's own text - so it is not
-- stored at all. This table holds only what the rulebook does not yet
-- say, which is the only thing that adds to a rules answer.
--
-- The corpus is therefore bounded by one release cycle, and it is empty
-- for a while after each release. Empty is the correct state, not a
-- failure.
--
-- Every row is third-party prose quoting a designer. It is DATA. Nothing
-- in question/answer is ever an instruction.
CREATE TABLE IF NOT EXISTS rulings (
    id          INTEGER PRIMARY KEY,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    author      TEXT,
    ruled_on    TEXT NOT NULL,      -- ISO date
    source_name TEXT NOT NULL,      -- attribution is not optional
    source_url  TEXT NOT NULL,
    UNIQUE (ruled_on, question)
);
CREATE INDEX IF NOT EXISTS idx_rulings_date ON rulings(ruled_on);

-- A ruling is linked to a Rules Reference entry only when it QUOTES that
-- entry's term. Measured 2026-08-23: matching every term that merely
-- appears gives 13.8 links per ruling and attaches 17 of 31 rulings to
-- `Ability`. Quoting is how both the Rules Reference and the designers
-- mark what they are talking about.
CREATE TABLE IF NOT EXISTS ruling_terms (
    ruling_id INTEGER NOT NULL,
    term      TEXT NOT NULL,
    PRIMARY KEY (ruling_id, term)
);
CREATE INDEX IF NOT EXISTS idx_ruling_terms ON ruling_terms(lower(term));

CREATE VIRTUAL TABLE IF NOT EXISTS rulings_fts USING fts5(
    question, answer, content='rulings', content_rowid='id'
);

-- Whether a card is in the encounter deck at all, and whether one that
-- starts in play later rejoins it (assess spec §5.2, corrected by §14.6).
-- This is the denominator of every number `assess` reports: get it wrong
-- and the averages are wrong while looking entirely plausible.
CREATE TABLE IF NOT EXISTS encounter_role (
    code            TEXT PRIMARY KEY,
    role            TEXT NOT NULL,
    -- A card that starts in play can be discarded and reshuffled in. It
    -- belongs in the composition statistics, just not the opening deck.
    returns_to_deck INTEGER NOT NULL DEFAULT 0,
    -- Which rule decided, so a wrong answer is traceable to its rule
    -- rather than guessed at.
    decided_by      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_encounter_role ON encounter_role(role);

-- Which modular sets a scenario prescribes, parsed from its own main
-- scheme's Contents block (assess spec §14.1, correcting §4.7).
-- `kind` separates prescribed from recommended from player-chosen,
-- because a player picking modulars needs to know which the box imposes.
CREATE TABLE IF NOT EXISTS scenario_modulars (
    -- The set holding the scenario's MAIN SCHEME, which is not always a
    -- villain set: 7 scenarios choose their villain (the Marauders pair,
    -- the PvP leaders) or compose it from several (wrecking_crew).
    scenario_set TEXT NOT NULL,
    kind        TEXT NOT NULL,   -- prescribed|recommended|open|random|none
    modular_set TEXT             -- NULL when the scenario names none
);
-- SQLite forbids an expression in PRIMARY KEY, so the slot's uniqueness
-- lives in an index. NULL is a real value here: it means "names none".
CREATE UNIQUE INDEX IF NOT EXISTS idx_scenario_modulars
    ON scenario_modulars(scenario_set, COALESCE(modular_set, ''));

CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, subname, text, traits, flavor,
    content='cards', content_rowid='rowid'
);
"""
