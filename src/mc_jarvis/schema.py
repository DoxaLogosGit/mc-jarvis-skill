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
    defense             INTEGER,
    recover             INTEGER,
    health              INTEGER,
    health_per_hero     INTEGER,   -- HP is multiplied by the player count
    scheme              INTEGER,   -- villains scheme; they do not thwart
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

CREATE TABLE IF NOT EXISTS card_keywords (
    code    TEXT NOT NULL,
    keyword TEXT NOT NULL,
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

CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, subname, text, traits, flavor,
    content='cards', content_rowid='rowid'
);
"""
