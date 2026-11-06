from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.database.connection import database
from app.database.repositories import inventory_repository
from app.services.deepseek_client import DeepSeekRecipeClient, DeepSeekRecipeError
from app.services.recipe_service import recommend_recipes


router = APIRouter(prefix="/api/recipes", tags=["recipes"])
logger = logging.getLogger(__name__)


@router.get("/today")
def today_recipe(servings: int = Query(default=2, ge=1, le=12)) -> dict[str, object]:
    with database() as connection:
        batches = inventory_repository.list_batches(connection)

    client = DeepSeekRecipeClient()
    generated_by = "local-rules"
    fallback_reason: str | None = None
    recipes = recommend_recipes(batches, servings)
    if batches and client.configured():
        try:
            recipes = client.generate(batches, servings)
            generated_by = f"deepseek:{client.model}"
        except DeepSeekRecipeError as exc:
            fallback_reason = str(exc)
            logger.warning("DeepSeek recipe generation fell back to local rules: %s", fallback_reason)
    elif not client.configured():
        fallback_reason = "missing_api_key"

    return {
        "items": recipes,
        "generated_by": generated_by,
        "inventory_count": len(batches),
        "ai_configured": client.configured(),
        "fallback_reason": fallback_reason,
    }
