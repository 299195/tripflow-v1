import json
import os
import unittest
from unittest.mock import patch

from tripflow.qwen_agent import QwenAgent, QwenSettings


class QwenAgentTests(unittest.TestCase):
    def test_settings_use_qwen_alias_without_exposing_secret(self):
        with patch.dict(os.environ, {"QWEN_API_KEY": "secret-value", "QWEN_MODEL": "qwen-test"}, clear=False):
            settings = QwenSettings.from_env()
        self.assertIsNotNone(settings)
        self.assertEqual(settings.model, "qwen-test")
        self.assertNotIn("secret", str(QwenAgent(settings).status()))

    def test_structured_mock_response_is_parsed_and_schema_is_sent(self):
        seen = {}

        def post(url, headers, body, timeout):
            seen.update(url=url, headers=headers, body=json.loads(body), timeout=timeout)
            return json.dumps({"choices": [{"message": {"content": json.dumps({"explanation": "Stable plan", "constraints_checked": ["time"], "warnings": []})}}]}).encode()

        agent = QwenAgent(QwenSettings("secret", "qwen-test"), post)
        result = agent.explain_plan({"activities": []})
        self.assertEqual(result["status"], "success")
        self.assertEqual(seen["body"]["response_format"]["type"], "json_schema")
        self.assertNotIn("secret", json.dumps(seen["body"]))
        self.assertNotIn("secret", str(agent.status()))

    def test_failed_call_returns_deterministic_fallback(self):
        def post(*args):
            raise TimeoutError("test timeout")

        result = QwenAgent(QwenSettings("secret", "qwen-test"), post).explain_plan({})
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(result["mode"], "deterministic_fallback")

    def test_missing_key_is_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            agent = QwenAgent()
        self.assertFalse(agent.configured)
        self.assertIsNone(agent.explain_plan({}))

