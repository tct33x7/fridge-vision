from __future__ import annotations

import os


class RecipeAIClient:
    """Reserved Coze adapter; DeepSeek is implemented in deepseek_client.py."""

    def configured(self) -> bool:
        return bool(os.getenv("COZE_API_TOKEN"))
