"""Shared data contract for the V1 adapter boundary."""
from dataclasses import dataclass
from typing import Any, Mapping


REQUIRED_RESULT_FIELDS = {"status"}
REASONED_STATUSES = {"conflict", "route_error", "invalid_input", "needs_clarification", "infeasible", "timeout"}


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    request: Mapping[str, Any]
    expect: Mapping[str, Any]


def load_cases(path=None):
    import json
    from pathlib import Path
    p = Path(path or Path(__file__).with_name("scenarios.json"))
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw["data_version"], raw["api_mode"], [Case(**item) for item in raw["cases"]]


def validate_result(case: Case, result: Mapping[str, Any]):
    missing = REQUIRED_RESULT_FIELDS - set(result)
    if missing:
        return False, f"missing result fields: {sorted(missing)}"
    expected_status = case.expect["status"]
    if result["status"] != expected_status:
        return False, f"status expected {expected_status!r}, got {result['status']!r}"
    if expected_status in REASONED_STATUSES and result.get("reason_code") != case.expect.get("reason_code"):
        return False, f"reason_code expected {case.expect.get('reason_code')!r}, got {result.get('reason_code')!r}"
    return True, "ok"
