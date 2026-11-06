from __future__ import annotations

from typing import Any


def prepare_recipe_inventory(batches: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Keep only edible stock and put the most urgent known expiry first."""
    usable = [batch for batch in batches if batch.get("expiry_status") != "expired"]
    usable.sort(
        key=lambda item: (
            item.get("days_until_expiry") is None,
            item.get("days_until_expiry") if item.get("days_until_expiry") is not None else 9999,
        )
    )
    return usable[:limit]


def recommend_recipes(batches: list[dict[str, Any]], servings: int = 2) -> list[dict[str, Any]]:
    usable = prepare_recipe_inventory(batches)
    names = [str(item["name"]) for item in usable]

    if not usable:
        return [{
            "title": "先给冰箱加点料",
            "subtitle": "录入库存后，今日食谱会优先消耗临期食材",
            "minutes": 0,
            "servings": servings,
            "ingredients": [],
            "steps": ["上传购物小票或手动添加第一件食材"],
            "calories_kcal": 0,
            "priority_reason": "库存为空",
        }]

    near = next((item for item in usable if item.get("expiry_status") == "expiring"), usable[0])
    ingredient_names = names[:4]
    primary = str(near["name"])
    has_beef = any("牛" in name for name in names)
    has_chicken = any("鸡" in name for name in names)
    if has_beef:
        title, subtitle, minutes = "牛肉能量暖碗", "一锅把优质蛋白和临期食材安排明白", 25
    elif has_chicken:
        title, subtitle, minutes = "脆香鸡肉杂粮沙拉", "高蛋白、少负担，适合今天的快手晚餐", 18
    else:
        title, subtitle, minutes = f"{primary} 快手料理", "优先吃掉更接近日期的库存", 15

    reason = (
        f"{primary} 还有 {near['days_until_expiry']} 天到期，优先使用"
        if near.get("days_until_expiry") is not None
        else f"优先使用较早入库的 {primary}"
    )
    return [{
        "title": title,
        "subtitle": subtitle,
        "minutes": minutes,
        "servings": servings,
        "ingredients": ingredient_names,
        "steps": ["准备并清洗食材", "先处理蛋白质食材至熟", "加入其余食材调味组合", "按人数分装，确认后扣减库存"],
        "calories_kcal": 520,
        "priority_reason": reason,
    }]
