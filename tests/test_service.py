import unittest

from tripflow.service import TripFlowService
from tripflow.qwen_agent import QwenAgent, QwenSettings


class ServiceFlowTests(unittest.TestCase):
    def setUp(self):
        self.service = TripFlowService(agent=QwenAgent(QwenSettings("offline", enabled=False)))
        self.user = "user-1"
        self.service.create_trip({"user_id": self.user, "city": "杭州", "start_date": "2026-12-01", "end_date": "2026-12-02"})
        self.trip = self.service.db.connection.execute("SELECT * FROM trips").fetchone()
        self.service.save_poi({"id": "p1", "name": "西湖", "city": "杭州", "latitude": 30.24, "longitude": 120.15})
        self.service.save_poi({"id": "p2", "name": "博物馆", "city": "杭州", "latitude": 30.25, "longitude": 120.16})

    def tearDown(self):
        self.service.close()

    def test_plan_edit_and_history_restore_create_versions(self):
        itinerary = self.service.generate_itinerary(self.trip["id"], {"poi_ids": ["p1", "p2"], "start": "09:00", "end": "18:00"})
        versions = self.service.list_versions(itinerary["id"])
        self.assertEqual(len(versions), 1)
        edited = self.service.edit_itinerary(itinerary["id"], {"operation": "delete", "poi_id": "p2"})
        self.assertEqual(len(edited["activities"]), 1)
        restored = self.service.restore_version(itinerary["id"], versions[0]["id"])
        self.assertEqual(len(restored["activities"]), 2)
        self.assertEqual(len(self.service.list_versions(itinerary["id"])), 3)

    def test_favorite_and_execution_event(self):
        favorite = self.service.favorite(self.user, {"poi_id": "p1", "preference_tags": ["景观"]})
        self.assertEqual(favorite["preference_tags"], ["景观"])
        itinerary = self.service.generate_itinerary(self.trip["id"], {"poi_ids": ["p1"]})
        event = self.service.execution_event(itinerary["id"], {"event_type": "started"})
        self.assertEqual(event["event_type"], "started")
