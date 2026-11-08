from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.services.ocr_pipeline import get_pipeline


class ExpiryOCRService:
    """包装日期 OCR 识别服务，使用统一 OCR 管线。"""

    DATE_RE = re.compile(
        r"(?<!\d)(20\d{2}|\d{2})[年./\-](\d{1,2})[月./\-](\d{1,2})日?(?!\d)"
    )

    def recognize(
        self,
        image_path: Path,
        original_name: str,
        file_id: str,
        engine: str = "rapidocr",
    ) -> dict[str, Any]:
        """识别包装日期，使用 OCR 管线进行预处理 → 识别 → 后处理。"""
        pipeline = get_pipeline()
        result = pipeline.run(
            image_path, f"{file_id}_expiry",
            engine=engine,
            profile="expiry",
        )

        raw_text = result.get("raw_text", "")
        parsed = self.parse_text(raw_text)
        parsed.update(
            {
                "engine": engine,
                "processed_name": result.get("processed_name"),
                "raw_text": raw_text,
                "confidence": result.get("avg_confidence", 0),
            }
        )
        if not result.get("lines"):
            parsed["warnings"].append("未安装或未能运行 OCR 引擎，请在确认页手动填写日期。")
        elif not parsed["detected_dates"]:
            parsed["warnings"].append("识别到文字，但未找到可靠日期，请手动核对包装。")
        return parsed

    @classmethod
    def parse_text(cls, text: str) -> dict[str, Any]:
        normalized = text.upper().replace("：", ":")
        detected: list[dict[str, str]] = []
        production_date = None
        expiry_date = None
        best_before_date = None

        for match in cls.DATE_RE.finditer(normalized):
            year = int(match.group(1))
            year = 2000 + year if year < 100 else year
            try:
                value = date(year, int(match.group(2)), int(match.group(3))).isoformat()
            except ValueError:
                continue
            context = normalized[max(0, match.start() - 18): min(len(normalized), match.end() + 12)]
            kind = "unknown"
            if re.search(r"生产|制造|灌装|MFG|MFD", context):
                kind = "production"
                production_date = production_date or value
            elif re.search(r"最佳|BEST\s*BEFORE|赏味", context):
                kind = "best_before"
                best_before_date = best_before_date or value
            elif re.search(r"有效|到期|截止|EXP|USE\s*BY", context):
                kind = "expiry"
                expiry_date = expiry_date or value
            detected.append({"value": value, "kind": kind, "context": context.strip()})

        shelf_life_days = None
        months = None
        shelf_match = re.search(r"保质期\s*[:：]?\s*(\d{1,3})\s*(天|日|个月|月|年)", normalized)
        if shelf_match:
            amount, unit = int(shelf_match.group(1)), shelf_match.group(2)
            if unit in ("天", "日"):
                shelf_life_days = amount
            elif unit in ("个月", "月"):
                months = amount
            else:
                months = amount * 12

        if production_date and not expiry_date and (shelf_life_days is not None or months is not None):
            start = date.fromisoformat(production_date)
            if shelf_life_days is not None:
                expiry_date = (start + timedelta(days=shelf_life_days)).isoformat()
            else:
                expiry_date = cls._add_months(start, months or 0).isoformat()
                shelf_life_days = (date.fromisoformat(expiry_date) - start).days

        if not production_date and not expiry_date:
            unknown_values = [entry["value"] for entry in detected if entry["kind"] == "unknown"]
            if len(unknown_values) >= 2:
                production_date, expiry_date = min(unknown_values), max(unknown_values)
            elif len(unknown_values) == 1:
                expiry_date = unknown_values[0]

        return {
            "production_date": production_date,
            "expiry_date": expiry_date or best_before_date,
            "best_before_date": best_before_date,
            "shelf_life_days": shelf_life_days,
            "detected_dates": detected,
            "warnings": [],
        }

    @staticmethod
    def _add_months(value: date, months: int) -> date:
        month_index = value.month - 1 + months
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
