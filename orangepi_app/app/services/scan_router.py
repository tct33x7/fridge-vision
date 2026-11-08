from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.barcode_service import BarcodeScanService
from app.services.expiry_ocr_service import ExpiryOCRService
from app.services.food_classifier import FoodPhotoService
from app.services.ocr_pipeline import get_pipeline
from app.services.receipt_ocr_service import ReceiptOCRService


class ScanRouter:
    """扫描路由器：根据 scan_type 分发到对应识别服务。"""

    def __init__(self) -> None:
        self.receipt_service = ReceiptOCRService()
        self.expiry_service = ExpiryOCRService()
        self.barcode_service = BarcodeScanService()
        self.food_service = FoodPhotoService()

    def analyze(
        self,
        scan_type: str,
        image_path: Path,
        original_name: str,
        file_id: str,
        engine: str = "rapidocr",
    ) -> dict[str, Any]:
        """分析图片，返回结构化识别结果。

        Args:
            scan_type: 识别类型 (food / barcode / receipt / expiry / ocr)
            image_path: 图片路径
            original_name: 原始文件名
            file_id: 文件唯一标识
            engine: OCR 引擎 ID（仅 receipt / expiry / ocr 使用）
        """
        if scan_type == "receipt":
            return self.receipt_service.recognize(image_path, original_name, file_id, engine=engine)
        if scan_type == "expiry":
            return self.expiry_service.recognize(image_path, original_name, file_id, engine=engine)
        if scan_type == "barcode":
            return self.barcode_service.recognize(image_path, original_name, file_id)
        if scan_type == "food":
            return self.food_service.recognize(image_path, original_name, file_id)
        if scan_type == "ocr":
            return self._run_general_ocr(image_path, file_id, engine)
        raise ValueError("当前仅支持食物照片、条形码、小票、日期和通用 OCR 识别")

    def list_engines(self) -> list[dict[str, Any]]:
        """返回可用 OCR 引擎列表。"""
        return get_pipeline().list_engines()

    @staticmethod
    def _run_general_ocr(image_path: Path, file_id: str, engine: str) -> dict[str, Any]:
        """通用 OCR 识别：使用管线进行预处理 → 识别 → 后处理。"""
        pipeline = get_pipeline()
        return pipeline.run(image_path, file_id, engine=engine, profile="general")
