"""OCR 结果后处理模块
============================
对 OCR 引擎输出的原始文本进行清洗、排序、分组和结构化，
使结果更符合原始图片中的排版格式。

后处理流程：
    原始行列表 → 文本清洗 → 置信度过滤 → 位置排序
              → 行分组（段落/列） → 结构化输出

支持的结构化模式：
    receipt: 提取商品行、价格、日期、商户
    expiry:  提取生产/到期日期、保质期
    general: 保留排版格式的纯文本 + 行块结构
"""

from __future__ import annotations

import re
from typing import Any

from app.services.ocr_engine_manager import OCRLine, OCRResult


class OCRPostprocessor:
    """OCR 结果后处理器。"""

    # 常见 OCR 错误修正映射（中英文混排场景）
    CHAR_FIXES: dict[str, str] = {
        "O": "0",  # 字母 O → 数字 0（在纯数字上下文中）
        "l": "1",  # 小写 l → 数字 1
        "I": "1",  # 大写 I → 数字 1
        "S": "5",  # 字母 S → 数字 5（在价格上下文中）
        "。": ".",
        "，": ",",
        "：": ":",
        "；": ";",
    }

    # 无效行过滤模式（纯噪声/空白）
    NOISE_PATTERNS = [
        re.compile(r"^[\s\W_]+$"),           # 纯符号/空白
        re.compile(r"^[.\-_=*~]{2,}$"),       # 分隔线
        re.compile(r"^\d{1,2}$"),             # 单独 1-2 位数字（可能是噪声）
    ]

    def process(
        self,
        result: OCRResult,
        profile: str = "general",
        confidence_threshold: float = 0.3,
    ) -> dict[str, Any]:
        """后处理 OCR 结果。

        Args:
            result: OCR 引擎返回的原始结果
            profile: 后处理策略 (receipt / expiry / general)
            confidence_threshold: 过滤低于此置信度的行

        Returns:
            结构化结果字典
        """
        # Step 1: 过滤低置信度行
        lines = [ln for ln in result.lines if ln.confidence >= confidence_threshold or ln.confidence == 0.0]

        # Step 2: 文本清洗
        lines = [self._clean_line(ln) for ln in lines]
        lines = [ln for ln in lines if ln.text]  # 去除空行

        # Step 3: 过滤噪声行
        lines = [ln for ln in lines if not self._is_noise(ln.text)]

        # Step 4: 按位置排序（恢复阅读顺序）
        lines = self._sort_by_position(lines)

        # Step 5: 根据策略进行结构化
        if profile == "receipt":
            structured = self._parse_receipt(lines)
        elif profile == "expiry":
            structured = self._parse_expiry(lines)
        else:
            structured = self._parse_general(lines)

        # 通用输出字段
        structured.update({
            "raw_text": "\n".join(ln.text for ln in lines),
            "line_count": len(lines),
            "lines": [{"text": ln.text, "confidence": round(ln.confidence, 3)} for ln in lines],
            "avg_confidence": round(
                sum(ln.confidence for ln in lines) / len(lines), 3
            ) if lines else 0.0,
            "engine": result.engine,
            "elapsed": result.elapsed,
            "error": result.error,
        })
        return structured

    # ──────────── 文本清洗 ────────────

    def _clean_line(self, line: OCRLine) -> OCRLine:
        """清洗单行文本：去首尾空白、修复常见 OCR 错误。"""
        text = line.text.strip()
        # 去除多余空格（中文之间不应有空格）
        text = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", text)
        # 合并多个连续空格
        text = re.sub(r" {2,}", " ", text)
        # 去除首尾特殊符号
        text = text.strip(" |·•▪◇◆")
        return OCRLine(text=text, confidence=line.confidence, bbox=line.bbox)

    def _is_noise(self, text: str) -> bool:
        """判断是否为噪声行。"""
        for pattern in self.NOISE_PATTERNS:
            if pattern.match(text):
                return True
        return False

    # ──────────── 位置排序 ────────────

    @staticmethod
    def _sort_by_position(lines: list[OCRLine]) -> list[OCRLine]:
        """按 y 坐标排序（从上到下），同 y 范围内按 x 排序（从左到右）。"""
        def get_y(line: OCRLine) -> float:
            if line.bbox and len(line.bbox) >= 2:
                return line.bbox[0][1]
            return 0.0

        def get_x(line: OCRLine) -> float:
            if line.bbox and len(line.bbox) >= 1:
                return line.bbox[0][0]
            return 0.0

        # 按 y 分组（容差 15px 视为同一行），组内按 x 排序
        sorted_lines = sorted(lines, key=get_y)
        grouped: list[list[OCRLine]] = []
        for line in sorted_lines:
            if grouped and abs(get_y(line) - get_y(grouped[-1][0])) < 15:
                grouped[-1].append(line)
            else:
                grouped.append([line])
        # 每组内按 x 排序
        result: list[OCRLine] = []
        for group in grouped:
            result.extend(sorted(group, key=get_x))
        return result

    # ──────────── 小票解析 ────────────

    def _parse_receipt(self, lines: list[OCRLine]) -> dict[str, Any]:
        """解析小票：提取商户、日期、商品列表、合计。"""
        texts = [ln.text for ln in lines]
        joined = "\n".join(texts)

        # 日期
        date_match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", joined)
        purchase_date = None
        if date_match:
            purchase_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"

        # 时间
        time_match = re.search(r"(\d{1,2}):(\d{2}):?(\d{2})?", joined)
        purchase_time = None
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            s = int(time_match.group(3)) if time_match.group(3) else 0
            purchase_time = f"{h:02d}:{m:02d}:{s:02d}"

        # 商户（通常是第一行或包含"商店/超市/商场"等关键词的行）
        merchant = None
        for text in texts[:5]:
            if re.search(r"商店|超市|商场|会员|购物|中心|广场", text):
                merchant = text.strip()
                break
        if not merchant and texts:
            merchant = texts[0].strip()

        # 忽略的关键词
        ignored = (
            "商品", "数量", "单价", "总价", "合计", "交易", "会员", "上岗", "欢迎",
            "微信", "支付宝", "支付", "付款", "折扣", "优惠", "满减", "实付", "应付",
            "找零", "现金", "银行卡", "代金券", "优惠券", "小票", "收银", "流水",
        )

        items: list[dict[str, Any]] = []
        pending_name: str | None = None
        for index, text in enumerate(texts):
            compact = text.replace(" ", "")
            if any(word in compact for word in ignored):
                pending_name = None
                continue
            barcode_match = re.fullmatch(r"\d{7,14}", compact)
            prices = re.findall(r"(?<!\d)(\d{1,5}\.\d{2})(?!\d)", text)
            has_letters = bool(re.search(r"[\u4e00-\u9fffA-Za-z]", text))
            if has_letters and not prices:
                pending_name = text
                continue
            if barcode_match and index + 1 < len(texts):
                next_prices = re.findall(r"(?<!\d)(\d{1,5}\.\d{2})(?!\d)", texts[index + 1])
                if pending_name and next_prices:
                    price = float(next_prices[-1])
                    items.append({"name": pending_name, "barcode": compact,
                                 "quantity": 1, "unit": "件",
                                 "unit_price": price, "total_price": price})
                    pending_name = None
            elif pending_name and prices:
                price = float(prices[-1])
                items.append({"name": pending_name, "barcode": None,
                             "quantity": 1, "unit": "件",
                             "unit_price": price, "total_price": price})
                pending_name = None

        # 合计金额
        total_match = re.search(r"(?:合计|总计|实付|应付)[^\d]*(\d+(?:\.\d{2})?)", joined)
        total = float(total_match.group(1)) if total_match else round(
            sum(float(item.get("total_price") or 0) for item in items), 2)

        return {
            "merchant": merchant,
            "purchase_date": purchase_date,
            "purchase_time": purchase_time,
            "items": items,
            "item_count": len(items),
            "total": total,
            "currency": "CNY",
            "warnings": [] if items else ["未自动提取到商品行，请在确认页手动补充。"],
        }

    # ──────────── 日期解析 ────────────

    def _parse_expiry(self, lines: list[OCRLine]) -> dict[str, Any]:
        """解析包装日期：提取生产日期、到期日期、保质期。"""
        from app.services.expiry_ocr_service import ExpiryOCRService
        texts = [ln.text for ln in lines]
        joined = "\n".join(texts)
        parsed = ExpiryOCRService.parse_text(joined)
        if not lines:
            parsed["warnings"].append("未识别到文字，请手动核对包装。")
        elif not parsed["detected_dates"]:
            parsed["warnings"].append("识别到文字，但未找到可靠日期，请手动核对包装。")
        return parsed

    # ──────────── 通用解析 ────────────

    def _parse_general(self, lines: list[OCRLine]) -> dict[str, Any]:
        """通用解析：保留排版格式，返回结构化文本块。"""
        # 按 y 分组为段落
        paragraphs: list[dict[str, Any]] = []
        current_para: list[str] = []
        last_y = None

        for ln in lines:
            y = ln.bbox[0][1] if ln.bbox and len(ln.bbox) >= 2 else 0.0
            if last_y is not None and abs(y - last_y) > 50:
                # 行间距过大，视为段落分隔
                if current_para:
                    paragraphs.append({"text": "\n".join(current_para), "line_count": len(current_para)})
                current_para = []
            current_para.append(ln.text)
            last_y = y

        if current_para:
            paragraphs.append({"text": "\n".join(current_para), "line_count": len(current_para)})

        return {
            "paragraphs": paragraphs,
            "paragraph_count": len(paragraphs),
            "formatted_text": "\n\n".join(p["text"] for p in paragraphs),
            "warnings": [] if lines else ["未识别到文字。"],
        }
