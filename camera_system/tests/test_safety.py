from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path


CAMERA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAMERA_ROOT))

from capture_repository import CaptureRepository, sqlite_has_wal_reset_fix  # noqa: E402
from capture_service import CameraStream, CaptureStore  # noqa: E402


class CameraSafetyTest(unittest.TestCase):
    def test_current_frame_rejects_stale_or_failed_camera(self):
        camera = CameraStream("mock", 640, 480, 80, 10)
        with camera._condition:
            camera._jpeg = b"jpeg"
            camera._width = 640
            camera._height = 480
            camera._sequence = 1
            camera._frame_monotonic = time.monotonic() - 10
        with self.assertRaisesRegex(RuntimeError, "过期"):
            camera.current_frame(max_age_seconds=1)

        with camera._condition:
            camera._frame_monotonic = time.monotonic()
            camera._last_error = "camera disconnected"
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            camera.current_frame(max_age_seconds=1)

    def test_status_and_preview_reject_a_stalled_frame(self):
        camera = CameraStream("mock", 640, 480, 80, 10, max_frame_age_seconds=0.01)
        with camera._condition:
            camera._jpeg = b"jpeg"
            camera._width = 640
            camera._height = 480
            camera._sequence = 1
            camera._frame_monotonic = time.monotonic() - 1

        status = camera.status()
        self.assertFalse(status["ready"])
        self.assertRegex(str(status["error"]), "未更新")
        with self.assertRaisesRegex(RuntimeError, "更新超时"):
            camera.frame_after(1, timeout=0.001)

    def test_current_frame_accepts_fresh_healthy_frame(self):
        camera = CameraStream("mock", 640, 480, 80, 10)
        with camera._condition:
            camera._jpeg = b"jpeg"
            camera._width = 640
            camera._height = 480
            camera._sequence = 2
            camera._frame_monotonic = time.monotonic()
        self.assertEqual(camera.current_frame(max_age_seconds=1), (b"jpeg", 640, 480, 2))

    def test_repository_avoids_unfixed_wal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = CaptureRepository(root / "catalog.sqlite3", root / "images")
            with repository._connect() as connection:
                mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            expected = "wal" if sqlite_has_wal_reset_fix() else "delete"
            self.assertEqual(mode, expected)

    def test_wal_fix_version_gate(self):
        self.assertFalse(sqlite_has_wal_reset_fix((3, 50, 6)))
        self.assertTrue(sqlite_has_wal_reset_fix((3, 50, 7)))
        self.assertTrue(sqlite_has_wal_reset_fix((3, 51, 3)))

    def test_database_failure_quarantines_the_saved_jpeg(self):
        class FakeCamera:
            device = "mock"

            @staticmethod
            def current_frame(_max_age):
                return b"jpeg", 640, 480, 1

        class FailedRepository:
            @staticmethod
            def new_capture_id():
                return "11111111-2222-3333-4444-555555555555"

            @staticmethod
            def register_capture(**_values):
                raise sqlite3.OperationalError("simulated database failure")

        with tempfile.TemporaryDirectory() as directory:
            store = CaptureStore(
                Path(directory),
                FakeCamera(),
                FailedRepository(),
                recognition_worker=None,
                recognition_enabled=False,
                max_frame_age_seconds=1,
            )
            with self.assertRaises(sqlite3.OperationalError):
                store.save_current("test")
            quarantined = list((Path(directory) / "quarantine").glob("*.jpg"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_bytes(), b"jpeg")


if __name__ == "__main__":
    unittest.main()
