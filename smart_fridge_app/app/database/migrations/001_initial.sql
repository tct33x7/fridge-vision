CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_metadata (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
    id                       INTEGER PRIMARY KEY CHECK (id = 1),
    display_name             TEXT NOT NULL DEFAULT '',
    diet_goal                TEXT NOT NULL DEFAULT 'balanced',
    preferences_json         TEXT NOT NULL DEFAULT '[]',
    allergies_json           TEXT NOT NULL DEFAULT '[]',
    medications_json         TEXT NOT NULL DEFAULT '[]',
    onboarding_completed     INTEGER NOT NULL DEFAULT 0 CHECK (onboarding_completed IN (0, 1)),
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL CHECK (kind IN ('fridge', 'freezer', 'pantry', 'counter')),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    normalized_name  TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT 'other',
    default_unit     TEXT NOT NULL DEFAULT 'piece',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_normalized_name
    ON products(normalized_name);

CREATE TABLE IF NOT EXISTS product_barcodes (
    barcode      TEXT PRIMARY KEY,
    product_id   TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_product_barcodes_product
    ON product_barcodes(product_id);

CREATE TABLE IF NOT EXISTS media_assets (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL CHECK (source IN ('camera', 'upload')),
    captured_at         TEXT,
    trigger             TEXT,
    sha256              TEXT,
    mime_type           TEXT,
    width               INTEGER,
    height              INTEGER,
    byte_size           INTEGER,
    camera_device       TEXT,
    recognition_status  TEXT,
    record_json         TEXT NOT NULL DEFAULT '{}',
    state               TEXT NOT NULL DEFAULT 'ready' CHECK (state IN ('ready', 'missing', 'deleted')),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_media_assets_captured_at
    ON media_assets(captured_at DESC);

CREATE TABLE IF NOT EXISTS inventory_lots (
    id                  TEXT PRIMARY KEY,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    location_id         TEXT NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    quantity            REAL NOT NULL CHECK (quantity >= 0),
    unit                TEXT NOT NULL,
    purchased_on        TEXT,
    expires_on          TEXT,
    opened_on           TEXT,
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'used', 'discarded')),
    source              TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'camera', 'barcode', 'receipt')),
    source_capture_id   TEXT REFERENCES media_assets(id) ON DELETE RESTRICT,
    note                TEXT NOT NULL DEFAULT '',
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inventory_lots_active_expiry
    ON inventory_lots(status, expires_on);
CREATE INDEX IF NOT EXISTS idx_inventory_lots_product
    ON inventory_lots(product_id, status);
CREATE INDEX IF NOT EXISTS idx_inventory_lots_location
    ON inventory_lots(location_id, status);

CREATE TABLE IF NOT EXISTS inventory_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id              TEXT NOT NULL REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    event_type          TEXT NOT NULL CHECK (event_type IN ('receive', 'consume', 'discard', 'adjust', 'open', 'transfer')),
    delta_quantity      REAL NOT NULL,
    quantity_after      REAL NOT NULL CHECK (quantity_after >= 0),
    reason              TEXT NOT NULL DEFAULT '',
    source_capture_id   TEXT REFERENCES media_assets(id) ON DELETE RESTRICT,
    details_json        TEXT NOT NULL DEFAULT '{}',
    occurred_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inventory_events_lot
    ON inventory_events(lot_id, id);

