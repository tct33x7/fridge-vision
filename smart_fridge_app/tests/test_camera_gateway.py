from __future__ import annotations

import json
import hashlib
import unittest
from unittest.mock import patch

from app.services.camera_gateway import CameraGateway, CameraUnavailable


CAPTURE_ID = "11111111-2222-3333-4444-555555555555"
JPEG = b"\xff\xd8test\xff\xd9"


def record():
    return {
        "id": CAPTURE_ID,
        "captured_at": "2026-08-07T12:00:00+08:00",
        "image_url": f"/captures/{CAPTURE_ID}.jpg",
        "record_url": f"/api/v1/captures/{CAPTURE_ID}",
        "image_path": "/secret/original.jpg",
        "sidecar_path": "/secret/original.json",
        "recognition": {"status": "skipped"},
    }


class FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self.content_type = content_type

    def get_content_type(self) -> str:
        return self.content_type


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.body = body
        self.headers = FakeHeaders(content_type)

    def read(self, _limit: int = -1) -> bytes:
        return self.body

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def fake_urlopen(request, timeout):
    del timeout
    path = request.full_url.removeprefix("http://camera")
    if path == "/api/v1/status":
        payload = {"camera": {"ready": True}, "last_capture": record()}
    elif path.startswith("/api/v1/captures?"):
        payload = {"items": [record()], "count": 1}
    elif path in {
        "/api/v1/capture",
        f"/api/v1/captures/{CAPTURE_ID}",
        f"/api/v1/captures/{CAPTURE_ID}/retry",
    }:
        payload = record()
    elif path == f"/captures/{CAPTURE_ID}.jpg":
        return FakeResponse(JPEG, "image/jpeg")
    else:
        raise AssertionError(f"unexpected fake request: {request.method} {path}")
    return FakeResponse(json.dumps(payload).encode("utf-8"))


class CameraGatewayTest(unittest.TestCase):
    def setUp(self):
        self.gateway = CameraGateway("http://camera")
        self.patcher = patch(
            "app.services.camera_gateway.urlopen", side_effect=fake_urlopen
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_status_and_records_are_rewritten_to_same_origin(self):
        status = self.gateway.status()
        self.assertTrue(status["connected"])
        item = status["last_capture"]
        self.assertEqual(
            item["image_url"], f"/api/v1/camera/captures/{CAPTURE_ID}/image"
        )
        self.assertNotIn("image_path", item)
        self.assertNotIn("sidecar_path", item)

    def test_capture_list_get_retry_and_image(self):
        self.assertEqual(self.gateway.capture()["id"], CAPTURE_ID)
        self.assertEqual(self.gateway.list_captures()["items"][0]["id"], CAPTURE_ID)
        self.assertEqual(self.gateway.get_capture(CAPTURE_ID)["id"], CAPTURE_ID)
        self.assertEqual(self.gateway.retry(CAPTURE_ID)["id"], CAPTURE_ID)
        body, content_type = self.gateway.image(CAPTURE_ID)
        self.assertEqual(body, JPEG)
        self.assertEqual(content_type, "image/jpeg")

    def test_get_rejects_a_mismatched_capture_id(self):
        mismatched = record()
        mismatched["id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch.object(self.gateway, "_request_json", return_value=mismatched):
            with self.assertRaisesRegex(CameraUnavailable, "mismatched"):
                self.gateway.get_capture(CAPTURE_ID)

    def test_verify_capture_checks_the_jpeg_digest(self):
        verified = self.gateway.verify_capture(CAPTURE_ID)
        self.assertTrue(verified["image_verified"])
        self.assertEqual(verified["image_sha256"], hashlib.sha256(JPEG).hexdigest())

        mismatched = record()
        mismatched["image_sha256"] = "0" * 64
        with patch.object(self.gateway, "get_capture", return_value=mismatched):
            with self.assertRaisesRegex(CameraUnavailable, "checksum"):
                self.gateway.verify_capture(CAPTURE_ID)


if __name__ == "__main__":
    unittest.main()
