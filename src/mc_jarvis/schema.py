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

CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, subname, text, traits, flavor,
    content='cards', content_rowid='rowid'
);
"""
