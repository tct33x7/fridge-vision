ALTER TABLE media_assets ADD COLUMN local_relpath TEXT;
ALTER TABLE media_assets ADD COLUMN imported_at TEXT;
ALTER TABLE media_assets ADD COLUMN verified_at TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_media_assets_local_relpath
    ON media_assets(local_relpath)
    WHERE local_relpath IS NOT NULL;

ALTER TABLE products ADD COLUMN primary_flavor TEXT;

CREATE TABLE IF NOT EXISTS product_nutrition (
    product_id          TEXT PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    basis_amount        REAL NOT NULL CHECK (basis_amount > 0),
    basis_unit          TEXT NOT NULL,
    calories_kcal       REAL CHECK (calories_kcal IS NULL OR calories_kcal >= 0),
    protein_g           REAL CHECK (protein_g IS NULL OR protein_g >= 0),
    carbs_g             REAL CHECK (carbs_g IS NULL OR carbs_g >= 0),
    fat_g               REAL CHECK (fat_g IS NULL OR fat_g >= 0),
    fiber_g             REAL CHECK (fiber_g IS NULL OR fiber_g >= 0),
    sodium_mg           REAL CHECK (sodium_mg IS NULL OR sodium_mg >= 0),
    source              TEXT NOT NULL DEFAULT 'manual',
    verified_by_user    INTEGER NOT NULL DEFAULT 1 CHECK (verified_by_user IN (0, 1)),
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intake_sessions (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'review', 'confirmed', 'failed', 'cancelled')),
    selected_media_id   TEXT REFERENCES media_assets(id) ON DELETE RESTRICT,
    draft_json          TEXT NOT NULL DEFAULT '{}',
    result_json         TEXT NOT NULL DEFAULT '{}',
    error               TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    confirmed_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_intake_sessions_status_updated
    ON intake_sessions(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS intake_session_captures (
    session_id          TEXT NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    media_id            TEXT NOT NULL REFERENCES media_assets(id) ON DELETE RESTRICT,
    position            INTEGER NOT NULL,
    added_at            TEXT NOT NULL,
    PRIMARY KEY (session_id, media_id),
    UNIQUE (session_id, position)
);

CREATE TABLE IF NOT EXISTS intake_session_lots (
    session_id          TEXT NOT NULL REFERENCES intake_sessions(id) ON DELETE RESTRICT,
    lot_id              TEXT NOT NULL REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    line_index          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, lot_id),
    UNIQUE (session_id, line_index)
);

CREATE TABLE IF NOT EXISTS meal_logs (
    id                  TEXT PRIMARY KEY,
    eaten_at            TEXT NOT NULL,
    meal_type           TEXT CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'other')),
    source              TEXT NOT NULL DEFAULT 'inventory',
    note                TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meal_logs_eaten_at
    ON meal_logs(eaten_at DESC);

CREATE TABLE IF NOT EXISTS meal_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id             TEXT NOT NULL REFERENCES meal_logs(id) ON DELETE CASCADE,
    lot_id              TEXT REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    product_id          TEXT REFERENCES products(id) ON DELETE RESTRICT,
    name_snapshot       TEXT NOT NULL,
    category_snapshot   TEXT NOT NULL,
    amount              REAL NOT NULL CHECK (amount > 0),
    unit                TEXT NOT NULL,
    taste_tags_json     TEXT NOT NULL DEFAULT '[]',
    calories_kcal       REAL,
    protein_g           REAL,
    carbs_g             REAL,
    fat_g               REAL,
    fiber_g             REAL,
    sodium_mg           REAL,
    nutrition_source    TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meal_items_meal
    ON meal_items(meal_id, id);
