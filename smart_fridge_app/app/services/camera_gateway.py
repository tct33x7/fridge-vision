"""Fault-tolerant client for the independent camera daemon API."""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import re
from collections.abc import Iterator
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CAPTURE_ID = re.compile(r"^[A-Za-z0-9-]{8,128}$")
LOG = logging.getLogger("smart_fridge.camera_gateway")


class CameraGatewayError(RuntimeError):
    pass


class CameraUnavailable(CameraGatewayError):
    pass


class CameraNotFound(CameraGatewayError):
    pass


class CameraConflict(CameraGatewayError):
    pass


class CameraGateway:
    def __init__(self, base_url: str, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def validate_capture_id(capture_id: str) -> str:
        if not CAPTURE_ID.fullmatch(capture_id):
            raise CameraNotFound("capture id is invalid")
        return capture_id

    def _request_json(self, path: str, method: str = "GET") -> dict[str, Any]:
        request = Request(self.base_url + path, method=method)
        request.add_header("Accept", "application/json")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(2_000_001)
        except HTTPError as error:
            if error.code == 404:
                raise CameraNotFound("camera record does not exist") from error
            try:
                payload = json.loads(error.read(100_000).decode("utf-8"))
                message = str(payload.get("error") or error.reason)
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                message = str(error.reason)
            if error.code == 409:
                raise CameraConflict(message) from error
            raise CameraUnavailable(message) from error
        except (URLError, TimeoutError, OSError) as error:
            LOG.debug("Camera JSON request failed: %s", error)
            raise CameraUnavailable("摄像头服务未连接") from error
        if len(body) > 2_000_000:
            raise CameraUnavailable("camera service returned an oversized JSON response")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CameraUnavailable("camera service returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise CameraUnavailable("camera service returned an unexpected response")
        return payload

    @staticmethod
    def _rewrite_record(record: dict[str, Any]) -> dict[str, Any]:
        item = dict(record)
        capture_id = str(item.get("id") or "")
        if not CAPTURE_ID.fullmatch(capture_id):
            raise CameraUnavailable("camera service returned an invalid capture id")
        item["image_url"] = f"/api/v1/camera/captures/{capture_id}/image"
        item["record_url"] = f"/api/v1/camera/captures/{capture_id}"
        item.pop("image_path", None)
        item.pop("sidecar_path", None)
        return item

    def status(self) -> dict[str, Any]:
        try:
            payload = self._request_json("/api/v1/status")
        except CameraGatewayError as error:
            return {
                "connected": False,
                "camera": {"ready": False, "error": str(error)},
                "gpio": {"available": False, "message": "camera service offline"},
                "recognition": {"enabled": False, "available": False},
                "counts": {"total": 0},
                "last_capture": None,
            }
        payload["connected"] = True
        latest = payload.get("last_capture")
        if isinstance(latest, dict):
            payload["last_capture"] = self._rewrite_record(latest)
        return payload

    def capture(self) -> dict[str, Any]:
        return self._rewrite_record(self._request_json("/api/v1/capture", method="POST"))

    def list_captures(self, *, limit: int = 24, offset: int = 0) -> dict[str, Any]:
        payload = self._request_json(
            f"/api/v1/captures?limit={int(limit)}&offset={int(offset)}"
        )
        items = payload.get("items")
        if isinstance(items, list):
            payload["items"] = [
                self._rewrite_record(item) for item in items if isinstance(item, dict)
            ]
        return payload

    def get_capture(self, capture_id: str) -> dict[str, Any]:
        capture_id = self.validate_capture_id(capture_id)
        item = self._rewrite_record(
            self._request_json(f"/api/v1/captures/{capture_id}")
        )
        if item["id"] != capture_id:
            raise CameraUnavailable("camera service returned a mismatched capture id")
        return item

    def retry(self, capture_id: str) -> dict[str, Any]:
        capture_id = self.validate_capture_id(capture_id)
        item = self._rewrite_record(
            self._request_json(f"/api/v1/captures/{capture_id}/retry", method="POST")
        )
        if item["id"] != capture_id:
            raise CameraUnavailable("camera service returned a mismatched capture id")
        return item

    def verify_capture(self, capture_id: str) -> dict[str, Any]:
        """Confirm that a camera record still has the JPEG it claims to describe."""

        item = self.get_capture(capture_id)
        body, _content_type = self.image(capture_id)
        actual = hashlib.sha256(body).hexdigest()
        expected_value = item.get("image_sha256")
        if expected_value:
            expected = str(expected_value).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise CameraUnavailable("camera record contains an invalid image checksum")
            if not hmac.compare_digest(expected, actual):
                raise CameraUnavailable("capture image checksum does not match its record")
        item["image_sha256"] = actual
        item["image_verified"] = True
        return item

    def image(self, capture_id: str) -> tuple[bytes, str]:
        capture_id = self.validate_capture_id(capture_id)
        request = Request(self.base_url + f"/captures/{capture_id}.jpg", method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                body = response.read(25_000_001)
        except HTTPError as error:
            if error.code == 404:
                raise CameraNotFound("capture image does not exist") from error
            raise CameraUnavailable(f"camera image request failed: {error.reason}") from error
        except (URLError, TimeoutError, OSError) as error:
            LOG.debug("Camera image request failed: %s", error)
            raise CameraUnavailable("摄像头服务未连接") from error
        if len(body) > 25_000_000:
            raise CameraUnavailable("capture image exceeds the 25 MB safety limit")
        if content_type != "image/jpeg":
            raise CameraUnavailable("camera service returned a non-JPEG image")
        return body, content_type

    def open_stream(self) -> BinaryIO:
        request = Request(self.base_url + "/stream.mjpg", method="GET")
        try:
            return urlopen(request, timeout=max(5.0, self.timeout_seconds))
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            LOG.debug("Camera preview request failed: %s", error)
            raise CameraUnavailable("摄像头实时画面暂不可用") from error

    @staticmethod
    def iter_stream(response: BinaryIO) -> Iterator[bytes]:
        try:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    return
                yield chunk
        finally:
            response.close()
