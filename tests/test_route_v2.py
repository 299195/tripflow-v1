import json
from datetime import datetime
from pathlib import Path

import pytest

from tripflow.planner import DeterministicPlanner, PlanInput
from tripflow.route_service import AmapRouteProvider, RouteProviderUnavailable
from tripflow_amap import AmapAdapter, AmapSettings
from tripflow_amap.transport import HttpResponse


FIXTURES = Path(__file__).parent / "fixtures"


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        return self.response


def _adapter(response):
    transport = FakeTransport(response)
    adapter = AmapAdapter(
        AmapSettings("fixture-key", max_retries=0, retry_backoff_seconds=0),
        transport,
    )
    return adapter, transport


def _poi(poi_id, location):
    longitude, latitude = location.split(",")
    return {
        "id": poi_id,
        "name": poi_id,
        "location": location,
        "longitude": float(longitude),
        "latitude": float(latitude),
    }


def test_amap_walking_fixture_maps_to_structured_route_result():
    payload = json.loads((FIXTURES / "route_success.json").read_text(encoding="utf-8"))
    adapter, transport = _adapter(HttpResponse(200, payload))
    provider = AmapRouteProvider(adapter, mode="walking", allow_estimate=False)

    result = provider(_poi("a", "116.390000,39.900000"), _poi("b", "116.400000,39.910000"))

    assert result.duration_minutes == 15
    assert result.distance_meters == 2400
    assert result.source == "amap"
    assert result.mode == "walking"
    assert result.raw_summary["path_count"] == 1
    assert "new_route_field" in result.raw_summary["unknown_fields"]
    assert result.estimated is False
    assert datetime.fromisoformat(result.fetched_at)
    assert transport.calls[0][1]["origin"] == "116.390000,39.900000"
    assert transport.calls[0][1]["destination"] == "116.400000,39.910000"
    assert transport.calls[0][1]["output"] == "JSON"


def test_planner_preserves_provider_route_metadata():
    payload = json.loads((FIXTURES / "route_success.json").read_text(encoding="utf-8"))
    adapter, _ = _adapter(HttpResponse(200, payload))
    provider = AmapRouteProvider(adapter, mode="walking", allow_estimate=False)
    request = PlanInput(
        city="北京",
        date="2026-12-01",
        poi_ids=["a", "b"],
        pois={"a": _poi("a", "116.390000,39.900000"), "b": _poi("b", "116.400000,39.910000")},
        start="09:00",
        end="18:00",
    )

    result = DeterministicPlanner().plan(request, route_provider=provider)

    assert result.status == "feasible"
    assert result.legs[0].source == "amap"
    assert result.legs[0].mode == "walking"
    assert result.legs[0].distance_meters == 2400
    assert result.legs[0].raw_summary["provider"] == "amap"
    assert result.legs[0].fetched_at
    assert result.legs[0].estimated is False


def test_upstream_failure_is_explicitly_labelled_estimate():
    adapter, _ = _adapter(HttpResponse(200, {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}))
    provider = AmapRouteProvider(adapter, mode="walking", allow_estimate=True)

    result = provider(_poi("a", "116.390000,39.900000"), _poi("b", "116.400000,39.910000"))

    assert result.source == "estimate:straight_line_after_amap_failure"
    assert result.raw_summary["status"] == "fallback_estimate"
    assert result.raw_summary["fallback"]["code"] == "10001"
    assert result.fetched_at
    assert result.estimated is True
    assert result.source != "amap"


def test_upstream_failure_can_be_configured_as_hard_route_error():
    adapter, _ = _adapter(HttpResponse(200, {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}))
    provider = AmapRouteProvider(adapter, mode="walking", allow_estimate=False)

    with pytest.raises(RouteProviderUnavailable):
        provider(_poi("a", "116.390000,39.900000"), _poi("b", "116.400000,39.910000"))


def test_estimate_has_a_structured_reason_and_timestamp():
    result = DeterministicPlanner.estimate_route(
        _poi("a", "116.390000,39.900000"),
        _poi("b", "116.400000,39.910000"),
        reason="fixture_route_failure",
    )

    assert result.estimated is True
    assert result.source == "deterministic_straight_line_estimate"
    assert result.raw_summary == {
        "kind": "estimate",
        "method": "straight_line_distance",
        "reason": "fixture_route_failure",
    }
    assert datetime.fromisoformat(result.fetched_at)
