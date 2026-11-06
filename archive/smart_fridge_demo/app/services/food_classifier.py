from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from app.config import PROCESSED_DIR
from app.services.product_matcher import enrich_product
from app.services.yolo_food_detector import detect_food_image


DEMO_FOOD_ITEM = {
    "name": "番茄",
    "barcode": None,
    "category": "蔬果",
    "quantity": 3,
    "unit": "个",
    "unit_price": None,
    "total_price": None,
}

FOOD_LABEL_ALIASES = {
    "almond": "杏仁",
    "apple": "苹果",
    "asparagus": "芦笋",
    "avocado": "牛油果",
    "bacon": "培根",
    "banana": "香蕉",
    "bean": "豆类",
    "bean sprout": "豆芽",
    "beef": "牛肉",
    "beetroot": "甜菜根",
    "bell pepper": "彩椒",
    "blackberry": "黑莓",
    "blueberry": "蓝莓",
    "bok choy": "小白菜",
    "bread": "面包",
    "brie cheese": "布里奶酪",
    "broccoli": "西兰花",
    "cabbage": "卷心菜",
    "carrot": "胡萝卜",
    "cauliflower": "花椰菜",
    "cheddar cheese": "切达奶酪",
    "cheese": "奶酪",
    "cherry": "樱桃",
    "chicken breast": "鸡胸肉",
    "chicken wing": "鸡翅",
    "chilli": "辣椒",
    "chocolate": "巧克力",
    "corn": "玉米",
    "cucumber": "黄瓜",
    "dry grape": "葡萄干",
    "durian": "榴莲",
    "egg": "鸡蛋",
    "eggplant": "茄子",
    "fish": "鱼",
    "garlic": "大蒜",
    "ginger": "生姜",
    "grape": "葡萄",
    "green grape": "青葡萄",
    "green pepper": "青椒",
    "guava": "番石榴",
    "jalepeno": "墨西哥辣椒",
    "jam": "果酱",
    "kiwi": "猕猴桃",
    "lemon": "柠檬",
    "mango": "芒果",
    "mangoteen": "山竹",
    "meat ball": "肉丸",
    "milk": "牛奶",
    "mozarella cheese": "马苏里拉奶酪",
    "mushroom": "蘑菇",
    "mussel": "贻贝",
    "noodle": "面条",
    "onion": "洋葱",
    "orange": "橙子",
    "oyster": "牡蛎",
    "papaya": "木瓜",
    "parmesan cheese": "帕玛森奶酪",
    "pasta": "意大利面",
    "pineapple": "菠萝",
    "pomegranate": "石榴",
    "pork": "猪肉",
    "pork belly": "五花肉",
    "pork rib": "猪排骨",
    "potato": "土豆",
    "pumpkin": "南瓜",
    "raspberry": "覆盆子",
    "salad": "沙拉",
    "salmon": "三文鱼",
    "scallop": "扇贝",
    "shrimp": "虾",
    "spring onion": "香葱",
    "starfruit": "杨桃",
    "stilton cheese": "斯蒂尔顿奶酪",
    "strawberry": "草莓",
    "sweet potato": "红薯",
    "tomato": "番茄",
    "tuna": "金枪鱼",
    "vegetable": "蔬菜",
    "watermelon": "西瓜",
    "yogurt": "酸奶",
}


def classify_food_image(image_path: str) -> dict[str, object]:
    """Compatibility adapter returning the strongest YOLO detection."""
    result = detect_food_image(image_path)
    detections = result.get("detections") or []
    strongest = detections[0] if detections else {}
    return {
        "label": strongest.get("label"),
        "confidence": strongest.get("confidence", 0.0),
        "status": result.get("status", "model_error"),
    }


def _display_label(label: str) -> str:
    return FOOD_LABEL_ALIASES.get(label.strip().lower(), label.strip())


def _group_detections(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for detection in detections:
        raw_label = str(detection.get("label") or "").strip()
        if not raw_label:
            continue
        label = _display_label(raw_label)
        current = grouped.setdefault(
            label,
            {"name": label, "quantity": 0, "unit": "个", "confidence": 0.0},
        )
        current["quantity"] += 1
        current["confidence"] = max(float(current["confidence"]), float(detection.get("confidence") or 0))
    return [enrich_product(item) for item in grouped.values()]


def _annotate_detections(image_path: Path, detections: list[dict[str, Any]]) -> None:
    if not detections:
        return
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    line_width = max(2, round(min(image.size) / 240))
    for detection in detections:
        bbox = detection.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        draw.rectangle(tuple(float(value) for value in bbox), outline="#7ac943", width=line_width)
        caption = f"{detection.get('label', 'food')} {float(detection.get('confidence') or 0):.0%}"
        draw.text((float(bbox[0]) + 3, float(bbox[1]) + 3), caption, fill="#101010", stroke_width=2, stroke_fill="#ffffff")
    image.save(image_path, quality=90)


class FoodPhotoService:
    def preprocess(self, image_path: Path, file_id: str) -> Path:
        processed_path = PROCESSED_DIR / f"{file_id}_food.jpg"
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            image.save(processed_path, quality=90)
        return processed_path

    def recognize(self, image_path: Path, original_name: str, file_id: str) -> dict[str, Any]:
        processed_path = self.preprocess(image_path, file_id)
        is_demo = original_name.lower() == "demo-food.png"
        if is_demo:
            engine = "fixture"
            detections: list[dict[str, Any]] = []
            items = [enrich_product(DEMO_FOOD_ITEM)]
            confidence = 0.96
            detected_count = 3
            warnings: list[str] = []
        else:
            result = detect_food_image(processed_path)
            engine = str(result.get("status") or "model_error")
            detections = list(result.get("detections") or [])
            items = _group_detections(detections)
            confidence = max((float(item.get("confidence") or 0) for item in detections), default=0.0)
            detected_count = len(detections)
            if detections:
                _annotate_detections(processed_path, detections)
                warnings = []
            elif result.get("error"):
                warnings = [f"YOLO 食物识别不可用：{result['error']}。可在确认页手动填写商品名称。"]
            else:
                warnings = ["YOLO 未检测到已训练的食物类别；请换用背景更简洁、目标更清晰的照片，或手动填写商品名称。"]
        return {
            "engine": engine,
            "processed_name": processed_path.name,
            "items": items,
            "item_count": len(items),
            "detected_count": detected_count,
            "detections": detections,
            "purchase_date": date.today().isoformat(),
            "confidence": confidence,
            "warnings": warnings,
        }


def render_demo_food_photo() -> bytes:
    """Create a lightweight tomato still-life used only by the offline demo."""
    image = Image.new("RGB", (720, 520), "#f4e5be")
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 80, 650, 480), fill="#fffefb", outline="#171717", width=8)
    for x, y, radius, color in ((210, 255, 105, "#ef4e38"), (365, 220, 112, "#ff6952"), (505, 300, 94, "#df3d2d")):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="#171717", width=5)
        draw.polygon(((x, y - radius + 4), (x - 48, y - radius + 55), (x, y - radius + 38), (x + 48, y - radius + 55)), fill="#63a941", outline="#171717")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
