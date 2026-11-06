"""Category and default shelf life for labels the door camera can produce.

YOLO 只给英文类别；这里把它映射成库存用的类别键，并给出"按类别估算到期日"所需的默认天数。
类别级默认天数以数据库表 ``category_shelf_life`` 为准（用户可改），本文件只提供标签→类别和
少数标签级覆盖（例如大蒜、土豆比一般蔬菜放得久）。
"""

from __future__ import annotations

FRUIT = {
    "apple", "avocado", "banana", "blackberry", "blueberry", "cherry", "durian", "grape",
    "green grape", "guava", "kiwi", "lemon", "mango", "mangoteen", "orange", "papaya",
    "pineapple", "pomegranate", "raspberry", "starfruit", "strawberry", "watermelon",
}
VEGETABLE = {
    "asparagus", "bean", "bean sprout", "beetroot", "bell pepper", "bok choy", "broccoli",
    "cabbage", "carrot", "cauliflower", "chilli", "corn", "cucumber", "eggplant", "garlic",
    "ginger", "green pepper", "jalepeno", "mushroom", "onion", "potato", "pumpkin",
    "salad", "spring onion", "sweet potato", "tomato", "vegetable",
}
MEAT = {"bacon", "beef", "chicken breast", "chicken wing", "meat ball", "pork", "pork belly", "pork rib"}
SEAFOOD = {"fish", "mussel", "oyster", "salmon", "scallop", "shrimp", "tuna"}
DAIRY = {
    "brie cheese", "cheddar cheese", "cheese", "milk", "mozarella cheese",
    "parmesan cheese", "stilton cheese", "yogurt",
}
EGG = {"egg"}
STAPLE = {"bread", "noodle", "pasta"}
BEVERAGE = {"bottle", "wine glass"}
CONDIMENT = {"jam"}
SNACK = {"almond", "chocolate", "dry grape", "donut", "cake"}
COOKED = {"sandwich", "hot dog", "pizza"}

CATEGORY_BY_LABEL: dict[str, str] = {}
for _category, _labels in (
    ("fruit", FRUIT),
    ("vegetable", VEGETABLE),
    ("meat", MEAT),
    ("seafood", SEAFOOD),
    ("dairy", DAIRY),
    ("egg", EGG),
    ("staple", STAPLE),
    ("beverage", BEVERAGE),
    ("condiment", CONDIMENT),
    ("snack", SNACK),
    ("cooked", COOKED),
):
    for _label in _labels:
        CATEGORY_BY_LABEL[_label] = _category

# 标签级覆盖：比所属类别放得更久或更短的东西（天）。
LABEL_SHELF_LIFE_DAYS: dict[str, int] = {
    "garlic": 30,
    "ginger": 30,
    "onion": 30,
    "potato": 30,
    "sweet potato": 30,
    "pumpkin": 14,
    "cabbage": 14,
    "carrot": 14,
    "apple": 21,
    "orange": 14,
    "lemon": 21,
    "watermelon": 5,
    "bean sprout": 2,
    "salad": 3,
    "bacon": 7,
    "chicken breast": 2,
    "chicken wing": 2,
    "mussel": 1,
    "oyster": 1,
    "cheddar cheese": 21,
    "parmesan cheese": 30,
    "mozarella cheese": 7,
    "yogurt": 10,
    "bread": 4,
    "noodle": 3,
    "jam": 60,
    "chocolate": 90,
    "almond": 90,
    "dry grape": 90,
}


def category_for(label: str) -> str:
    return CATEGORY_BY_LABEL.get(label.strip().lower(), "other")


def label_override_days(label: str) -> int | None:
    return LABEL_SHELF_LIFE_DAYS.get(label.strip().lower())
