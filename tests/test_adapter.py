import json
from pathlib import Path
import pytest
from tripflow_amap import AmapAdapter, AmapSettings
from tripflow_amap.transport import HttpResponse
FIX = Path(__file__).parent / "fixtures"
def fixture(n): return json.loads((FIX/n).read_text(encoding="utf-8"))
class FakeTransport:
    def __init__(self, xs): self.xs, self.calls = list(xs), []
    def __call__(self, url, params, timeout):
        self.calls.append((url, params, timeout)); x = self.xs.pop(0)
        if isinstance(x, Exception): raise x
        return x
def make(xs, retries=2):
    f = FakeTransport(xs if isinstance(xs, list) else [xs]); return AmapAdapter(AmapSettings("fixture-key", max_retries=retries, retry_backoff_seconds=0), f), f
def test_search_maps_and_preserves_metadata():
    a, _ = make(HttpResponse(200, fixture("search_success.json"))); r = a.search_pois("故宫", city="北京")
    assert r.ok and r.data[0].id == "B000A1" and r.meta.provider == "amap" and r.meta.unknown["count"] == "1" and r.meta.raw_data["pois"]
def test_route_and_navigation():
    a, _ = make(HttpResponse(200, fixture("route_success.json"))); r = a.route("116,39", "117,40")
    assert r.ok and r.data.distance_m == 2400 and r.data.duration_s == 900 and "uri.amap.com/navigation" in a.navigation_url("116,39", "117,40", mode="driving")
def test_api_error_is_not_success():
    a, _ = make(HttpResponse(200, {"status":"0","info":"INVALID_USER_KEY","infocode":"10001"})); r = a.search_pois("故宫")
    assert not r.ok and r.data is None and r.meta.error_code == "10001"
def test_transport_retries_then_errors():
    a, f = make([TimeoutError("offline")] * 3); r = a.search_pois("故宫")
    assert not r.ok and r.meta.error_code == "transport_error" and len(f.calls) == 3
def test_key_only_from_environment(monkeypatch):
    monkeypatch.delenv("AMAP_API_KEY", raising=False)
    with pytest.raises(ValueError): AmapSettings.from_env()

