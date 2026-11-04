from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from app.config import PROCESSED_DIR
from app.services.product_matcher import enrich_product


DEMO_BARCODE = "6901234567892"
DEMO_PRODUCT = {
    "name": "原味酸奶",
    "barcode": DEMO_BARCODE,
    "brand": "食光 Demo",
    "category": "乳品",
    "quantity": 1,
    "unit": "盒",
    "unit_price": 12.9,
    "total_price": 12.9,
}


def detect_barcodes(image_path: Path) -> list[str]:
    """Decode common 1D/2D codes when the optional zxing-cpp wheel exists."""
    try:
        import zxingcpp  # type: ignore

        with Image.open(image_path) as image:
            values = [str(item.text).strip() for item in zxingcpp.read_barcodes(image)]
        return list(dict.fromkeys(value for value in values if value))
    except Exception:
        # zxing-cpp is intentionally optional on ARM. The confirmation page remains
        # usable as a manual fallback when the decoder is not installed.
        return []


class BarcodeScanService:
    def preprocess(self, image_path: Path, file_id: str) -> Path:
        processed_path = PROCESSED_DIR / f"{file_id}_barcode.png"
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            image.save(processed_path, format="PNG", optimize=True)
        return processed_path

    def recognize(self, image_path: Path, original_name: str, file_id: str) -> dict[str, Any]:
        processed_path = self.preprocess(image_path, file_id)
        is_demo = original_name.lower() == "demo-barcode.png"
        barcodes = [DEMO_BARCODE] if is_demo else detect_barcodes(processed_path)

        items: list[dict[str, Any]] = []
        for barcode in barcodes:
            if barcode == DEMO_BARCODE:
                items.append(enrich_product(DEMO_PRODUCT))
            else:
                items.append(
                    enrich_product(
                        {
                            "name": "待确认条码商品",
                            "barcode": barcode,
                            "quantity": 1,
                            "unit": "件",
                            "unit_price": None,
                            "total_price": None,
                        }
                    )
                )

        warnings: list[str] = []
        if not barcodes:
            warnings.append("未检测到条形码；请让条码占满画面、保持水平并避免反光，也可手动补录候选。")
        elif not is_demo:
            warnings.append("已读取条码，请核对商品名称；未命中本地商品库时需要手动填写。")

        return {
            "engine": "fixture" if is_demo else ("zxing-cpp" if barcodes else "manual"),
            "processed_name": processed_path.name,
            "barcodes": barcodes,
            "items": items,
            "item_count": len(items),
            "purchase_date": date.today().isoformat(),
            "confidence": 0.99 if is_demo else (0.88 if barcodes else 0.0),
            "warnings": warnings,
        }


_EAN_L = {
    "0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101", "4": "0100011",
    "5": "0110001", "6": "0101111", "7": "0111011", "8": "0110111", "9": "0001011",
}
_EAN_G = {
    "0": "0100111", "1": "0110011", "2": "0011011", "3": "0100001", "4": "0011101",
    "5": "0111001", "6": "0000101", "7": "0010001", "8": "0001001", "9": "0010111",
}
_EAN_R = {digit: "".join("1" if bit == "0" else "0" for bit in pattern) for digit, pattern in _EAN_L.items()}
_EAN_PARITY = {
    "0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL", "4": "LGLLGG",
    "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG", "8": "LGLGGL", "9": "LGGLGL",
}


def render_demo_barcode() -> bytes:
    """Create a deterministic, genuinely decodable EAN-13 fixture in memory."""
    code = DEMO_BARCODE
    parity = _EAN_PARITY[code[0]]
    left = "".join((_EAN_L if mode == "L" else _EAN_G)[digit] for digit, mode in zip(code[1:7], parity))
    right = "".join(_EAN_R[digit] for digit in code[7:])
    modules = "101" + left + "01010" + right + "101"
    scale, quiet, top, bar_height = 4, 12, 34, 142
    width = (len(modules) + quiet * 2) * scale
    image = Image.new("RGB", (width, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, width - 8, 211), radius=16, outline="#171717", width=3)
    for index, bit in enumerate(modules):
        if bit == "1":
            x = (quiet + index) * scale
            guard = index < 3 or 45 <= index < 50 or index >= 92
            draw.rectangle((x, top, x + scale - 1, top + bar_height + (12 if guard else 0)), fill="#171717")
    draw.text((width // 2 - 42, 188), code, fill="#171717")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
