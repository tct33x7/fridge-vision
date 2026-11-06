from __future__ import annotations

import ast
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from app.config import BASE_DIR


DEFAULT_MODEL_PATH = BASE_DIR / "yolo" / "food_best.onnx"
DEFAULT_CLASSES_PATH = BASE_DIR / "yolo" / "classes.txt"


def _float_setting(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _configured_path(name: str, default: Path) -> Path:
    configured = os.getenv(name)
    return Path(configured).expanduser() if configured else default


@lru_cache(maxsize=4)
def _create_session(model_path: str):
    try:
        import onnxruntime as ort
    except ImportError as exc:  # pragma: no cover - exercised only in incomplete installs
        raise RuntimeError("未安装 onnxruntime，请重新执行 pip install -r requirements.txt") from exc

    return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


def _load_class_names(classes_path: Path, session: Any) -> list[str]:
    if classes_path.exists():
        names = [line.strip() for line in classes_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if names:
            return names

    serialized_names = session.get_modelmeta().custom_metadata_map.get("names", "")
    if serialized_names:
        try:
            parsed = ast.literal_eval(serialized_names)
            if isinstance(parsed, dict):
                return [str(parsed[key]) for key in sorted(parsed, key=lambda value: int(value))]
            if isinstance(parsed, (list, tuple)):
                return [str(value) for value in parsed]
        except (SyntaxError, ValueError, TypeError):
            pass
    raise RuntimeError(f"无法读取 YOLO 类别文件：{classes_path}")


def _input_size(session: Any) -> tuple[int, int]:
    shape = session.get_inputs()[0].shape
    if len(shape) != 4:
        raise RuntimeError(f"YOLO 输入张量应为 NCHW 四维格式，实际为：{shape}")
    height = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 640
    width = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 640
    return int(width), int(height)


def _letterbox(image_path: Path, size: tuple[int, int]) -> tuple[np.ndarray, float, int, int, tuple[int, int]]:
    target_width, target_height = size
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        original_width, original_height = image.size
        scale = min(target_width / original_width, target_height / original_height)
        resized_width = max(1, round(original_width * scale))
        resized_height = max(1, round(original_height * scale))
        resized = image.resize((resized_width, resized_height), Image.Resampling.BILINEAR)

    pad_left = (target_width - resized_width) // 2
    pad_top = (target_height - resized_height) // 2
    canvas = Image.new("RGB", size, (114, 114, 114))
    canvas.paste(resized, (pad_left, pad_top))
    array = np.asarray(canvas, dtype=np.float32) / 255.0
    tensor = np.ascontiguousarray(array.transpose(2, 0, 1)[None])
    return tensor, scale, pad_left, pad_top, (original_width, original_height)


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    if not len(boxes):
        return []
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break
        remaining = order[1:]
        intersection_width = np.maximum(0.0, np.minimum(x2[current], x2[remaining]) - np.maximum(x1[current], x1[remaining]))
        intersection_height = np.maximum(0.0, np.minimum(y2[current], y2[remaining]) - np.maximum(y1[current], y1[remaining]))
        intersection = intersection_width * intersection_height
        union = areas[current] + areas[remaining] - intersection
        iou = np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
        order = remaining[iou <= iou_threshold]
    return keep


def _decode_output(
    output: np.ndarray,
    class_names: list[str],
    input_size: tuple[int, int],
    original_size: tuple[int, int],
    scale: float,
    pad_left: int,
    pad_top: int,
    confidence_threshold: float,
    iou_threshold: float,
) -> list[dict[str, Any]]:
    predictions = np.asarray(output).squeeze()
    if predictions.ndim != 2:
        raise RuntimeError(f"不支持的 YOLO 输出形状：{np.asarray(output).shape}")
    if predictions.shape[0] < predictions.shape[1] and predictions.shape[0] <= 512:
        predictions = predictions.T

    class_count = len(class_names)
    column_count = predictions.shape[1]
    if column_count == 4 + class_count:
        class_scores = predictions[:, 4 : 4 + class_count]
    elif column_count >= 5 + class_count:
        class_scores = predictions[:, 5 : 5 + class_count] * predictions[:, 4:5]
    else:
        raise RuntimeError(
            f"YOLO 输出列数 {column_count} 与类别数 {class_count} 不匹配；"
            "请确认 classes.txt 与 food_best.onnx 来自同一次导出"
        )

    class_ids = class_scores.argmax(axis=1)
    scores = class_scores[np.arange(len(class_scores)), class_ids]
    selected = scores >= confidence_threshold
    if not np.any(selected):
        return []

    xywh = predictions[selected, :4].astype(np.float32, copy=True)
    scores = scores[selected].astype(np.float32, copy=False)
    class_ids = class_ids[selected]
    input_width, input_height = input_size
    if float(np.max(np.abs(xywh))) <= 2.0:
        xywh[:, [0, 2]] *= input_width
        xywh[:, [1, 3]] *= input_height

    boxes = np.empty_like(xywh)
    boxes[:, 0] = xywh[:, 0] - xywh[:, 2] / 2
    boxes[:, 1] = xywh[:, 1] - xywh[:, 3] / 2
    boxes[:, 2] = xywh[:, 0] + xywh[:, 2] / 2
    boxes[:, 3] = xywh[:, 1] + xywh[:, 3] / 2
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad_left) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad_top) / scale
    original_width, original_height = original_size
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, original_width)
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, original_height)

    kept: list[int] = []
    for class_id in np.unique(class_ids):
        class_indexes = np.flatnonzero(class_ids == class_id)
        kept.extend(class_indexes[index] for index in _nms(boxes[class_indexes], scores[class_indexes], iou_threshold))
    kept.sort(key=lambda index: float(scores[index]), reverse=True)

    detections: list[dict[str, Any]] = []
    for index in kept:
        x1, y1, x2, y2 = boxes[index]
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append(
            {
                "label": class_names[int(class_ids[index])],
                "class_id": int(class_ids[index]),
                "confidence": round(float(scores[index]), 4),
                "bbox": [round(float(value), 1) for value in (x1, y1, x2, y2)],
            }
        )
    return detections


def detect_food_image(image_path: str | Path) -> dict[str, Any]:
    model_path = _configured_path("SMART_FRIDGE_YOLO_MODEL", DEFAULT_MODEL_PATH)
    classes_path = _configured_path("SMART_FRIDGE_YOLO_CLASSES", DEFAULT_CLASSES_PATH)
    confidence_threshold = min(max(_float_setting("SMART_FRIDGE_YOLO_CONFIDENCE", 0.25), 0.0), 1.0)
    iou_threshold = min(max(_float_setting("SMART_FRIDGE_YOLO_IOU", 0.45), 0.0), 1.0)

    if not model_path.is_file():
        return {"status": "model_missing", "detections": [], "error": f"YOLO 模型不存在：{model_path}"}
    try:
        session = _create_session(str(model_path.resolve()))
        class_names = _load_class_names(classes_path, session)
        size = _input_size(session)
        tensor, scale, pad_left, pad_top, original_size = _letterbox(Path(image_path), size)
        output = session.run(None, {session.get_inputs()[0].name: tensor})[0]
        detections = _decode_output(
            output,
            class_names,
            size,
            original_size,
            scale,
            pad_left,
            pad_top,
            confidence_threshold,
            iou_threshold,
        )
        return {
            "status": "onnxruntime-yolo11",
            "detections": detections,
            "model": model_path.name,
            "input_size": list(size),
            "confidence_threshold": confidence_threshold,
        }
    except Exception as exc:
        return {"status": "model_error", "detections": [], "error": str(exc)}
