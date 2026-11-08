from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_api_settings


class OpenFoodFactsClient:
    def __init__(self) -> None:
        settings = get_api_settings("open_food_facts")
        enabled_env = os.getenv("OPEN_FOOD_FACTS_ENABLED")
        self.enabled = (
            enabled_env.strip().lower() not in {"0", "false", "no", "off"}
            if enabled_env is not None
            else bool(settings.get("enabled", True))
        )
        self.base_url = (
            os.getenv("OPEN_FOOD_FACTS_BASE_URL")
            or str(settings.get("base_url") or "https://world.openfoodfacts.org/api/v2/product")
        ).rstrip("/")
        self.timeout_seconds = float(
            os.getenv("OPEN_FOOD_FACTS_TIMEOUT_SECONDS") or settings.get("timeout_seconds") or 6
        )

    def lookup(self, barcode: str) -> dict[str, object] | None:
        if not self.enabled:
            return None
        request = Request(
            f"{self.base_url}/{barcode}.json",
            headers={"User-Agent": "SmartFridgeDemo/1.0 (local Orange Pi demo)"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None
        if data.get("status") != 1:
            return None
        product = data.get("product") or {}
        nutriments = product.get("nutriments") or {}
        return {
            "name": product.get("product_name_zh") or product.get("product_name") or "未知商品",
            "barcode": barcode,
            "brand": product.get("brands"),
            "category": product.get("categories") or "其他",
            "calories_kcal": nutriments.get("energy-kcal_100g") or 0,
            "protein_g": nutriments.get("proteins_100g") or 0,
            "carbs_g": nutriments.get("carbohydrates_100g") or 0,
            "fat_g": nutriments.get("fat_100g") or 0,
            "source": "openfoodfacts",
        }
