from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.config import get_api_settings
from app.services.recipe_service import prepare_recipe_inventory


class DeepSeekRecipeError(RuntimeError):
    """Raised when DeepSeek cannot produce a safe, valid recipe document."""


class RecipeCandidate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    subtitle: str = Field(min_length=1, max_length=160)
    minutes: int = Field(ge=1, le=240)
    servings: int = Field(ge=1, le=12)
    ingredients: list[str] = Field(min_length=1, max_length=12)
    steps: list[str] = Field(min_length=2, max_length=12)
    calories_kcal: int = Field(ge=0, le=5000)
    priority_reason: str = Field(min_length=1, max_length=200)


class RecipeDocument(BaseModel):
    recipes: list[RecipeCandidate] = Field(min_length=1, max_length=2)


class DeepSeekRecipeClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_api_settings("deepseek")
        enabled_env = os.getenv("DEEPSEEK_ENABLED")
        self.enabled = (
            enabled_env.strip().lower() not in {"0", "false", "no", "off"}
            if enabled_env is not None
            else bool(settings.get("enabled", True))
        )
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("DEEPSEEK_API_KEY") or str(settings.get("api_key") or "")
        )
        self.base_url = (
            base_url
            or os.getenv("DEEPSEEK_BASE_URL")
            or str(settings.get("base_url") or "https://api.deepseek.com")
        ).rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL") or str(settings.get("model") or "deepseek-v4-flash")
        self.timeout_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS") or settings.get("timeout_seconds") or 25)
        )

    def configured(self) -> bool:
        return self.enabled and bool(self.api_key.strip())

    def generate(self, batches: list[dict[str, Any]], servings: int) -> list[dict[str, Any]]:
        if not self.configured():
            raise DeepSeekRecipeError("missing_api_key")

        inventory = prepare_recipe_inventory(batches)
        if not inventory:
            raise DeepSeekRecipeError("empty_inventory")

        inventory_context = [
            {
                "name": str(item["name"]),
                "category": item.get("category") or "其他",
                "quantity": float(item.get("quantity") or 0),
                "unit": item.get("unit") or "份",
                "expiry_status": item.get("expiry_status") or "unknown",
                "days_until_expiry": item.get("days_until_expiry"),
            }
            for item in inventory
        ]
        system_prompt = (
            "你是家庭冰箱食谱助手。请只输出 JSON 对象，不要输出 Markdown。"
            "JSON 必须符合：{\"recipes\":[{\"title\":\"\",\"subtitle\":\"\","
            "\"minutes\":20,\"servings\":2,\"ingredients\":[\"库存中的准确商品名\"],"
            "\"steps\":[\"步骤1\",\"步骤2\"],\"calories_kcal\":500,"
            "\"priority_reason\":\"为什么优先使用这些临期食材\"}]}。"
            "生成 1 到 2 个中文家常食谱。ingredients 只能使用用户给出的准确商品名称，"
            "不要把盐、油、水等基础调味料放入 ingredients；它们可以写在 steps 中。"
            "优先消耗 expiry_status=expiring 或 days_until_expiry 较小的食材。"
            "不得使用已过期或库存中不存在的食材。calories_kcal 表示每人份估算热量。"
        )
        user_prompt = json.dumps(
            {
                "request": "请根据库存生成 JSON 食谱和具体做法",
                "servings": servings,
                "inventory": inventory_context,
            },
            ensure_ascii=False,
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": 1800,
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key.strip()}",
                "Content-Type": "application/json",
                "User-Agent": "SmartFridgeDemo/0.3",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DeepSeekRecipeError("request_failed") from exc

        try:
            content = raw_response["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            document = RecipeDocument.model_validate(json.loads(content))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise DeepSeekRecipeError("invalid_response") from exc

        allowed_names = {str(item["name"]) for item in inventory}
        validated: list[dict[str, Any]] = []
        for recipe in document.recipes:
            canonical_ingredients: list[str] = []
            for ingredient in recipe.ingredients:
                if ingredient in allowed_names:
                    match = ingredient
                else:
                    matches = [name for name in allowed_names if name in ingredient]
                    match = matches[0] if len(matches) == 1 else None
                if match and match not in canonical_ingredients:
                    canonical_ingredients.append(match)
            if not canonical_ingredients:
                continue
            item = recipe.model_dump()
            item["servings"] = servings
            item["ingredients"] = canonical_ingredients
            validated.append(item)

        if not validated:
            raise DeepSeekRecipeError("ingredients_not_in_inventory")
        return validated
