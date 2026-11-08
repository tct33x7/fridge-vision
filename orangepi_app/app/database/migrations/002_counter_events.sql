-- 物品进出自动计数事件流水（yolo_web_counter 集成）
-- cls 为 COCO 类别名；delta +1 = 放入（沿正方向穿过计数线），-1 = 取出
-- 计数清零写入一条 cls = '__reset__' 的标记行，汇总时只统计最后一个标记之后的行
CREATE TABLE IF NOT EXISTS counter_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cls TEXT NOT NULL,
    delta INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_counter_events_id ON counter_events(id);
