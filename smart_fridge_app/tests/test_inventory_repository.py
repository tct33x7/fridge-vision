from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.connection import Database, sqlite_has_wal_reset_fix
from app.repositories.inventory import ConflictError, InventoryRepository


class InventoryRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = Database(self.root / "smart_fridge.sqlite3")
        self.database.initialize()
        self.repository = InventoryRepository(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_lot(self, **overrides):
        values = {
            "name": "番茄",
            "category": "vegetable",
            "barcode": None,
            "quantity": 3.0,
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
        return self.repository.create_lot(**values)

    def test_create_consume_and_audit_lot(self) -> None:
        item = self.create_lot()
        self.assertEqual(item["quantity"], 3.0)
        self.assertEqual(item["version"], 1)
        events = self.repository.events(str(item["id"]))
        self.assertEqual([event["event_type"] for event in events], ["receive"])

        changed = self.repository.consume(
            str(item["id"]), amount=1.25, expected_version=1, reason="test meal"
        )
        self.assertAlmostEqual(float(changed["quantity"]), 1.75)
        self.assertEqual(changed["version"], 2)
        events = self.repository.events(str(item["id"]))
        self.assertEqual([event["event_type"] for event in events], ["receive", "consume"])
        self.assertAlmostEqual(float(events[-1]["quantity_after"]), 1.75)

    def test_optimistic_version_rejects_stale_update(self) -> None:
        item = self.create_lot()
        self.repository.consume(str(item["id"]), amount=1, expected_version=1, reason="first")
        with self.assertRaises(ConflictError):
            self.repository.consume(
                str(item["id"]), amount=1, expected_version=1, reason="stale client"
            )

    def test_discard_preserves_event_instead_of_deleting(self) -> None:
        item = self.create_lot(quantity=2.0)
        discarded = self.repository.discard(
            str(item["id"]), expected_version=1, reason="spoiled"
        )
        self.assertEqual(discarded["status"], "discarded")
        self.assertEqual(discarded["quantity"], 0.0)
        self.assertEqual(self.repository.events(str(item["id"]))[-1]["event_type"], "discard")

    def test_camera_capture_is_snapshotted_and_linked(self) -> None:
        camera_record = {
            "id": "11111111-2222-3333-4444-555555555555",
            "captured_at": "2026-08-07T12:00:00+08:00",
            "trigger": "实体按钮",
            "image_sha256": "a" * 64,
            "mime_type": "image/jpeg",
            "width": 1920,
            "height": 1080,
            "bytes": 1000,
            "camera_device": "/dev/video0",
            "image_path": "/private/path/that/must/not/reach/browser.jpg",
            "recognition": {"status": "skipped"},
        }
        self.repository.upsert_media(
            camera_record,
            local_relpath=f"captures/2026/08/07/{camera_record['id']}.jpg",
        )
        item = self.create_lot(source_capture_id=camera_record["id"])
        self.assertEqual(item["source"], "camera")
        self.assertEqual(item["source_capture_id"], camera_record["id"])
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT sha256, state FROM media_assets WHERE id=?", (camera_record["id"],)
            ).fetchone()
        self.assertEqual(row["sha256"], "a" * 64)
        self.assertEqual(row["state"], "ready")

    def test_session_confirmation_is_idempotent_and_feeds_real_insights(self) -> None:
        session = self.repository.create_session()
        capture_id = "11111111-2222-3333-4444-555555555555"
        self.repository.upsert_media(
            {
                "id": capture_id,
                "captured_at": "2026-08-07T12:00:00+08:00",
                "trigger": "网页按钮",
                "image_sha256": "a" * 64,
                "mime_type": "image/jpeg",
                "recognition": {"status": "skipped"},
            },
            local_relpath=f"captures/2026/08/07/{capture_id}.jpg",
            session_id=str(session["id"]),
        )
        values = {
            "source_capture_id": None,
            "intake_session_id": str(session["id"]),
            "primary_flavor": "savory",
            "nutrition": {
                "basis_amount": 1,
                "basis_unit": "piece",
                "calories_kcal": 22,
                "protein_g": 1.1,
                "carbs_g": 4.8,
                "fat_g": 0.2,
                "fiber_g": 1.5,
                "sodium_mg": 5,
            },
        }
        created = self.create_lot(**values)
        repeated = self.create_lot(**values)
        self.assertEqual(created["id"], repeated["id"])
        self.assertEqual(self.repository.get_session(str(session["id"]))["status"], "confirmed")

        changed = self.repository.consume(
            str(created["id"]),
            amount=1,
            expected_version=1,
            reason="午餐",
            record_meal=True,
            meal_type="lunch",
        )
        self.assertIsNotNone(changed["recorded_meal_id"])
        insights = self.repository.insights(days=7)
        self.assertTrue(insights["availability"]["nutrition"])
        self.assertTrue(insights["availability"]["flavors"])
        self.assertEqual(insights["nutrition"]["totals"]["calories_kcal"], 22)
        self.assertEqual(insights["flavors"][0]["label"], "咸鲜")

    def test_lot_nutrition_snapshot_is_not_overwritten_by_a_new_same_name_lot(self) -> None:
        older = self.create_lot(
            name="原味酸奶",
            quantity=2,
            nutrition={
                "basis_amount": 1,
                "basis_unit": "piece",
                "calories_kcal": 100,
            },
        )
        self.create_lot(
            name="原味酸奶",
            quantity=2,
            nutrition={
                "basis_amount": 1,
                "basis_unit": "piece",
                "calories_kcal": 200,
            },
        )

        self.repository.consume(
            str(older["id"]),
            amount=1,
            expected_version=1,
            reason="旧批次",
            record_meal=True,
        )
        self.assertEqual(
            self.repository.insights(days=7)["nutrition"]["totals"]["calories_kcal"],
            100,
        )

    def test_insights_compare_offset_timestamps_on_the_actual_timeline(self) -> None:
        lot = self.create_lot(
            quantity=2,
            nutrition={
                "basis_amount": 1,
                "basis_unit": "piece",
                "calories_kcal": 22,
            },
        )
        outside_window = datetime.now(timezone.utc) - timedelta(days=7, minutes=5)
        misleading_offset = outside_window.astimezone(timezone(timedelta(hours=14)))
        self.repository.consume(
            str(lot["id"]),
            amount=1,
            expected_version=1,
            reason="窗口之外",
            record_meal=True,
            eaten_at=misleading_offset.isoformat(),
        )
        self.assertEqual(self.repository.insights(days=7)["sample_size"], 0)

    def test_profile_round_trip_and_verified_backup(self) -> None:
        profile = self.repository.update_profile(
            display_name="测试用户",
            diet_goal="balanced",
            preferences=["清淡"],
            allergies=["花生"],
            medications=[],
            onboarding_completed=True,
        )
        self.assertTrue(profile["onboarding_completed"])
        self.assertEqual(profile["allergies"], ["花生"])

        backup = self.database.backup_to(self.root / "backups" / "copy.sqlite3")
        with sqlite3.connect(backup) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_runtime_uses_wal_only_when_fix_is_known(self) -> None:
        expected = "wal" if sqlite_has_wal_reset_fix() else "delete"
        self.assertEqual(self.database.journal_mode, expected)


if __name__ == "__main__":
    unittest.main()
