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
"""
