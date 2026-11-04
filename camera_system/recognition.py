"""Local OCR, document classification, field extraction, and async jobs."""

from __future__ import annotations

import csv
import io
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


LOG = logging.getLogger("camera_capture.recognition")


class TesseractRecognizer:
    """Offline OCR recognizer with conservative receipt/document extraction."""

    name = "tesseract-local-v1"

    def __init__(self, requested_languages: str, timeout_seconds: int, page_mode: int) -> None:
        self.executable = shutil.which("tesseract")
        self.requested_languages = requested_languages
        self.timeout_seconds = timeout_seconds
        self.page_mode = page_mode
        self.languages, self.setup_error = self._choose_languages()

    def _choose_languages(self) -> tuple[str, str | None]:
        if self.executable is None:
            return "", "未安装 Tesseract OCR"
        try:
            completed = subprocess.run(
                [self.executable, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return "", f"无法检查 Tesseract 语言包：{error}"
        installed = {
            line.strip()
            for line in completed.stdout.splitlines()[1:]
            if line.strip()
        }
        requested = [item for item in self.requested_languages.split("+") if item]
        selected = [item for item in requested if item in installed]
        if not selected and "eng" in installed:
            selected = ["eng"]
        if not selected and installed:
            selected = [sorted(installed)[0]]
        if not selected:
            return "", "Tesseract 没有可用语言包"
        missing = [item for item in requested if item not in installed]
        warning = f"缺少语言包：{', '.join(missing)}" if missing else None
        return "+".join(selected), warning

    def status(self) -> dict[str, object]:
        return {
            "recognizer": self.name,
            "available": self.executable is not None and bool(self.languages),
            "languages": self.languages,
            "warning": self.setup_error,
        }

    def recognize(self, image_path: Path) -> dict[str, object]:
        if self.executable is None or not self.languages:
            raise RuntimeError(self.setup_error or "Tesseract OCR 不可用")
        command = [
            self.executable,
            str(image_path),
            "stdout",
            "-l",
            self.languages,
            "--psm",
            str(self.page_mode),
            "tsv",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"OCR 超过 {self.timeout_seconds} 秒") from error
        except OSError as error:
            raise RuntimeError(f"无法启动 OCR：{error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            raise RuntimeError(detail[-1] if detail else f"OCR 返回代码 {completed.returncode}")

        lines, confidence = self._parse_tsv(completed.stdout)
        raw_text = "\n".join(lines).strip()
        document_type = classify_document(raw_text)
        document_name = choose_document_name(lines, document_type)
        fields = extract_fields(raw_text, lines, confidence, document_name)
        structured = {
            "schema_version": 1,
            "document": {
                "name": document_name,
                "type": document_type,
                "language": self.languages,
                "confidence": confidence,
            },
            "fields": fields,
            "items": [],
            "text": {"lines": lines},
        }
        return {
            "name": document_name,
            "type": document_type,
            "language": self.languages,
            "confidence": confidence,
            "raw_text": raw_text,
            "fields": fields,
            "structured": structured,
        }

    @staticmethod
    def _parse_tsv(tsv: str) -> tuple[list[str], float]:
        grouped: dict[tuple[int, int, int, int], list[str]] = {}
        confidences: list[float] = []
        reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                confidence = float(row.get("conf") or -1)
            except ValueError:
                confidence = -1
            if confidence >= 0:
                confidences.append(confidence)
            try:
                key = tuple(int(row.get(name) or 0) for name in ("page_num", "block_num", "par_num", "line_num"))
            except ValueError:
                key = (0, 0, 0, len(grouped))
            grouped.setdefault(key, []).append(text)
        lines = [" ".join(words).strip() for words in grouped.values() if words]
        average = round(sum(confidences) / len(confidences) / 100, 4) if confidences else 0.0
        return lines, average


def classify_document(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in ("发票", "invoice", "税号", "tax invoice")):
        return "invoice"
    if any(
        keyword in lowered
        for keyword in ("小票", "收据", "购物", "合计", "应付", "实付", "receipt", "total", "change")
    ):
        return "receipt"
    if any(keyword in lowered for keyword in ("型号", "序列号", "serial", "model", "barcode", "标签")):
        return "label"
    return "document"


def choose_document_name(lines: list[str], document_type: str) -> str:
    ignored = {"receipt", "invoice", "收据", "发票", "购物小票", "欢迎光临"}
    candidates: list[tuple[int, str]] = []
    for index, raw_line in enumerate(lines[:10]):
        line = re.sub(r"\s+", " ", raw_line).strip(" -_:：")
        if not 2 <= len(line) <= 80 or line.lower() in ignored:
            continue
        if not re.search(r"[A-Za-z\u4e00-\u9fff]", line):
            continue
        score = 30 - index * 2 + min(len(line), 25)
        if re.search(r"合计|总计|total|日期|电话|地址|编号", line, re.IGNORECASE):
            score -= 30
        candidates.append((score, line))
    if candidates:
        return max(candidates)[1]
    names = {"receipt": "未命名小票", "invoice": "未命名发票", "label": "未命名标签"}
    return names.get(document_type, "未命名文档")


def _field(
    value: str,
    normalized_value: str | None,
    confidence: float,
    source: str = "ocr_rule",
) -> dict[str, object]:
    return {
        "value": value,
        "normalized_value": normalized_value if normalized_value is not None else value,
        "confidence": confidence,
        "source": source,
    }


def extract_fields(
    text: str,
    lines: list[str],
    ocr_confidence: float,
    document_name: str,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "name": _field(document_name, document_name, ocr_confidence),
    }
    date_match = re.search(
        r"(?<!\d)(20\d{2}|19\d{2})\s*[-/.年]\s*(0?[1-9]|1[0-2])\s*[-/.月]\s*(0?[1-9]|[12]\d|3[01])日?",
        text,
    )
    if date_match:
        normalized_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        fields["date"] = _field(date_match.group(0), normalized_date, ocr_confidence)

    total_matches = list(
        re.finditer(
            r"(?:合\s*计|总\s*计|应\s*付|实\s*付|total|amount)\s*[:：]?\s*([¥￥$€£]?)\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
            text,
            re.IGNORECASE,
        )
    )
    if total_matches:
        match = total_matches[-1]
        amount = match.group(2).replace(",", "")
        fields["total"] = _field(match.group(0), amount, ocr_confidence)
        symbol = match.group(1)
        currency = {"¥": "CNY", "￥": "CNY", "$": "USD", "€": "EUR", "£": "GBP"}.get(symbol)
        if currency:
            fields["currency"] = _field(symbol, currency, ocr_confidence)

    number_patterns = {
        "invoice_number": r"(?:发票号码|invoice\s*(?:no|number))\s*[:：#]?\s*([A-Z0-9-]{5,})",
        "receipt_number": r"(?:小票号|流水号|receipt\s*(?:no|number))\s*[:：#]?\s*([A-Z0-9-]{4,})",
        "tax_id": r"(?:税号|纳税人识别号|tax\s*id)\s*[:：]?\s*([A-Z0-9]{8,})",
    }
    for field_name, pattern in number_patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            fields[field_name] = _field(match.group(1), match.group(1).upper(), ocr_confidence)

    phone_match = re.search(r"(?<!\d)(?:\+?86[- ]?)?(1[3-9]\d{9}|0\d{2,3}[- ]?\d{7,8})(?!\d)", text)
    if phone_match:
        value = phone_match.group(0)
        fields["phone"] = _field(value, re.sub(r"\D", "", value), ocr_confidence)

    if lines:
        fields["line_count"] = _field(str(len(lines)), str(len(lines)), 1.0, "system")
    return fields


class RecognitionWorker:
    """Runs one OCR job at a time so capture and preview remain responsive."""

    def __init__(self, repository: Any, recognizer: TesseractRecognizer, stop: threading.Event) -> None:
        self.repository = repository
        self.recognizer = recognizer
        self.stop = stop
        self._queue: queue.Queue[str] = queue.Queue()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._current_id: str | None = None
        self._thread = threading.Thread(target=self._run, name="recognition", daemon=True)

    def start(self) -> None:
        self._thread.start()
        for capture_id in self.repository.recoverable_capture_ids():
            self.submit(capture_id)

    def submit(self, capture_id: str) -> None:
        with self._lock:
            if capture_id in self._queued or capture_id == self._current_id:
                return
            self._queued.add(capture_id)
            self._queue.put(capture_id)

    def retry(self, capture_id: str) -> bool:
        if not self.repository.retry(capture_id):
            return False
        self.submit(capture_id)
        return True

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                capture_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._lock:
                self._queued.discard(capture_id)
                self._current_id = capture_id
            try:
                self.repository.mark_processing(capture_id, self.recognizer.name)
                image_path = self.repository.image_path(capture_id)
                if image_path is None or not image_path.exists():
                    raise RuntimeError("原始照片不存在")
                result = self.recognizer.recognize(image_path)
                self.repository.complete_recognition(capture_id, result)
                LOG.info("识别完成：%s", capture_id)
            except Exception as error:  # job errors must never stop camera capture
                LOG.error("识别失败 %s：%s", capture_id, error)
                self.repository.fail_recognition(capture_id, str(error))
            finally:
                with self._lock:
                    self._current_id = None
                self._queue.task_done()

    def wait_for(self, capture_id: str, timeout: float) -> dict[str, object] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.repository.get(capture_id)
            if record is None:
                return None
            recognition = record.get("recognition")
            if isinstance(recognition, dict) and recognition.get("status") in {
                "completed",
                "failed",
                "skipped",
            }:
                return record
            time.sleep(0.1)
        return self.repository.get(capture_id)

    def status(self) -> dict[str, object]:
        with self._lock:
            current_id = self._current_id
            queued = len(self._queued)
        return {
            **self.recognizer.status(),
            "current_capture_id": current_id,
            "queued": queued,
        }

    def join(self) -> None:
        self._thread.join(timeout=2)
