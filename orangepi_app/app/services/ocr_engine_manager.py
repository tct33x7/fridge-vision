"""多引擎 OCR 管理器
====================
统一管理 RapidOCR / Tesseract / EasyOCR / CnOCR / ddddocr / Surya 等引擎，
提供标准化的识别接口和延迟初始化。

每个引擎返回统一的 OCRResult 格式：
    {
        "lines": [OCRLine(text, confidence, bbox)],
        "engine": str,
        "elapsed": float,
    }
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("ocr_engine_manager")


@dataclass(slots=True)
class OCRLine:
    """单行 OCR 识别结果。"""
    text: str
    confidence: float = 0.0
    # bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] 或 None
    bbox: list[list[float]] | None = None


@dataclass(slots=True)
class OCRResult:
    """一次 OCR 识别的完整结果。"""
    lines: list[OCRLine] = field(default_factory=list)
    engine: str = "unknown"
    elapsed: float = 0.0
    error: str | None = None

    @property
    def texts(self) -> list[str]:
        return [ln.text for ln in self.lines if ln.text]

    @property
    def avg_confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(ln.confidence for ln in self.lines) / len(self.lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [{"text": ln.text, "confidence": round(ln.confidence, 3), "bbox": ln.bbox} for ln in self.lines],
            "texts": self.texts,
            "count": len(self.lines),
            "engine": self.engine,
            "elapsed": round(self.elapsed, 2),
            "avg_confidence": round(self.avg_confidence, 3),
            "error": self.error,
        }


class OCREngineManager:
    """统一管理多个 OCR 引擎，提供标准化的识别接口。

    所有引擎延迟初始化，首次调用时才加载模型。
    """

    def __init__(self) -> None:
        self._rapidocr: Any = None
        self._ddddocr: Any = None
        self._cnocr: Any = None
        self._easyocr: Any = None
        self._surya: Any = None
        self._tesseract_path: str | None = shutil.which("tesseract")
        self._tessdata_ok: bool = self._tesseract_path is not None
        self._engines: list[dict[str, Any]] = self._build_engine_list()

    # ──────────── 引擎注册 ────────────

    def _build_engine_list(self) -> list[dict[str, Any]]:
        engines: list[dict[str, Any]] = []

        # RapidOCR
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            engines.append({"id": "rapidocr", "name": "RapidOCR（中英文·中文友好）",
                            "type": "rapidocr", "available": True})
        except ImportError:
            try:
                from rapidocr import RapidOCR  # type: ignore  # noqa: F401
                engines.append({"id": "rapidocr", "name": "RapidOCR（中英文·中文友好）",
                                "type": "rapidocr", "available": True})
            except ImportError:
                engines.append({"id": "rapidocr", "name": "RapidOCR（未安装）",
                                "type": "rapidocr", "available": False})

        # Tesseract
        if self._tessdata_ok:
            for lang, label, friendly in [
                ("chi_sim", "简体中文", "中文友好"),
                ("chi_tra", "繁体中文", "中文友好"),
                ("eng", "英文", "英文友好"),
                ("chi_sim+eng", "中英文混合", "通用"),
                ("osd", "自动检测语言", "通用"),
            ]:
                available = self._check_tesseract_lang(lang)
                engines.append({
                    "id": f"tesseract_{lang.replace('+', '_')}",
                    "name": f"Tesseract {label}（{friendly}）",
                    "type": "tesseract",
                    "lang": lang,
                    "available": available,
                })
        else:
            engines.append({"id": "tesseract_none", "name": "Tesseract（未安装）",
                           "type": "tesseract", "available": False})

        # EasyOCR
        try:
            import easyocr  # noqa: F401
            engines.append({"id": "easyocr", "name": "EasyOCR（中英文·中文友好）",
                           "type": "easyocr", "available": True})
        except ImportError:
            engines.append({"id": "easyocr", "name": "EasyOCR（未安装）",
                           "type": "easyocr", "available": False})

        # CnOCR
        try:
            import cnocr  # noqa: F401
            engines.append({"id": "cnocr", "name": "CnOCR（中文·中文友好）",
                           "type": "cnocr", "available": True})
        except ImportError:
            engines.append({"id": "cnocr", "name": "CnOCR（未安装）",
                           "type": "cnocr", "available": False})

        # ddddocr
        try:
            import ddddocr  # noqa: F401
            engines.append({"id": "ddddocr", "name": "ddddocr（验证码·短文本）",
                           "type": "ddddocr", "available": True})
        except ImportError:
            engines.append({"id": "ddddocr", "name": "ddddocr（未安装）",
                           "type": "ddddocr", "available": False})

        # Surya
        try:
            from surya.recognition import RecognitionPredictor  # noqa: F401
            engines.append({"id": "surya", "name": "Surya（多语言·文档级）",
                           "type": "surya", "available": True})
        except ImportError:
            engines.append({"id": "surya", "name": "Surya（未安装）",
                           "type": "surya", "available": False})

        return engines

    def _check_tesseract_lang(self, lang: str) -> bool:
        if not self._tesseract_path:
            return False
        try:
            result = subprocess.run(
                [self._tesseract_path, "--list-langs"],
                capture_output=True, text=True, timeout=5,
            )
            return all(l in result.stdout for l in lang.split("+"))
        except Exception:
            return False

    def list_engines(self) -> list[dict[str, Any]]:
        return self._engines

    def get_engine(self, engine_id: str) -> dict[str, Any] | None:
        return next((e for e in self._engines if e["id"] == engine_id), None)

    # ──────────── 统一识别入口 ────────────

    def recognize(self, engine_id: str, image: np.ndarray | Path) -> OCRResult:
        """用指定引擎识别图像，返回统一的 OCRResult。"""
        engine = self.get_engine(engine_id)
        if engine is None:
            return OCRResult(engine=engine_id, error=f"未知引擎: {engine_id}")
        if not engine.get("available"):
            return OCRResult(engine=engine_id, error=f"引擎不可用: {engine['name']}")

        # 如果传入 Path，读取为 ndarray
        if isinstance(image, Path):
            image = cv2.imread(str(image))
            if image is None:
                return OCRResult(engine=engine_id, error="无法读取图像文件")

        t0 = time.monotonic()
        try:
            if engine["type"] == "rapidocr":
                result = self._run_rapidocr(image)
            elif engine["type"] == "tesseract":
                result = self._run_tesseract(image, engine["lang"])
            elif engine["type"] == "easyocr":
                result = self._run_easyocr(image)
            elif engine["type"] == "cnocr":
                result = self._run_cnocr(image)
            elif engine["type"] == "ddddocr":
                result = self._run_ddddocr(image)
            elif engine["type"] == "surya":
                result = self._run_surya(image)
            else:
                result = OCRResult(engine=engine_id, error="未知引擎类型")
        except Exception as exc:
            log.error("引擎 %s 异常: %s\n%s", engine_id, exc, traceback.format_exc())
            result = OCRResult(engine=engine_id, error=f"引擎执行异常: {exc}")

        result.elapsed = round(time.monotonic() - t0, 2)
        result.engine = engine_id
        return result

    # ──────────── 各引擎实现 ────────────

    def _run_rapidocr(self, image: np.ndarray) -> OCRResult:
        if self._rapidocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError:
                from rapidocr import RapidOCR  # type: ignore
            self._rapidocr = RapidOCR()
        result = self._rapidocr(image)
        lines: list[OCRLine] = []
        # rapidocr_onnxruntime 返回 (result, elapse); rapidocr 返回对象有 .txts/.scores/.boxes
        if isinstance(result, tuple):
            entries, _ = result
            for entry in entries or []:
                if len(entry) >= 3:
                    bbox = entry[0] if isinstance(entry[0], list) else None
                    lines.append(OCRLine(
                        text=str(entry[1]).strip(),
                        confidence=float(entry[2]),
                        bbox=bbox,
                    ))
        else:
            # 新版 rapidocr 返回对象
            txts = list(result.txts) if result.txts else []
            scores = list(result.scores) if result.scores is not None else []
            boxes = list(result.boxes) if hasattr(result, "boxes") and result.boxes is not None else []
            for i, t in enumerate(txts):
                conf = float(scores[i]) if i < len(scores) else 0.0
                bbox = boxes[i].tolist() if i < len(boxes) and boxes[i] is not None else None
                lines.append(OCRLine(text=t, confidence=conf, bbox=bbox))
        return OCRResult(lines=lines)

    def _run_tesseract(self, image: np.ndarray, lang: str) -> OCRResult:
        import pytesseract
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if lang == "osd":
            try:
                osd = pytesseract.image_to_osd(gray, config="--psm 0")
                import re
                m = re.search(r"Script:\s*(\S+)", osd)
                script = m.group(1) if m else "Latin"
                lang_map = {"HanS": "chi_sim", "HanT": "chi_tra",
                           "Latin": "eng", "Japanese": "jpn", "Korean": "kor"}
                detected_lang = lang_map.get(script, "eng")
            except Exception:
                detected_lang = "eng"
            text = pytesseract.image_to_string(gray, lang=detected_lang, config="--psm 6")
            lines = [OCRLine(text=t.strip()) for t in text.split("\n") if t.strip()]
            return OCRResult(lines=lines)
        else:
            # 使用 image_to_data 获取置信度和位置
            data = pytesseract.image_to_data(gray, lang=lang, config="--psm 6",
                                             output_type=pytesseract.Output.DICT)
            lines: list[OCRLine] = []
            for i in range(len(data["text"])):
                txt = data["text"][i].strip()
                if txt:
                    conf = float(data["conf"][i]) / 100.0 if int(data["conf"][i]) >= 0 else 0.0
                    x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                    bbox = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
                    lines.append(OCRLine(text=txt, confidence=conf, bbox=bbox))
            return OCRResult(lines=lines)

    def _run_easyocr(self, image: np.ndarray) -> OCRResult:
        if self._easyocr is None:
            import easyocr
            log.info("初始化 EasyOCR...")
            self._easyocr = easyocr.Reader(lang_list=["ch_sim", "en"], gpu=False, verbose=False)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self._easyocr.readtext(rgb)
        lines: list[OCRLine] = []
        for bbox, text, conf in results:
            text = text.strip()
            if text:
                lines.append(OCRLine(
                    text=text,
                    confidence=round(float(conf), 3),
                    bbox=[[list(p) for p in bbox]],
                ))
        return OCRResult(lines=lines)

    def _run_cnocr(self, image: np.ndarray) -> OCRResult:
        if self._cnocr is None:
            import cnocr
            log.info("初始化 CnOCR...")
            self._cnocr = cnocr.CnOcr(context="cpu")
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self._cnocr.ocr(rgb)
        lines: list[OCRLine] = []
        for r in results:
            text = r.get("text", "").strip() if isinstance(r, dict) else str(r).strip()
            if text:
                conf = float(r.get("score", 0.0)) if isinstance(r, dict) else 0.0
                bbox = r.get("box") if isinstance(r, dict) else None
                lines.append(OCRLine(text=text, confidence=conf, bbox=bbox))
        return OCRResult(lines=lines)

    def _run_ddddocr(self, image: np.ndarray) -> OCRResult:
        if self._ddddocr is None:
            import ddddocr
            log.info("初始化 ddddocr...")
            self._ddddocr = ddddocr.DdddOcr(ocr=True, use_gpu=False, show_ad=False)
        _, encoded = cv2.imencode(".png", image)
        text = self._ddddocr.classification(encoded.tobytes())
        text = text.strip() if text else ""
        if text:
            return OCRResult(lines=[OCRLine(text=text)])
        return OCRResult()

    def _run_surya(self, image: np.ndarray) -> OCRResult:
        if self._surya is None:
            from surya.recognition import RecognitionPredictor, get_default_manager
            log.info("初始化 Surya...")
            manager = get_default_manager()
            self._surya = RecognitionPredictor(manager)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        results = self._surya([pil_img], full_page=True)
        lines: list[OCRLine] = []
        for page_result in results:
            page_lines = getattr(page_result, "lines", None) or getattr(page_result, "text_lines", None)
            if page_lines:
                for line in page_lines:
                    text = getattr(line, "text", None) or (
                        line.get("text", "") if isinstance(line, dict) else str(line))
                    text = text.strip() if text else ""
                    if text:
                        conf = getattr(line, "confidence", None)
                        if conf is None and isinstance(line, dict):
                            conf = line.get("confidence", 0.0)
                        conf = float(conf) if conf else 0.0
                        lines.append(OCRLine(text=text, confidence=conf))
            elif hasattr(page_result, "text") and page_result.text:
                text = page_result.text.strip()
                if text:
                    lines.append(OCRLine(text=text))
        return OCRResult(lines=lines)
