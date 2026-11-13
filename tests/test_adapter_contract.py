import importlib
import os
import unittest

from tests.fixtures.contract import load_cases, validate_result


def load_adapter():
    spec = os.environ.get("TRIPFLOW_ADAPTER", "tripflow_adapter:TripFlowAdapter")
    module_name, class_name = spec.split(":", 1)
    try:
        cls = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError):
        return None
    return cls()


class AdapterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = load_adapter()
        if cls.adapter is None:
            raise unittest.SkipTest("TripFlowAdapter 未提供；仅运行 Fixture 合同检查")

    def test_all_scenarios_match_contract(self):
        _, _, cases = load_cases()
        for case in cases:
            with self.subTest(case=case.id):
                result = self.adapter.handle(case.kind, case.request)
                ok, detail = validate_result(case, result)
                self.assertTrue(ok, detail)


if __name__ == "__main__":
    unittest.main()
