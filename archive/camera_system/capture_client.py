"""Dependency-free Python client for the camera system's versioned HTTP API."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CaptureApiError(RuntimeError):
    pass


class CaptureClient:
    def __init__(self, base_url: str, timeout: float = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, method: str = "GET") -> dict[str, Any]:
        request = Request(self.base_url + path, method=method)
        request.add_header("Accept", "application/json")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
                message = payload.get("error", str(error))
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = str(error)
            raise CaptureApiError(message) from error

    def status(self) -> dict[str, Any]:
        return self._request("/api/v1/status")

    def capture(self) -> dict[str, Any]:
        """Take a photo; returned recognition status is normally pending."""
        return self._request("/api/v1/capture", method="POST")

    def latest(self) -> dict[str, Any]:
        return self._request("/api/v1/latest")

    def get(self, capture_id: str) -> dict[str, Any]:
        return self._request(f"/api/v1/captures/{capture_id}")

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        document_type: str | None = None,
    ) -> dict[str, Any]:
        query: dict[str, object] = {"limit": limit, "offset": offset}
        if status:
            query["status"] = status
        if document_type:
            query["type"] = document_type
        return self._request("/api/v1/captures?" + urlencode(query))

    def retry(self, capture_id: str) -> dict[str, Any]:
        return self._request(f"/api/v1/captures/{capture_id}/retry", method="POST")

    def wait_until_recognized(
        self,
        capture_id: str,
        timeout: float = 60,
        poll_interval: float = 0.5,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.get(capture_id)
            recognition = record.get("recognition", {})
            if recognition.get("status") in {"completed", "failed", "skipped"}:
                return record
            time.sleep(poll_interval)
        raise TimeoutError(f"等待识别超时：{capture_id}")
