"""OCR 统一管线
=================
将预处理 → 引擎识别 → 后处理串联为完整管线，
为小票识别、日期识别和通用 OCR 提供统一的调用入口。

使用方式：
    pipeline = OCRPipeline()
    result = pipeline.run(image_path, file_id="xxx", engine="rapidocr", profile="receipt")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.ocr_engine_manager import OCREngineManager, OCRResult
from app.services.ocr_postprocessor import OCRPostprocessor
from app.services.ocr_preprocessor import OCRPreprocessor

log = logging.getLogger("ocr_pipeline")


class OCRPipeline:
    """OCR 统一管线：预处理 → 识别 → 后处理。"""

    # 单例引擎管理器（所有管线共享）
    _engine_manager: OCREngineManager | None = None
    _preprocessor: OCRPreprocessor | None = None
    _postprocessor: OCRPostprocessor | None = None

    @classmethod
    def _get_engine_manager(cls) -> OCREngineManager:
        if cls._engine_manager is None:
            cls._engine_manager = OCREngineManager()
        return cls._engine_manager

    @classmethod
    def _get_preprocessor(cls) -> OCRPreprocessor:
        if cls._preprocessor is None:
            cls._preprocessor = OCRPreprocessor()
        return cls._preprocessor

    @classmethod
    def _get_postprocessor(cls) -> OCRPostprocessor:
        if cls._postprocessor is None:
            cls._postprocessor = OCRPostprocessor()
        return cls._postprocessor

    def run(
        self,
        image_path: Path,
        file_id: str,
        engine: str = "rapidocr",
        profile: str = "general",
        skip_preprocess: bool = False,
    ) -> dict[str, Any]:
        """执行完整的 OCR 管线。

        Args:
            image_path: 原始图像路径
            file_id: 文件唯一标识
            engine: OCR 引擎 ID
            profile: 预处理/后处理策略 (receipt / expiry / general)
            skip_preprocess: 是否跳过预处理（用于已处理过的图像）

        Returns:
            结构化的 OCR 结果字典
        """
        mgr = self._get_engine_manager()
        pre = self._get_preprocessor()
        post = self._get_postprocessor()

        # Step 1: 预处理
        if skip_preprocess:
            processed_path = image_path
        else:
            processed_path = pre.preprocess(image_path, file_id, profile)

        # Step 2: 引擎识别
        ocr_result = mgr.recognize(engine, processed_path)

        # Step 3: 后处理
        structured = post.process(ocr_result, profile=profile)

        # 补充元信息
        structured["processed_name"] = processed_path.name if processed_path != image_path else None
        structured["engine_id"] = engine
        structured["profile"] = profile

        log.info(
            "OCR 管线完成: engine=%s, profile=%s, lines=%d, elapsed=%.2fs",
            engine, profile, structured.get("line_count", 0), ocr_result.elapsed,
        )
        return structured

    def list_engines(self) -> list[dict[str, Any]]:
        """返回可用引擎列表。"""
        return self._get_engine_manager().list_engines()


# 全局单例
_pipeline = OCRPipeline()


def get_pipeline() -> OCRPipeline:
    """获取全局 OCR 管线实例。"""
    return _pipeline
