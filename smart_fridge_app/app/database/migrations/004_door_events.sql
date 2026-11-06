-- 门口纯视觉记账：一次过线 = 一条 door_events；按类别估算到期日。

CREATE TABLE IF NOT EXISTS category_shelf_life (
    category        TEXT PRIMARY KEY,
    label_zh        TEXT NOT NULL DEFAULT '',
    default_days    INTEGER NOT NULL CHECK (default_days > 0),
    location_id     TEXT NOT NULL DEFAULT 'fridge',  -- 位置在代码中校验；迁移早于默认位置写入，不能加外键
    updated_at      TEXT NOT NULL
);

INSERT OR IGNORE INTO category_shelf_life(category, label_zh, default_days, location_id, updated_at) VALUES
    ('fruit',     '水果',   7,  'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('vegetable', '蔬菜',   5,  'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('meat',      '肉类',   3,  'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('seafood',   '海鲜',   2,  'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('dairy',     '乳制品', 7,  'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('egg',       '蛋',     21, 'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('staple',    '主食',   4,  'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('beverage',  '饮品',   14, 'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('condiment', '调味品', 90, 'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('snack',     '零食',   30, 'pantry',  '2026-11-06T00:00:00.000+00:00'),
    ('cooked',    '熟食',   3,  'fridge',  '2026-11-06T00:00:00.000+00:00'),
    ('other',     '其他',   7,  'fridge',  '2026-11-06T00:00:00.000+00:00');

CREATE TABLE IF NOT EXISTS door_events (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    occurred_at         TEXT NOT NULL,
    action              TEXT NOT NULL CHECK (action IN ('in', 'out')),
    label               TEXT NOT NULL,
    label_zh            TEXT NOT NULL,
    category            TEXT NOT NULL DEFAULT 'other',
    confidence          REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    count               REAL NOT NULL DEFAULT 1 CHECK (count > 0),
    vlm_json            TEXT NOT NULL DEFAULT '{}',
    media_id            TEXT REFERENCES media_assets(id) ON DELETE RESTRICT,
    lot_id              TEXT REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    inventory_event_id  INTEGER REFERENCES inventory_events(id) ON DELETE RESTRICT,
    applied_quantity    REAL NOT NULL DEFAULT 0,
    status              TEXT NOT NULL CHECK (status IN ('applied', 'unmatched', 'undone')),
    undone_at           TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_door_events_occurred
    ON door_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_door_events_session
    ON door_events(session_id, occurred_at);
