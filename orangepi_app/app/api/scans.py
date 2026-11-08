from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import ALLOWED_IMAGE_TYPES, BASE_DIR, MAX_FILE_SIZE, PROCESSED_DIR, UPLOAD_DIR
from app.database.connection import database
from app.database.repositories import inventory_repository, product_repository, scan_repository
from app.schemas.scan import ExpiryConfirmRequest, ReceiptConfirmRequest
from app.services.barcode_service import render_demo_barcode
from app.services.food_classifier import render_demo_food_photo
from app.services.product_matcher import enrich_product
from app.services.scan_router import ScanRouter


router = APIRouter(prefix="/api/scans", tags=["scans"])
scan_router = ScanRouter()

# 支持的识别类型
SCAN_TYPES = {"food", "barcode", "receipt", "expiry", "ocr"}


def _validate_date(value: str | None, label: str) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{label}必须是 YYYY-MM-DD") from exc


def _save_and_analyze(
    *,
    content: bytes,
    original_name: str,
    content_type: str,
    scan_type: str,
    batch_id: int | None,
    engine: str = "rapidocr",
) -> dict[str, Any]:
    if scan_type not in SCAN_TYPES:
        raise HTTPException(status_code=422, detail="识别类型必须是 food、barcode、receipt、expiry 或 ocr")
    suffix_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    file_id = uuid.uuid4().hex
    saved_name = file_id + suffix_map.get(content_type, Path(original_name).suffix.lower() or ".jpg")
    image_path = UPLOAD_DIR / saved_name
    image_path.write_bytes(content)
    try:
        with Image.open(image_path) as image:
            image.verify()
        result = scan_router.analyze(scan_type, image_path, original_name, file_id, engine=engine)
    except (UnidentifiedImageError, OSError) as exc:
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传文件不是有效图片") from exc
    except Exception as exc:
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"识别处理失败：{exc}") from exc

    with database() as connection:
        if batch_id is not None and inventory_repository.get_batch(connection, batch_id) is None:
            image_path.unlink(missing_ok=True)
            processed_name = result.get("processed_name")
            if processed_name:
                (PROCESSED_DIR / processed_name).unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="库存批次不存在")
        return scan_repository.create_scan(
            connection,
            {
                "file_id": file_id,
                "scan_type": scan_type,
                "original_name": original_name,
                "saved_name": saved_name,
                "processed_name": result.get("processed_name"),
                "content_type": content_type,
                "size_bytes": len(content),
                "status": "pending_confirmation",
                "engine": result.get("engine", engine),
                "batch_id": batch_id,
                "result": result,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            },
        )


@router.get("/engines")
def list_engines() -> dict[str, Any]:
    """返回所有可用 OCR 引擎列表。"""
    return {"engines": scan_router.list_engines()}


@router.post("")
async def create_scan(
    file: Annotated[UploadFile, File()],
    scan_type: Annotated[str, Form()] = "receipt",
    batch_id: Annotated[int | None, Form()] = None,
    engine: Annotated[str, Form()] = "rapidocr",
) -> dict[str, Any]:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG、WEBP 图片")
    content = await file.read(MAX_FILE_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="图片不能超过 15 MB")
    return _save_and_analyze(
        content=content,
        original_name=file.filename or "unnamed.jpg",
        content_type=file.content_type,
        scan_type=scan_type,
        batch_id=batch_id,
        engine=engine,
    )


@router.post("/demo-receipt")
def create_demo_receipt_scan() -> dict[str, Any]:
    fixture = BASE_DIR / "receipt.jpg"
    if not fixture.exists():
        raise HTTPException(status_code=404, detail="示例小票 receipt.jpg 不存在")
    return _save_and_analyze(
        content=fixture.read_bytes(),
        original_name="receipt.jpg",
        content_type="image/jpeg",
        scan_type="receipt",
        batch_id=None,
    )


@router.post("/demo-barcode")
def create_demo_barcode_scan() -> dict[str, Any]:
    return _save_and_analyze(
        content=render_demo_barcode(),
        original_name="demo-barcode.png",
        content_type="image/png",
        scan_type="barcode",
        batch_id=None,
    )


@router.post("/demo-food")
def create_demo_food_scan() -> dict[str, Any]:
    return _save_and_analyze(
        content=render_demo_food_photo(),
        original_name="demo-food.png",
        content_type="image/png",
        scan_type="food",
        batch_id=None,
    )


@router.get("")
def list_scans(limit: int = 30) -> dict[str, Any]:
    with database() as connection:
        return {"items": scan_repository.list_scans(connection, limit)}


@router.get("/{scan_id}")
def get_scan(scan_id: int) -> dict[str, Any]:
    with database() as connection:
        scan = scan_repository.get_scan(connection, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="识别记录不存在")
    return scan


