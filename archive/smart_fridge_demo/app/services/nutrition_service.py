from __future__ import annotations

from typing import Any


DAILY_REFERENCE = {"calories_kcal": 2000, "protein_g": 60, "carbs_g": 300, "fat_g": 60}


def summarize_inventory(batches: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {key: 0.0 for key in DAILY_REFERENCE}
    known_products = 0
    for batch in batches:
        if batch.get("expiry_status") == "expired":
            continue
        factor = float(batch.get("estimated_weight_g") or 0) * float(batch.get("quantity") or 0) / 100
        if factor <= 0:
            continue
        if any(float(batch.get(key) or 0) > 0 for key in DAILY_REFERENCE):
            known_products += 1
        for key in DAILY_REFERENCE:
            totals[key] += factor * float(batch.get(key) or 0)
    totals = {key: round(value, 1) for key, value in totals.items()}
    percentages = {
        key: min(999, round(totals[key] / reference * 100))
        for key, reference in DAILY_REFERENCE.items()
    }
    return {
        "totals": totals,
        "daily_reference_percent": percentages,
        "known_product_count": known_products,
        "note": "按商品估算重量和每 100g 营养值计算，仅供饮食管理参考。",
    }

