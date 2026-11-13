import unittest

from tests.fixtures.contract import load_cases


class FixtureContractTests(unittest.TestCase):
    def test_fixture_has_required_metadata_and_unique_ids(self):
        version, api_mode, cases = load_cases()
        self.assertEqual(version, "synthetic-v1")
        self.assertEqual(api_mode, "fixture")
        self.assertEqual(len({c.id for c in cases}), len(cases))
        self.assertGreaterEqual(len(cases), 12)

    def test_fixture_cases_have_request_and_expectation(self):
        _, _, cases = load_cases()
        for case in cases:
            with self.subTest(case=case.id):
                self.assertTrue(case.kind)
                self.assertIsInstance(case.request, dict)
                self.assertIn("status", case.expect)


if __name__ == "__main__":
    unittest.main()
