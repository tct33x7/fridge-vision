CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    barcode TEXT,
    category TEXT NOT NULL DEFAULT '其他',
    brand TEXT,
    default_unit TEXT NOT NULL DEFAULT '份',
    estimated_weight_g REAL NOT NULL DEFAULT 100,
    calories_kcal REAL NOT NULL DEFAULT 0,
    protein_g REAL NOT NULL DEFAULT 0,
    carbs_g REAL NOT NULL DEFAULT 0,
    fat_g REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_barcode
ON products(barcode) WHERE barcode IS NOT NULL AND barcode <> '';
CREATE INDEX IF NOT EXISTS idx_products_normalized_name ON products(normalized_name);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL UNIQUE,
    scan_type TEXT NOT NULL,
    original_name TEXT NOT NULL,
    saved_name TEXT NOT NULL,
    processed_name TEXT,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    engine TEXT NOT NULL,
    batch_id INTEGER,
    result_json TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    confirmed_at TEXT,
    FOREIGN KEY(batch_id) REFERENCES inventory_batches(id)
);

CREATE TABLE IF NOT EXISTS inventory_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    original_quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    purchase_date TEXT,
    production_date TEXT,
    expiry_date TEXT,
    best_before_date TEXT,
    shelf_life_days INTEGER,
    storage_location TEXT NOT NULL DEFAULT '冷藏室',
    unit_price REAL,
    source_scan_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id),
    FOREIGN KEY(source_scan_id) REFERENCES scans(id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory_batches(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_expiry ON inventory_batches(expiry_date);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    transaction_type TEXT NOT NULL,
    quantity_delta REAL NOT NULL,
    quantity_after REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES inventory_batches(id),
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_batch ON inventory_transactions(batch_id);

