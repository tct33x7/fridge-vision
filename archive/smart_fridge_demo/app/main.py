from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import camera, inventory, nutrition, products, recipes, reminders, scans, settings, shopping
from app.config import FRONTEND_DIR, UPLOAD_DIR
from app.database.connection import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    camera.start_hardware()
    try:
        yield
    finally:
        camera.stop_hardware()


app = FastAPI(
    title="Smart Fridge · 食光冰箱",
    description="本地优先的食物、条码、小票、日期识别与食品库存 Demo",
    version="0.4.0",
    lifespan=lifespan,
)

for api_router in (
    scans.router,
    products.router,
    inventory.router,
    nutrition.router,
    recipes.router,
    shopping.router,
    reminders.router,
    settings.router,
    camera.router,
):
    app.include_router(api_router)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "src"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(), "version": "0.4.0"}


@app.get("/manifest.json", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "manifest.json")


@app.get("/service-worker.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "service-worker.js", media_type="application/javascript")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
