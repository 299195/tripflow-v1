from pathlib import Path

from fastapi.testclient import TestClient

from tripflow.api import create_app
from tripflow.qwen_agent import QwenAgent, QwenSettings
from tripflow.service import TripFlowService


def test_v2_replan_http_flow(tmp_path: Path):
    service = TripFlowService(tmp_path / "api.db", agent=QwenAgent(QwenSettings("offline", enabled=False)))
    try:
        client = TestClient(create_app(service))
        trip = client.post("/api/v1/trips", json={"user_id": "api-user", "city": "杭州", "start_date": "2026-11-13", "end_date": "2026-11-13"}).json()
        for index, poi_id in enumerate(("p1", "p2")):
            service.save_poi({"id": poi_id, "name": poi_id, "city": "杭州", "latitude": 30.2 + index * 0.01, "longitude": 120.1 + index * 0.01})
        plan = client.post(f"/api/v1/trips/{trip['id']}/itinerary/generate", json={"poi_ids": ["p1", "p2"], "date": "2026-11-13", "start": "09:00", "end": "18:00"}).json()
        activity_id = plan["activities"][0]["id"]
        preview_response = client.post(f"/api/v2/itineraries/{plan['id']}/replan/preview", json={"event_type": "delayed", "activity_id": activity_id, "delay_minutes": 30})
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["options"]
        confirmed = client.post(f"/api/v2/itineraries/{plan['id']}/replan/confirm", json={"proposal_id": preview["proposal_id"], "option_id": preview["options"][0]["option_id"], "base_version_id": preview["base_version_id"]})
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"
    finally:
        service.close()