@router.post("/{scan_id}/confirm-receipt")
def confirm_receipt(scan_id: int, payload: ReceiptConfirmRequest) -> dict[str, Any]:
    purchase_date = _validate_date(payload.purchase_date, "购买日期")
    created_batches: list[dict[str, Any]] = []
    with database() as connection:
        scan = scan_repository.get_scan(connection, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="识别记录不存在")
        if scan["scan_type"] != "receipt":
            raise HTTPException(status_code=409, detail="该记录不是小票识别")
        if scan["status"] == "confirmed":
            raise HTTPException(status_code=409, detail="该小票已经确认入库")

        for item in payload.items:
            data = enrich_product(item.model_dump())
            data["source"] = "receipt_ocr"
            data["default_unit"] = item.unit
            product = product_repository.get_or_create(connection, data)
            created_batches.append(
                inventory_repository.create_batch(
                    connection,
                    product_id=product["id"],
                    quantity=item.quantity,
                    unit=item.unit,
                    purchase_date=purchase_date,
                    expiry_date=_validate_date(item.expiry_date, f"{item.name} 到期日"),
                    unit_price=item.unit_price,
                    source_scan_id=scan_id,
                )
            )
        scan_repository.confirm_scan(connection, scan_id)
    return {"confirmed": True, "scan_id": scan_id, "created_count": len(created_batches), "batches": created_batches}


@router.post("/{scan_id}/confirm-products")
def confirm_products(scan_id: int, payload: ReceiptConfirmRequest) -> dict[str, Any]:
    """Confirm product candidates produced by a barcode or food-photo scan."""
    purchase_date = _validate_date(payload.purchase_date, "入库日期") or date.today().isoformat()
    created_batches: list[dict[str, Any]] = []
    with database() as connection:
        scan = scan_repository.get_scan(connection, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="识别记录不存在")
        if scan["scan_type"] not in {"barcode", "food"}:
            raise HTTPException(status_code=409, detail="该记录不是条形码或食物照片识别")
        if scan["status"] == "confirmed":
            raise HTTPException(status_code=409, detail="该识别结果已经确认入库")

        for item in payload.items:
            data = enrich_product(item.model_dump())
            data["source"] = f"{scan['scan_type']}_scan"
            data["default_unit"] = item.unit
            product = product_repository.get_or_create(connection, data)
            created_batches.append(
                inventory_repository.create_batch(
                    connection,
                    product_id=product["id"],
                    quantity=item.quantity,
                    unit=item.unit,
                    purchase_date=purchase_date,
                    expiry_date=_validate_date(item.expiry_date, f"{item.name} 到期日"),
                    unit_price=item.unit_price,
                    source_scan_id=scan_id,
                )
            )
        scan_repository.confirm_scan(connection, scan_id)
    return {"confirmed": True, "scan_id": scan_id, "created_count": len(created_batches), "batches": created_batches}


@router.post("/{scan_id}/confirm-expiry")
def confirm_expiry(scan_id: int, payload: ExpiryConfirmRequest) -> dict[str, Any]:
    with database() as connection:
        scan = scan_repository.get_scan(connection, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="识别记录不存在")
        if scan["scan_type"] != "expiry":
            raise HTTPException(status_code=409, detail="该记录不是日期识别")
        if scan["status"] == "confirmed":
            raise HTTPException(status_code=409, detail="该日期识别已经确认")
        batch = inventory_repository.update_expiry(
            connection,
            payload.batch_id,
            production_date=_validate_date(payload.production_date, "生产日期"),
            expiry_date=_validate_date(payload.expiry_date, "到期日期"),
            best_before_date=_validate_date(payload.best_before_date, "最佳食用期"),
            shelf_life_days=payload.shelf_life_days,
        )
        if not batch:
            raise HTTPException(status_code=404, detail="库存批次不存在")
        scan_repository.confirm_scan(connection, scan_id)
    return {"confirmed": True, "scan_id": scan_id, "batch": batch}


@router.delete("/{scan_id}")
def delete_scan(scan_id: int) -> dict[str, Any]:
    with database() as connection:
        scan = scan_repository.get_scan(connection, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="识别记录不存在")
        referenced = connection.execute(
            "SELECT 1 FROM inventory_batches WHERE source_scan_id = ? LIMIT 1", (scan_id,)
        ).fetchone()
        if referenced:
            raise HTTPException(status_code=409, detail="已入库的小票记录需要保留审计链路")
        scan_repository.delete_scan(connection, scan_id)
    (UPLOAD_DIR / scan["saved_name"]).unlink(missing_ok=True)
    if scan.get("processed_name"):
        (PROCESSED_DIR / scan["processed_name"]).unlink(missing_ok=True)
    return {"deleted": True, "id": scan_id}
