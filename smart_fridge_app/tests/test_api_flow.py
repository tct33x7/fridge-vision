from __future__ import annotations

import os
import tempfile
import unittest


_runtime = tempfile.TemporaryDirectory()
os.environ["SMART_FRIDGE_DATA_DIR"] = _runtime.name
os.environ["SMART_FRIDGE_CAMERA_URL"] = "http://127.0.0.1:65534"
os.environ["SMART_FRIDGE_CAMERA_TIMEOUT_SECONDS"] = "0.1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def tearDownModule() -> None:
    _runtime.cleanup()


class ApiFlowTest(unittest.TestCase):
    def test_inventory_profile_and_offline_camera_flow(self) -> None:
        with TestClient(app) as client:
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("饮食均衡助手", page.text)

            health = client.get("/api/v1/health").json()
            self.assertEqual(health["status"], "degraded")
            self.assertTrue(health["database"]["ready"])
            self.assertFalse(health["camera"]["connected"])

            locations = client.get("/api/v1/locations").json()
            self.assertEqual(locations["count"], 4)

            created_response = client.post(
                "/api/v1/inventory",
                json={
                    "name": "番茄",
                    "category": "vegetable",
                    "quantity": 3,
                    "unit": "piece",
                    "location_id": "fridge",
                    "expires_on": "2026-08-10",
                },
            )
            self.assertEqual(created_response.status_code, 201)
            created = created_response.json()
            self.assertEqual(created["quantity"], 3)
            self.assertEqual(created["source"], "manual")

            incompatible_nutrition = client.post(
                "/api/v1/inventory",
                json={
                    "name": "盒装酸奶",
                    "category": "dairy",
                    "quantity": 1,
                    "unit": "box",
                    "location_id": "fridge",
                    "nutrition": {
                        "basis_amount": 100,
                        "basis_unit": "g",
                        "calories_kcal": 70,
                    },
                },
            )
            self.assertEqual(incompatible_nutrition.status_code, 422)

            changed = client.post(
                f"/api/v1/inventory/{created['id']}/consume",
                json={"amount": 1, "expected_version": 1, "reason": "API test"},
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.json()["quantity"], 2)
            self.assertEqual(changed.json()["version"], 2)

            events = client.get(
                f"/api/v1/inventory/{created['id']}/events"
            ).json()
            self.assertEqual(
                [item["event_type"] for item in events["items"]],
                ["receive", "consume"],
            )

            profile = client.put(
                "/api/v1/profile",
                json={
                    "display_name": "验收用户",
                    "diet_goal": "balanced",
                    "preferences": ["清淡"],
                    "allergies": ["花生"],
                    "medications": [],
                    "onboarding_completed": True,
                },
            )
            self.assertEqual(profile.status_code, 200)
            self.assertEqual(profile.json()["allergies"], ["花生"])

            camera = client.get("/api/v1/camera/status").json()
            self.assertFalse(camera["connected"])
            self.assertEqual(camera["camera"]["error"], "摄像头服务未连接")

            gallery = client.get("/api/v1/camera/captures")
            self.assertEqual(gallery.status_code, 503)
            self.assertEqual(gallery.json()["error"], "摄像头服务未连接")


if __name__ == "__main__":
    unittest.main()
