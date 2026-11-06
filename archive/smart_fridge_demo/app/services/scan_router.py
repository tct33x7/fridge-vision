from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.barcode_service import BarcodeScanService
from app.services.expiry_ocr_service import ExpiryOCRService
from app.services.food_classifier import FoodPhotoService
from app.services.receipt_ocr_service import ReceiptOCRService


class ScanRouter:
    def __init__(self) -> None:
        self.receipt_service = ReceiptOCRService()
        self.expiry_service = ExpiryOCRService()
        self.barcode_service = BarcodeScanService()
        self.food_service = FoodPhotoService()

    def analyze(self, scan_type: str, image_path: Path, original_name: str, file_id: str) -> dict[str, Any]:
        if scan_type == "receipt":
            return self.receipt_service.recognize(image_path, original_name, file_id)
        if scan_type == "expiry":
            return self.expiry_service.recognize(image_path, original_name, file_id)
        if scan_type == "barcode":
            return self.barcode_service.recognize(image_path, original_name, file_id)
        if scan_type == "food":
            return self.food_service.recognize(image_path, original_name, file_id)
        raise ValueError("当前仅支持食物照片、条形码、小票和日期识别")
