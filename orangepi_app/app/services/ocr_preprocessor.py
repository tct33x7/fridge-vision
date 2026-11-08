"""OCR 图像预处理增强模块
============================
针对不同识别场景（小票、日期、通用文本）提供差异化的图像预处理管线，
提升 OCR 识别准确率。

预处理流程：
    原图 → EXIF 矫正 → 缩放 → 灰度 → 去噪 → 倾斜矫正
         → 对比度增强 → 二值化 → 边框裁剪 → 输出

预处理策略：
    receipt（小票）: 高分辨率 + 强对比 + 倾斜矫正 + 二值化
    expiry （日期）: 局部增强 + 自适应阈值
    general（通用）: 均衡增强，保留颜色信息
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.config import PROCESSED_DIR

log = logging.getLogger("ocr_preprocessor")


class OCRPreprocessor:
    """OCR 图像预处理器，支持多种预处理策略。"""

    # 不同场景的目标最小宽度（像素）
    MIN_WIDTH = {
        "receipt": 1600,   # 小票需要高分辨率才能看清小字
        "expiry": 1200,    # 日期通常印在较小区域
        "general": 1000,   # 通用场景
    }

    def preprocess(
        self,
        image_path: Path,
        file_id: str,
        profile: str = "general",
    ) -> Path:
        """预处理图像并保存到 PROCESSED_DIR。

        Args:
            image_path: 原始图像路径
            file_id: 文件唯一标识
            profile: 预处理策略 (receipt / expiry / general)

        Returns:
            处理后图像路径
        """
        processed_path = PROCESSED_DIR / f"{file_id}_{profile}.jpg"

        with Image.open(image_path) as source:
            # Step 1: EXIF 方向矫正
            image = ImageOps.exif_transpose(source)

        # 转 numpy (BGR) 供 OpenCV 处理
        rgb = np.array(image.convert("RGB"))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        # Step 2: 缩放（如果分辨率不足）
        min_width = self.MIN_WIDTH.get(profile, 1000)
        bgr = self._upscale(bgr, min_width)

        # Step 3: 灰度转换
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        # Step 4: 去噪
        gray = self._denoise(gray, profile)

        # Step 5: 倾斜矫正（小票和文档类特别重要）
        if profile in ("receipt", "general"):
            gray = self._deskew(gray)

        # Step 6: 对比度增强
        gray = self._enhance_contrast(gray, profile)

        # Step 7: 二值化
        if profile == "receipt":
            gray = self._binarize(gray, method="adaptive")
        elif profile == "expiry":
            gray = self._binarize(gray, method="otsu")
        # general: 保留灰度，不做二值化

        # Step 8: 边框裁剪（去除多余白边/黑边）
        gray = self._crop_borders(gray)

        # 保存
        cv2.imwrite(str(processed_path), gray, [cv2.IMWRITE_JPEG_QUALITY, 95])
        log.info("预处理完成: %s -> %s (profile=%s)", image_path.name, processed_path.name, profile)
        return processed_path

    # ──────────── 各步骤实现 ────────────

    @staticmethod
    def _upscale(image: np.ndarray, min_width: int) -> np.ndarray:
        """如果图像宽度不足，按比例放大。"""
        h, w = image.shape[:2]
        if w < min_width:
            ratio = min_width / w
            new_size = (min_width, int(h * ratio))
            image = cv2.resize(image, new_size, interpolation=cv2.INTER_LANCZOS4)
            log.debug("缩放: %dx%d -> %dx%d", w, h, *new_size)
        return image

    @staticmethod
    def _denoise(gray: np.ndarray, profile: str) -> np.ndarray:
        """去噪：小票用双边滤波保留边缘，其他用快速均值去噪。"""
        if profile == "receipt":
            # 双边滤波：去噪同时保留文字边缘
            return cv2.bilateralFilter(gray, d=5, sigmaColor=30, sigmaSpace=30)
        else:
            # 非局部均值去噪（OpenCV 快速版）
            return cv2.fastNlMeansDenoising(gray, h=10)

    @staticmethod
    def _deskew(gray: np.ndarray) -> np.ndarray:
        """倾斜矫正：检测文本行角度并旋转回正。"""
        # 二值化用于检测角度
        binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        # 膨胀使文字行连通
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 5))
        dilated = cv2.dilate(binary, kernel, iterations=1)
        # 寻找最小外接矩形
        coords = np.column_stack(np.where(dilated > 0))
        if len(coords) < 50:
            return gray
        angle = cv2.minAreaRect(coords)[-1]
        # 矫正角度（minAreaRect 返回 -90 到 0）
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 0.5 or abs(angle) > 45:
            return gray
        # 旋转
        h, w = gray.shape[:2]
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_REPLICATE)
        log.debug("倾斜矫正: %.2f°", angle)
        return rotated

    @staticmethod
    def _enhance_contrast(gray: np.ndarray, profile: str) -> np.ndarray:
        """对比度增强：自动对比度 + CLAHE 局部均衡化。"""
        # 自动对比度（截掉 1% 极端像素）
        gray = cv2.normalize(gray, None, alpha=0, beta=255,
                             norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U)
        # CLAHE 局部自适应直方图均衡
        clip_limit = 3.0 if profile == "receipt" else 2.0
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        return gray

    @staticmethod
    def _binarize(gray: np.ndarray, method: str = "adaptive") -> np.ndarray:
        """二值化：自适应阈值或 Otsu 全局阈值。"""
        if method == "adaptive":
            # 自适应阈值：适合光照不均的小票
            return cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, blockSize=31, C=15,
            )
        elif method == "otsu":
            # Otsu 全局阈值：适合光照均匀的包装日期
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary
        return gray

    @staticmethod
    def _crop_borders(gray: np.ndarray) -> np.ndarray:
        """裁剪多余边框：检测内容区域并裁剪到有效范围。"""
        # 检测非空白区域
        if len(gray.shape) == 2:
            _, binary = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)
        else:
            binary = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        coords = np.column_stack(np.where(binary > 0))
        if len(coords) < 100:
            return gray
        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        # 留 10px 边距
        pad = 10
        y_min = max(0, y_min - pad)
        x_min = max(0, x_min - pad)
        y_max = min(gray.shape[0], y_max + pad)
        x_max = min(gray.shape[1], x_max + pad)
        return gray[y_min:y_max, x_min:x_max]
