import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tripflow.api import create_app
from tripflow.service import TripFlowService
from tripflow.qwen_agent import QwenAgent, QwenSettings


class ProductFlowTests(unittest.TestCase):
    def test_home_profile_and_nearby_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            service = TripFlowService(Path(directory) / "test.db")
            client = TestClient(create_app(service))
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("下一站", home.text)
            profile = client.get("/api/v1/users/local-traveler/profile")
            self.assertEqual(profile.status_code, 200)
            self.assertEqual(profile.json()["favorites"], [])
            nearby = client.get("/api/v1/pois/nearby", params={"location": "invalid"})
            self.assertEqual(nearby.status_code, 422)
            service.close()

    def test_guide_requires_city_and_real_model_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"QWEN_API_KEY": "", "DASHSCOPE_API_KEY": "", "AMAP_API_KEY": ""}):
                service = TripFlowService(Path(directory) / "test.db")
                client = TestClient(create_app(service))
                self.assertEqual(client.post("/api/v1/guides/draft", json={"city": "杭州", "message": ""}).status_code, 422)
                draft = client.post("/api/v1/guides/draft", json={"city": "杭州", "message": "轻松的一日游"})
                self.assertEqual(draft.status_code, 200)
                self.assertEqual(draft.json()["mode"], "basic")
                service.close()

    def test_qwen_guide_parses_structured_response(self):
        import json
        response = {"choices": [{"message": {"content": json.dumps({"title": "杭州慢游", "summary": "沿湖散步", "style": "慢游", "place_queries": ["西湖"], "tips": ["出发前确认开放时间"]}, ensure_ascii=False)}}]}
        agent = QwenAgent(QwenSettings("test-key"), post=lambda *_: json.dumps(response, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(agent.draft_guide("想看湖", "杭州")["place_queries"], ["西湖"])


if __name__ == "__main__":
    unittest.main()
