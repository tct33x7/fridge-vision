"""可选：把关键帧发给多模态大模型，确认食品名字和数量。

走 OpenAI 兼容的 chat/completions 接口，所以通义千问（百炼）、OpenAI、以及任何兼容网关都能用。
环境变量：
    VLM_API_KEY    必填
    VLM_BASE_URL   默认 https://dashscope.aliyuncs.com/compatible-mode/v1  （通义千问）
    VLM_MODEL      默认 qwen-vl-plus
"""
from __future__ import annotations

import base64
import json
import os
import re

import cv2
import httpx
import numpy as np

PROMPT = (
    "这是冰箱门口摄像头抓到的一件手里拿着的东西的截图。请判断它是什么食品或饮品。"
    '只输出一行 JSON，不要其他文字：{"name": "中文名", "category": "蔬菜/水果/肉类/乳制品/饮料/调味品/熟食/其他", '
    '"count": 数量整数, "confidence": 0到1的小数}。看不清就 name 填 "unknown"。'
)


class VisionNamer:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls) -> "VisionNamer":
        key = os.getenv("VLM_API_KEY")
        if not key:
            raise RuntimeError("--vlm 需要环境变量 VLM_API_KEY")
        return cls(
            api_key=key,
            base_url=os.getenv("VLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            model=os.getenv("VLM_MODEL", "qwen-vl-plus"),
        )

    def name_item(self, crop_bgr: np.ndarray) -> dict:
        ok, buf = cv2.imencode(".jpg", crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError("关键帧编码失败")
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            "temperature": 0,
        }
        resp = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {"name": "unknown", "raw": text[:200]}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"name": "unknown", "raw": text[:200]}
