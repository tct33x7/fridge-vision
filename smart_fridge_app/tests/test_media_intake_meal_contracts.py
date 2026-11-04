from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.database.connection import Database
from app.api.intake import capture_for_session
from app.repositories.inventory import ConflictError, InventoryRepository
from app.services.camera_gateway import CameraUnavailable
from app.services.capture_library import CaptureLibrary
from app.services.media_store import MediaStore, MediaStoreError
from app.tasks.backup import create_bundle


JPEG_A = b"\xff\xd8smart-fridge-capture-a\xff\xd9"
JPEG_B = b"\xff\xd8smart-fridge-capture-b\xff\xd9"
JPEG_C = b"\xff\xd8smart-fridge-capture-c\xff\xd9"


def capture_record(capture_id: str, body: bytes) -> dict[str, object]:
    return {
        "id": capture_id,
        "captured_at": "2026-08-07T12:00:00+08:00",
        "trigger": "test",
        "image_sha256": hashlib.sha256(body).hexdigest(),
        "mime_type": "image/jpeg",
        "width": 640,
        "height": 480,
        "bytes": len(body),
        "camera_device": "fake-camera",
        "recognition": {"status": "skipped"},
    }


class FakeCameraGateway:
    def __init__(self, captures: list[tuple[dict[str, object], bytes]]) -> None:
        self.records = {str(record["id"]): dict(record) for record, _body in captures}
        self.bodies = {str(record["id"]): body for record, body in captures}
        self.capture_order = [str(record["id"]) for record, _body in captures]
        self.online = True
        self.image_calls = 0
        self.metadata_calls = 0

    def _require_online(self) -> None:
        if not self.online:
            raise CameraUnavailable("fake camera is offline")

    def capture(self) -> dict[str, object]:
        self._require_online()
        capture_id = self.capture_order[0]
        return dict(self.records[capture_id])

    def get_capture(self, capture_id: str) -> dict[str, object]:
        self._require_online()
        self.metadata_calls += 1
        return dict(self.records[capture_id])

    def image(self, capture_id: str) -> tuple[bytes, str]:
        self._require_online()
        self.image_calls += 1
        return self.bodies[capture_id], "image/jpeg"


class MediaIntakeMealContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = Database(self.root / "smart_fridge.sqlite3")
        self.database.initialize()
        self.repository = InventoryRepository(self.database)
        self.media_root = self.root / "media"
        self.media_store = MediaStore(self.media_root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def library_for(
        self, captures: list[tuple[dict[str, object], bytes]]
    ) -> tuple[CaptureLibrary, FakeCameraGateway]:
        gateway = FakeCameraGateway(captures)
        return (
            CaptureLibrary(gateway, self.media_store, self.repository),
            gateway,
        )

    def create_lot(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "name": "番茄",
            "category": "vegetable",
            "barcode": None,
            "quantity": 4.0,
            "unit": "piece",
            "location_id": "fridge",
            "purchased_on": "2026-08-07",
            "expires_on": "2026-08-10",
            "note": "",
            "source_capture_id": None,
            "intake_session_id": None,
            "primary_flavor": None,
            "nutrition": None,
        }
        values.update(overrides)
        return self.repository.create_lot(**values)  # type: ignore[arg-type]

    def test_capture_is_persisted_with_sha_and_history_remains_readable_offline(
        self,
    ) -> None:
        capture_id = "11111111-2222-3333-4444-555555555555"
        record = capture_record(capture_id, JPEG_A)
        library, gateway = self.library_for([(record, JPEG_A)])

        imported = library.capture()

        expected_digest = hashlib.sha256(JPEG_A).hexdigest()
        self.assertEqual(imported["sha256"], expected_digest)
        self.assertEqual(imported["image_url"], f"/api/v1/media/{capture_id}/image")
        relative_path = str(imported["local_relpath"])
        stored_path = self.media_root / relative_path
        self.assertTrue(stored_path.is_file())
        self.assertEqual(stored_path.read_bytes(), JPEG_A)
        self.assertEqual(gateway.image_calls, 1)

        # Simulate the camera daemon disappearing after an application restart.
        gateway.online = False
        restarted_library = CaptureLibrary(
            gateway,
            MediaStore(self.media_root),
            InventoryRepository(Database(self.root / "smart_fridge.sqlite3")),
        )
        history = restarted_library.repository.list_media()
        self.assertEqual([item["id"] for item in history], [capture_id])
        self.assertEqual(restarted_library.image(capture_id), JPEG_A)
        self.assertEqual(gateway.image_calls, 1, "local history must not call the camera")

    def test_backup_bundle_contains_the_database_and_verified_media(self) -> None:
        capture_id = "12121212-2222-3333-4444-555555555555"
        record = capture_record(capture_id, JPEG_A)
        library, _gateway = self.library_for([(record, JPEG_A)])
        imported = library.capture()

        settings = SimpleNamespace(
            database_path=self.root / "smart_fridge.sqlite3",
            media_dir=self.media_root,
        )
        with patch("app.tasks.backup.load_settings", return_value=settings):
            bundle = create_bundle(self.root / "backups")

        database_copy = bundle / "smart_fridge.sqlite3"
        copied_media = bundle / "media" / str(imported["local_relpath"])
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(database_copy.is_file())
        self.assertEqual(copied_media.read_bytes(), JPEG_A)
        self.assertEqual(manifest["media_count"], 1)
        self.assertEqual(manifest["media"][0]["capture_id"], capture_id)
        self.assertEqual(manifest["media"][0]["sha256"], hashlib.sha256(JPEG_A).hexdigest())

    def test_import_rejects_invalid_jpeg_and_mismatched_sha_without_db_rows(
        self,
    ) -> None:
        invalid_id = "22222222-2222-3333-4444-555555555555"
        invalid_body = b"not-a-jpeg"
        invalid_record = capture_record(invalid_id, invalid_body)
        sha_id = "33333333-2222-3333-4444-555555555555"
        sha_record = capture_record(sha_id, JPEG_B)
        sha_record["image_sha256"] = "0" * 64
        library, _gateway = self.library_for(
            [(invalid_record, invalid_body), (sha_record, JPEG_B)]
        )

        for capture_id in (invalid_id, sha_id):
            with self.subTest(capture_id=capture_id):
                with self.assertRaises(MediaStoreError):
                    library.ensure(capture_id)
                self.assertIsNone(self.repository.get_media(capture_id))

        self.assertEqual(list((self.media_root / "captures").rglob("*.jpg")), [])
        self.assertEqual(list((self.media_root / "captures").rglob("*.part")), [])

    def test_local_history_detects_sha_corruption_without_camera_fallback(self) -> None:
        capture_id = "44444444-2222-3333-4444-555555555555"
        record = capture_record(capture_id, JPEG_A)
        library, gateway = self.library_for([(record, JPEG_A)])
        imported = library.ensure(capture_id)
        stored_path = self.media_root / str(imported["local_relpath"])
        stored_path.write_bytes(JPEG_B)
        gateway.online = False

        with self.assertRaisesRegex(MediaStoreError, "SHA-256"):
            library.image(capture_id)
        self.assertEqual(gateway.image_calls, 1)

    def test_legacy_media_without_a_local_path_is_safely_reimported(self) -> None:
        capture_id = "45454545-2222-3333-4444-555555555555"
        record = capture_record(capture_id, JPEG_A)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO media_assets(
                    id, source, captured_at, trigger, sha256, mime_type,
                    byte_size, record_json, state, created_at, updated_at
                ) VALUES (?, 'camera', ?, 'legacy', ?, 'image/jpeg', ?, '{}',
                          'ready', ?, ?)
                """,
                (
                    capture_id,
                    record["captured_at"],
                    record["image_sha256"],
                    len(JPEG_A),
                    record["captured_at"],
                    record["captured_at"],
                ),
            )
        library, gateway = self.library_for([(record, JPEG_A)])

        self.assertEqual(library.image(capture_id), JPEG_A)
        repaired = self.repository.get_media(capture_id)
        assert repaired is not None
        self.assertTrue(repaired["local_relpath"])
        self.assertEqual(repaired["state"], "ready")
        self.assertEqual(gateway.metadata_calls, 1)

    def test_closed_session_is_rejected_before_the_camera_is_triggered(self) -> None:
        session_id = str(self.repository.create_session()["id"])
        self.repository.cancel_session(session_id)

        class CountingLibrary:
            calls = 0

            def capture(self, _session_id: str) -> None:
                self.calls += 1

        library = CountingLibrary()
        with self.assertRaisesRegex(ConflictError, "no longer accept"):
            capture_for_session(session_id, library=library, repo=self.repository)  # type: ignore[arg-type]
        self.assertEqual(library.calls, 0)

    def test_session_attach_select_and_duplicate_attach_are_consistent(self) -> None:
        capture_a = "aaaaaaaa-2222-3333-4444-555555555555"
        capture_b = "bbbbbbbb-2222-3333-4444-555555555555"
        capture_c = "cccccccc-2222-3333-4444-555555555555"
        records = [
            (capture_record(capture_a, JPEG_A), JPEG_A),
            (capture_record(capture_b, JPEG_B), JPEG_B),
            (capture_record(capture_c, JPEG_C), JPEG_C),
        ]
        library, _gateway = self.library_for(records)
        session_id = str(self.repository.create_session()["id"])

        library.ensure(capture_a, session_id=session_id)
        library.ensure(capture_b, session_id=session_id)
        duplicated = library.ensure(capture_a, session_id=session_id)

        session = self.repository.get_session(session_id)
        assert session is not None
        self.assertEqual(
            [(item["id"], item["position"]) for item in session["captures"]],
            [(capture_a, 0), (capture_b, 1)],
        )
        self.assertEqual(session["selected_media_id"], capture_a)
        self.assertEqual(duplicated["id"], capture_a)

        selected = self.repository.select_capture(session_id, capture_b)
        self.assertEqual(selected["selected_media_id"], capture_b)

        library.ensure(capture_c)
        with self.assertRaisesRegex(ConflictError, "does not belong"):
            self.repository.select_capture(session_id, capture_c)

    def test_repeated_session_confirmation_creates_one_lot_and_receive_event(self) -> None:
        capture_id = "dddddddd-2222-3333-4444-555555555555"
        record = capture_record(capture_id, JPEG_A)
        library, _gateway = self.library_for([(record, JPEG_A)])
        session_id = str(self.repository.create_session()["id"])
        library.ensure(capture_id, session_id=session_id)

        created = self.create_lot(
            name="番茄",
            intake_session_id=session_id,
            nutrition={
                "basis_amount": 1,
                "basis_unit": "piece",
                "calories_kcal": 22,
            },
        )
        repeated = self.create_lot(
            name="不应创建的新名称",
            quantity=99,
            intake_session_id=session_id,
        )

        self.assertEqual(repeated["id"], created["id"])
        session = self.repository.get_session(session_id)
        assert session is not None
        self.assertEqual(session["status"], "confirmed")
        self.assertEqual([lot["id"] for lot in session["lots"]], [created["id"]])
        with self.database.connect() as connection:
            lot_count = connection.execute(
                "SELECT COUNT(*) FROM inventory_lots"
            ).fetchone()[0]
            receive_count = connection.execute(
                "SELECT COUNT(*) FROM inventory_events WHERE event_type='receive'"
            ).fetchone()[0]
            link_count = connection.execute(
                "SELECT COUNT(*) FROM intake_session_lots WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
        self.assertEqual((lot_count, receive_count, link_count), (1, 1, 1))

    def test_insights_only_include_consumption_explicitly_recorded_as_meal(self) -> None:
        lot = self.create_lot(
            quantity=4,
            primary_flavor="savory",
            nutrition={
                "basis_amount": 1,
                "basis_unit": "piece",
                "calories_kcal": 22,
                "protein_g": 1.1,
                "carbs_g": 4.8,
                "fat_g": 0.2,
                "fiber_g": 1.5,
                "sodium_mg": 5,
            },
        )

        ordinary = self.repository.consume(
            str(lot["id"]),
            amount=1,
            expected_version=1,
            reason="库存调整，不是用餐",
            record_meal=False,
        )
        self.assertIsNone(ordinary["recorded_meal_id"])
        before_meal = self.repository.insights(days=7)
        self.assertEqual(before_meal["sample_size"], 0)
        self.assertFalse(before_meal["availability"]["nutrition"])
        self.assertFalse(before_meal["availability"]["flavors"])

        recorded = self.repository.consume(
            str(lot["id"]),
            amount=1,
            expected_version=2,
            reason="午餐",
            record_meal=True,
            meal_type="lunch",
        )
        self.assertIsNotNone(recorded["recorded_meal_id"])
        insights = self.repository.insights(days=7)
        self.assertEqual(insights["sample_size"], 1)
        self.assertEqual(insights["nutrition"]["sample_size"], 1)
        self.assertEqual(insights["nutrition"]["totals"]["calories_kcal"], 22)
        self.assertEqual(insights["flavors"], [{"key": "savory", "label": "咸鲜", "count": 1}])

        with self.database.connect() as connection:
            meal_logs = connection.execute("SELECT COUNT(*) FROM meal_logs").fetchone()[0]
            meal_items = connection.execute("SELECT COUNT(*) FROM meal_items").fetchone()[0]
        self.assertEqual((meal_logs, meal_items), (1, 1))
        self.assertEqual(
            [event["details"]["recorded_as_meal"] for event in self.repository.events(str(lot["id"]))[1:]],
            [False, True],
        )


if __name__ == "__main__":
    unittest.main()
