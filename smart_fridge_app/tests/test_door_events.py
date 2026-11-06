from __future__ import annotations

import base64
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.database.connection import Database
from app.repositories.door_events import DoorEventRepository
from app.repositories.inventory import InventoryRepository, NotFoundError
from app.services.media_store import MediaStore


FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"


class DoorEventRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.database = Database(root / "smart_fridge.sqlite3")
        self.database.initialize()
        self.inventory = InventoryRepository(self.database)
        self.media = MediaStore(root / "media")
        self.repo = DoorEventRepository(self.inventory, self.media)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, action: str, label: str = "banana", **overrides):
        values = {
            "session_id": "session-1",
            "occurred_at": "2026-11-06T10:00:00.000+00:00",
            "action": action,
            "label": label,
            "label_zh": None,
            "confidence": 0.9,
            "count": 1.0,
            "vlm": None,
            "keyframe": FAKE_JPEG,
        }
        values.update(overrides)
        return self.repo.record(**values)

    def test_in_creates_lot_with_category_shelf_life_and_evidence(self) -> None:
        event = self.record("in", label="banana", label_zh="香蕉", count=3)
        self.assertEqual(event["status"], "applied")
        self.assertEqual(event["category"], "fruit")
        self.assertIsNotNone(event["image_url"])
        lot = self.inventory.get_lot(str(event["lot_id"]))
        self.assertEqual(lot["name"], "香蕉")
        self.assertEqual(lot["quantity"], 3)
        self.assertEqual(lot["source"], "camera")
        self.assertEqual(lot["expires_on"], (date.today() + timedelta(days=7)).isoformat())
        self.assertTrue(self.media.exists(self.inventory.get_media(str(event["media_id"]))["local_relpath"]))
        events = self.inventory.events(str(event["lot_id"]))
        self.assertEqual([e["event_type"] for e in events], ["receive"])

    def test_label_override_beats_category_default(self) -> None:
        event = self.record("in", label="garlic", label_zh="大蒜")
        lot = self.inventory.get_lot(str(event["lot_id"]))
        self.assertEqual(lot["expires_on"], (date.today() + timedelta(days=30)).isoformat())

    def test_out_consumes_earliest_expiring_lot(self) -> None:
        later = self.inventory.create_lot(
            name="香蕉", category="fruit", barcode=None, quantity=2, unit="piece",
            location_id="fridge", purchased_on=None, expires_on="2026-12-20", note="",
        )
        sooner = self.inventory.create_lot(
            name="香蕉", category="fruit", barcode=None, quantity=2, unit="piece",
            location_id="fridge", purchased_on=None, expires_on="2026-11-10", note="",
        )
        event = self.record("out", label="banana", label_zh="香蕉", count=1)
        self.assertEqual(event["status"], "applied")
        self.assertEqual(event["lot_id"], sooner["id"])
        self.assertEqual(self.inventory.get_lot(str(sooner["id"]))["quantity"], 1)
        self.assertEqual(self.inventory.get_lot(str(later["id"]))["quantity"], 2)

    def test_out_without_stock_is_unmatched_and_changes_nothing(self) -> None:
        event = self.record("out", label="milk", label_zh="牛奶")
        self.assertEqual(event["status"], "unmatched")
        self.assertIsNone(event["lot_id"])
        self.assertEqual(self.inventory.list_lots(status="active"), [])
        undone = self.repo.undo(str(event["id"]))
        self.assertEqual(undone["status"], "undone")

    def test_out_caps_at_available_quantity(self) -> None:
        self.record("in", label="egg", label_zh="鸡蛋", count=2)
        event = self.record("out", label="egg", label_zh="鸡蛋", count=5)
        self.assertEqual(event["applied_quantity"], 2)
        self.assertEqual(event["lot"]["status"], "used")

    def test_undo_in_discards_lot_with_reverse_ledger(self) -> None:
        event = self.record("in", label="apple", label_zh="苹果", count=2)
        undone = self.repo.undo(str(event["id"]))
        self.assertEqual(undone["status"], "undone")
        lot = self.inventory.get_lot(str(event["lot_id"]))
        self.assertEqual(lot["status"], "discarded")
        self.assertEqual(lot["quantity"], 0)
        self.assertEqual(
            [e["event_type"] for e in self.inventory.events(str(event["lot_id"]))],
            ["receive", "discard"],
        )
        again = self.repo.undo(str(event["id"]))
        self.assertEqual(again["status"], "undone")
        self.assertEqual(len(self.inventory.events(str(event["lot_id"]))), 2)

    def test_undo_out_restores_quantity(self) -> None:
        self.record("in", label="milk", label_zh="牛奶", count=2)
        out = self.record("out", label="milk", label_zh="牛奶", count=2)
        self.assertEqual(out["lot"]["status"], "used")
        self.repo.undo(str(out["id"]))
        lot = self.inventory.get_lot(str(out["lot_id"]))
        self.assertEqual(lot["status"], "active")
        self.assertEqual(lot["quantity"], 2)
        self.assertEqual([e["event_type"] for e in self.inventory.events(lot["id"])][-1], "adjust")

    def test_correct_reuses_evidence_and_rewrites(self) -> None:
        event = self.record("in", label="bottle", label_zh="瓶装饮料", count=1)
        fixed = self.repo.correct(str(event["id"]), label_zh="鲜奶", count=2)
        self.assertEqual(fixed["label_zh"], "鲜奶")
        self.assertEqual(fixed["count"], 2)
        self.assertEqual(fixed["media_id"], event["media_id"])
        self.assertEqual(self.repo.get(str(event["id"]))["status"], "undone")
        active = self.inventory.list_lots(status="active")
        self.assertEqual([(item["name"], item["quantity"]) for item in active], [("鲜奶", 2)])

    def test_invalid_keyframe_is_quarantined_not_recorded(self) -> None:
        with self.assertRaises(Exception):
            self.record("in", keyframe=b"not a jpeg")
        self.assertEqual(self.repo.list(), [])

    def test_shelf_life_table_is_editable(self) -> None:
        changed = self.repo.set_shelf_life("fruit", default_days=10)
        self.assertEqual(changed["default_days"], 10)
        event = self.record("in", label="mango", label_zh="芒果")
        lot = self.inventory.get_lot(str(event["lot_id"]))
        self.assertEqual(lot["expires_on"], (date.today() + timedelta(days=10)).isoformat())
        with self.assertRaises(NotFoundError):
            self.repo.set_shelf_life("nope", default_days=1)


