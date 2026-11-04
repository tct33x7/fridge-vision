from __future__ import annotations

import re
from typing import Any


NUTRITION_PRESETS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (("牛奶", "奶"), {"category": "乳品", "estimated_weight_g": 250, "calories_kcal": 66, "protein_g": 3.3, "carbs_g": 4.8, "fat_g": 3.8}),
    (("牛腩", "牛肉", "嫩肩", "牛前胸"), {"category": "肉类", "estimated_weight_g": 500, "calories_kcal": 205, "protein_g": 20, "carbs_g": 0, "fat_g": 13}),
    (("鸡蛋", "蛋"), {"category": "蛋类", "estimated_weight_g": 500, "calories_kcal": 144, "protein_g": 13.3, "carbs_g": 2.8, "fat_g": 8.8}),
    (("烤鸡", "鸡"), {"category": "肉类", "estimated_weight_g": 800, "calories_kcal": 190, "protein_g": 27, "carbs_g": 1, "fat_g": 8}),
    (("面包", "奶酪包", "吐司"), {"category": "烘焙", "estimated_weight_g": 300, "calories_kcal": 285, "protein_g": 9, "carbs_g": 49, "fat_g": 6}),
    (("芝麻酥", "饼干", "糕点"), {"category": "零食", "estimated_weight_g": 200, "calories_kcal": 520, "protein_g": 8, "carbs_g": 58, "fat_g": 28}),
    (("油",), {"category": "粮油", "estimated_weight_g": 500, "calories_kcal": 899, "protein_g": 0, "carbs_g": 0, "fat_g": 99.9}),
    (("菜", "蔬", "番茄", "黄瓜"), {"category": "蔬果", "estimated_weight_g": 300, "calories_kcal": 30, "protein_g": 1.5, "carbs_g": 5, "fat_g": 0.3}),
    (("香蕉",), {"category": "蔬果", "estimated_weight_g": 120, "calories_kcal": 89, "protein_g": 1.1, "carbs_g": 22.8, "fat_g": 0.3}),
]


def clean_product_name(name: str) -> str:
    value = name.strip(" .，。·-_")
    value = re.sub(r"^(MM|Mm|mm)", "", value)
    value = re.sub(r"[PpWw]$", "", value)
    return value.strip(" .，。·-_") or name.strip()


def enrich_product(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    enriched["name"] = clean_product_name(str(enriched.get("name") or "未命名商品"))
    defaults: dict[str, Any] = {
        "category": "其他",
        "estimated_weight_g": 100,
        "calories_kcal": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0,
    }
    for keywords, preset in NUTRITION_PRESETS:
        if any(keyword in enriched["name"] for keyword in keywords):
            defaults.update(preset)
            break
    for key, value in defaults.items():
        enriched.setdefault(key, value)
        if enriched[key] is None:
            enriched[key] = value
    return enriched
