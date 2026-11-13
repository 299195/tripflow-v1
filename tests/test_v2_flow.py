import tempfile
import unittest
from pathlib import Path

from tripflow.service import TripFlowService
from tripflow.planner import RouteResult
from tripflow.qwen_agent import QwenAgent, QwenSettings


class V2FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = TripFlowService(Path(self.tmp.name) / "v2.db", agent=QwenAgent(QwenSettings("offline", enabled=False)))
        self.service.save_poi({"id": "p1", "name": "西湖", "city": "杭州", "latitude": 30.25, "longitude": 120.15, "address": "西湖"})
        self.service.save_poi({"id": "p2", "name": "博物馆", "city": "杭州", "latitude": 30.26, "longitude": 120.16, "address": "博物馆"})
        self.trip = self.service.create_trip({"user_id": "u1", "city": "杭州", "start_date": "2026-11-13", "end_date": "2026-11-13"})
        self.plan = self.service.generate_itinerary(self.trip["id"], {"poi_ids": ["p1", "p2"], "date": "2026-11-13", "start": "09:00", "end": "18:00", "stay_minutes": {"p1": 60, "p2": 60}})

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_preview_confirm_diff_and_agent_trace(self):
        activity_id = self.plan["activities"][0]["id"]
        proposal = self.service.preview_replan(self.plan["id"], {"event_type": "delayed", "activity_id": activity_id, "delay_minutes": 30, "idempotency_key": "delay-1"})
        self.assertEqual(proposal["status"], "pending")
        self.assertGreaterEqual(len(proposal["options"]), 1)
        self.assertTrue(proposal["agent_run"]["agents"])
        confirmed = self.service.confirm_replan(self.plan["id"], {"proposal_id": proposal["proposal_id"], "option_id": proposal["options"][0]["option_id"], "base_version_id": proposal["base_version_id"]})
        self.assertEqual(confirmed["status"], "confirmed")
        diff = self.service.diff_versions(self.plan["id"], proposal["base_version_id"], confirmed["new_version_id"])
        self.assertTrue(diff["changed"])

    def test_idempotent_preview_and_feedback(self):
        aid = self.plan["activities"][0]["id"]
        first = self.service.preview_replan(self.plan["id"], {"event_type": "skipped", "activity_id": aid, "idempotency_key": "skip-1"})
        second = self.service.preview_replan(self.plan["id"], {"event_type": "skipped", "activity_id": aid, "idempotency_key": "skip-1"})
        self.assertEqual(first["proposal_id"], second["proposal_id"])
        feedback = self.service.record_feedback("u1", self.plan["id"], {"target_type": "proposal", "target_id": first["proposal_id"], "label": "rejected", "reason_code": "too_far"})
        self.assertEqual(feedback["status"], "recorded")

    def test_service_persists_provider_route_metadata(self):
        self.service.route_provider = lambda _origin, _destination: RouteResult(12, 1800, "amap", "walking", {"fixture": True}, "2026-11-13T00:00:00+00:00", False)
        trip = self.service.create_trip({"user_id": "u2", "city": "杭州", "start_date": "2026-11-13", "end_date": "2026-11-13"})
        result = self.service.generate_itinerary(trip["id"], {"poi_ids": ["p1", "p2"], "date": "2026-11-13", "start": "09:00", "end": "18:00"})
        self.assertEqual(result["travel_legs"][0]["route_data"]["source"], "amap")

