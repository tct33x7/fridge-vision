"""Same-origin camera facade for status, capture, gallery, images, and MJPEG."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import camera, capture_library
from app.services.camera_gateway import CameraGateway
from app.services.capture_library import CaptureLibrary


router = APIRouter(prefix="/api/v1/camera", tags=["camera"])


@router.get("/status")
def camera_status(gateway: CameraGateway = Depends(camera)) -> dict[str, object]:
    return gateway.status()


@router.post("/capture", status_code=status.HTTP_201_CREATED)
def take_photo(library: CaptureLibrary = Depends(capture_library)) -> dict[str, object]:
    item = library.capture()
    return {key: value for key, value in item.items() if key != "local_relpath"}


@router.get("/captures")
def list_captures(
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    gateway: CameraGateway = Depends(camera),
) -> dict[str, object]:
    return gateway.list_captures(limit=limit, offset=offset)


@router.get("/captures/{capture_id}")
def get_capture(
    capture_id: str, gateway: CameraGateway = Depends(camera)
) -> dict[str, object]:
    return gateway.get_capture(capture_id)


@router.post("/captures/{capture_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_capture(
    capture_id: str, gateway: CameraGateway = Depends(camera)
) -> dict[str, object]:
    return gateway.retry(capture_id)


@router.get("/captures/{capture_id}/image")
def capture_image(
    capture_id: str,
    library: CaptureLibrary = Depends(capture_library),
) -> Response:
    return Response(
        library.image(capture_id),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/stream.mjpg")
def camera_stream(gateway: CameraGateway = Depends(camera)) -> StreamingResponse:
    upstream = gateway.open_stream()
    return StreamingResponse(
        gateway.iter_stream(upstream),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
