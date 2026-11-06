from __future__ import annotations


def build_expiry_message(product_name: str, days: int) -> str:
    if days < 0:
        return f"{product_name} 已过期，请检查后处理。"
    return f"{product_name} 还有 {days} 天到期，建议优先食用。"

