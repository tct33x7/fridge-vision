CREATE TABLE IF NOT EXISTS inventory_lot_nutrition (
    lot_id              TEXT PRIMARY KEY REFERENCES inventory_lots(id) ON DELETE RESTRICT,
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
    captured_at         TEXT NOT NULL
);

-- Existing lots can only inherit the best product-level value available at
-- migration time. New lots receive an immutable snapshot when they are made.
INSERT OR IGNORE INTO inventory_lot_nutrition(
    lot_id, basis_amount, basis_unit, calories_kcal, protein_g, carbs_g,
    fat_g, fiber_g, sodium_mg, source, verified_by_user, captured_at
)
SELECT l.id, n.basis_amount, n.basis_unit, n.calories_kcal, n.protein_g,
       n.carbs_g, n.fat_g, n.fiber_g, n.sodium_mg, n.source,
       n.verified_by_user, n.updated_at
FROM inventory_lots l
JOIN product_nutrition n ON n.product_id=l.product_id;

-- Version-1 records referenced camera-owned files and do not yet have an
-- application-owned evidence copy. They become ready again after verified sync.
UPDATE media_assets
SET state='missing', updated_at=COALESCE(updated_at, created_at)
WHERE local_relpath IS NULL AND state='ready';