class DoorEventApiTest(unittest.TestCase):
    def test_post_list_undo_over_http(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            created = client.post(
                "/api/v1/door-events",
                json={
                    "session_id": "api-session",
                    "occurred_at": "2026-11-06T18:00:00+08:00",
                    "action": "in",
                    "label": "banana",
                    "label_zh": "香蕉",
                    "confidence": 0.91,
                    "count": 3,
                    "keyframe_base64": base64.b64encode(FAKE_JPEG).decode(),
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            event = created.json()
            self.assertEqual(event["status"], "applied")
            image = client.get(event["image_url"])
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, FAKE_JPEG)

            listed = client.get("/api/v1/door-events?limit=5").json()
            self.assertEqual(listed["items"][0]["id"], event["id"])

            bad = client.post(
                "/api/v1/door-events",
                json={"session_id": "s", "action": "in", "label": "x", "keyframe_base64": "@@@"},
            )
            self.assertEqual(bad.status_code, 422)

            naive = client.post(
                "/api/v1/door-events",
                json={"session_id": "s", "action": "in", "label": "x", "occurred_at": "2026-11-06T18:00:00"},
            )
            self.assertEqual(naive.status_code, 422)

            undone = client.post(f"/api/v1/door-events/{event['id']}/undo")
            self.assertEqual(undone.status_code, 200)
            self.assertEqual(undone.json()["status"], "undone")
            lot = client.get(f"/api/v1/inventory/{event['lot_id']}").json()
            self.assertEqual(lot["status"], "discarded")

            shelf = client.get("/api/v1/door-events/meta/shelf-life").json()
            self.assertEqual(shelf["count"], 12)
            missing = client.post("/api/v1/door-events/does-not-exist/undo")
            self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
