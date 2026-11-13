import unittest
from urllib.parse import parse_qs, urlparse

from tripflow.meituan import MeituanMaps


class MeituanMapsTests(unittest.TestCase):
    def test_search_normalizes_documented_fields_without_inventing_media(self):
        def transport(url, timeout):
            params = parse_qs(urlparse(url).query)
            self.assertEqual(params["keywords"], ["西湖"])
            self.assertEqual(params["city"], ["杭州"])
            self.assertEqual(params["key"], ["test-key"])
            return 200, {"status": 200, "pois": [{"id": "123", "name": "西湖", "type": "风景名胜", "address": "西湖区", "location": "120.1,30.2", "cityname": "杭州市"}]}
        results = MeituanMaps("test-key", transport).search("西湖", "杭州")
        self.assertEqual(results[0]["id"], "meituan:123")
        self.assertEqual(results[0]["city"], "杭州市")
        self.assertIsNone(results[0]["image_url"])
        self.assertIsNone(results[0]["description"])

    def test_permission_failure_is_not_a_successful_empty_search(self):
        api = MeituanMaps("test-key", lambda *_: (200, {"status": 403, "msg": "账号未授权"}))
        with self.assertRaisesRegex(RuntimeError, "账号未授权"):
            api.search("西湖", "杭州")


if __name__ == "__main__":
    unittest.main()
