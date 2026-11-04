# 拍摄与识别数据契约

当前数据契约版本为 `schema_version = 1`。后续新增字段时应保持现有字段含义不变；破坏性调整必须提高版本号。

## 一条完整记录

```json
{
  "schema_version": 1,
  "id": "9676909d-e46f-43dc-ab49-a8973e7c1e67",
  "captured_at": "2026-08-06T15:40:21.251+08:00",
  "updated_at": "2026-08-06T15:40:23.018+08:00",
  "trigger": "实体按钮",
  "filename": "capture_20260806_154021_251_9676909d.jpg",
  "image_path": "/home/orangepi/pythontest/captures/2026/08/06/capture_....jpg",
  "image_relpath": "2026/08/06/capture_....jpg",
  "sidecar_path": "/home/orangepi/pythontest/captures/2026/08/06/capture_....json",
  "image_url": "/captures/9676909d-e46f-43dc-ab49-a8973e7c1e67.jpg",
  "record_url": "/api/v1/captures/9676909d-e46f-43dc-ab49-a8973e7c1e67",
  "image_sha256": "...",
  "mime_type": "image/jpeg",
  "width": 1920,
  "height": 1080,
  "bytes": 162812,
  "camera_device": "/dev/video0",
  "recognition": {
    "status": "completed",
    "recognizer": "tesseract-local-v1",
    "name": "示例商店",
    "type": "receipt",
    "language": "chi_sim+eng",
    "confidence": 0.91,
    "recognized_at": "2026-08-06T15:40:23.018+08:00",
    "error": null,
    "raw_text": "示例商店\n合计 ￥28.50",
    "fields": {
      "total": {
        "value": "合计 ￥28.50",
        "normalized_value": "28.50",
        "confidence": 0.91,
        "source": "ocr_rule"
      }
    },
    "structured": {
      "schema_version": 1,
      "document": {},
      "fields": {},
      "items": [],
      "text": {"lines": []}
    }
  }
}
```

## 状态定义

| 状态 | 含义 |
|---|---|
| `pending` | 原图已保存，等待识别 |
| `processing` | OCR 正在执行 |
| `completed` | 识别和结构化提取完成 |
| `failed` | 原图安全，但识别失败；查看 `error` |
| `skipped` | 使用 `--no-ocr` 拍摄，未安排识别 |

后续程序只能在 `completed` 时把结构化值视为识别结果；即使完成，也应结合字段置信度决定是否需要人工复核。

## SQLite 表

- `captures`：一张照片一行，包含生命周期、主要分类、OCR 原文及 JSON；
- `capture_fields`：将名称、日期、金额等字段单独索引，方便查询和统计；
- `capture_events`：记录拍摄、开始识别、完成、失败、重试等审计事件；
- `system_metadata`：数据库 schema 版本。

数据库根据运行时 SQLite 版本选择日志模式：SQLite 3.51.3+，或官方已回补
修复的 3.50.7+ / 3.44.6+ 系列使用 WAL；其他版本使用 rollback journal，
规避 2026 年披露的 WAL-reset 并发风险。应用每次操作使用短连接，并保持
写事务简短。

常用查询示例：

```sql
SELECT id, captured_at, document_name, document_type, confidence
FROM captures
WHERE recognition_status = 'completed'
ORDER BY captured_at DESC;
```

```sql
SELECT c.id, c.document_name, f.normalized_value AS total
FROM captures AS c
JOIN capture_fields AS f ON f.capture_id = c.id
WHERE f.field_name = 'total'
ORDER BY c.captured_at DESC;
```

## 扩展原则

- 原始 JPEG 永远保留，识别结果可以重建；
- JPEG 已落盘但 SQLite 登记失败时移入 `captures/quarantine/`，等待对账，不静默删除；
- JSON sidecar 是可重建的便携副本；SQLite 已提交但 sidecar 写入失败不撤销拍摄记录；
- UUID 是跨数据库和文件系统的稳定主键；
- 数据库存相对图片路径，API 同时返回当前机器的绝对路径；
- `structured.items` 已预留商品明细数组，目前为空，不伪造低可信度行项目；
- 替换识别器时更新 `recognizer` 名称，保持外层记录结构不变；
- 需要人工校正时，应新增“修订值”和审计事件，不直接覆盖 OCR 原文。
