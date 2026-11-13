from __future__ import annotations
import urllib.parse
import time
from time import monotonic
from typing import Any
from .config import AmapSettings
from .models import ApiMeta, ApiResult, Place, Route, now_utc
from .transport import HttpResponse, Transport, urllib_transport

class AmapAdapter:
    provider = "amap"
    def __init__(self, settings: AmapSettings, transport: Transport = urllib_transport):
        self.settings, self.transport = settings, transport

    def _request(self, path: str, params: dict[str, str]) -> tuple[HttpResponse | None, ApiMeta]:
        started, queried_at = monotonic(), now_utc()
        request_params = {**params, "key": self.settings.api_key, "output": "JSON"}
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self.transport(self.settings.base_url + path, request_params, self.settings.timeout_seconds)
                payload = response.json_data
                if response.status_code >= 500 and attempt < self.settings.max_retries:
                    time.sleep(self.settings.retry_backoff_seconds * (2 ** attempt))
                    continue
                ok = response.status_code < 400 and str(payload.get("status", "1")) == "1"
                unknown = {k: v for k, v in payload.items() if k not in {"status", "info", "infocode"}}
                return response, ApiMeta("success" if ok else "error", self.provider, queried_at,
                    round((monotonic()-started)*1000), None if ok else str(payload.get("infocode", response.status_code)),
                    None if ok else str(payload.get("info", f"HTTP {response.status_code}")), unknown, payload)
            except Exception as exc:
                last_error = exc
                if attempt >= self.settings.max_retries: break
                time.sleep(self.settings.retry_backoff_seconds * (2 ** attempt))
        return None, ApiMeta("error", self.provider, queried_at, round((monotonic()-started)*1000),
                             "transport_error", str(last_error) if last_error else "request failed")

    @staticmethod
    def _place(x: dict[str, Any]) -> Place:
        return Place(x.get("id"), x.get("name", ""), x.get("address"), x.get("location"),
                     x.get("typecode"), x.get("city"), x.get("adname"), x)

    def search_pois(self, keywords: str, *, city: str | None = None, types: str | None = None,
                    page: int = 1, offset: int = 20) -> ApiResult[list[Place]]:
        if not keywords and not types: raise ValueError("keywords or types is required")
        params = {"keywords": keywords, "page_num": str(page), "page_size": str(min(offset, 25))}
        if city: params.update(region=city, city_limit="true")
        if types: params["types"] = types
        response, meta = self._request("/v5/place/text", params)
        return ApiResult(None, meta) if not meta.status == "success" or response is None else ApiResult(
            [self._place(x) for x in response.json_data.get("pois", [])], meta)

    def resolve_place(self, query: str, *, city: str | None = None) -> ApiResult[list[Place]]:
        return self.search_pois(query, city=city, offset=10)

    def nearby_pois(self, location: str, *, keywords: str = "美食", radius: int = 3000, city: str | None = None) -> ApiResult[list[Place]]:
        params = {"location": location, "keywords": keywords, "radius": str(radius), "page_size": "20", "page_num": "1"}
        if city: params.update(region=city, city_limit="true")
        response, meta = self._request("/v5/place/around", params)
        return ApiResult(None, meta) if meta.status != "success" or response is None else ApiResult(
            [self._place(x) for x in response.json_data.get("pois", [])], meta)

    def confirm_place(self, poi_id: str) -> ApiResult[list[Place]]:
        response, meta = self._request("/v5/place/detail", {"id": poi_id})
        return ApiResult(None, meta) if not meta.status == "success" or response is None else ApiResult(
            [self._place(x) for x in response.json_data.get("pois", [])], meta)

    def geocode(self, address: str, *, city: str | None = None) -> ApiResult[list[dict[str, Any]]]:
        params = {"address": address}
        if city: params["city"] = city
        response, meta = self._request("/v3/geocode/geo", params)
        return ApiResult(None, meta) if not meta.status == "success" or response is None else ApiResult(
            response.json_data.get("geocodes", []), meta)

    def route(self, origin: str, destination: str, *, mode: str = "driving", **options: str) -> ApiResult[Route]:
        if mode not in {"driving", "walking", "cycling", "transit"}: raise ValueError("unsupported route mode")
        params = {"origin": origin, "destination": destination, **options}
        if mode == "transit" and "city" not in params: raise ValueError("city is required for transit")
        path = "/v5/direction/transit/integrated" if mode == "transit" else f"/v5/direction/{mode}"
        response, meta = self._request(path, params)
        if not meta.status == "success" or response is None: return ApiResult(None, meta)
        route = response.json_data.get("route", {})
        paths = route.get("paths", []) or route.get("transits", [])
        first = paths[0] if paths else {}
        return ApiResult(Route(mode, origin, destination, _int(first.get("distance")), _int(first.get("duration")), paths, response.json_data), meta)

    @staticmethod
    def navigation_url(origin: str, destination: str, *, mode: str = "car", origin_name: str = "", destination_name: str = "") -> str:
        modes = {"driving":"car", "walking":"walk", "cycling":"ride", "car":"car", "walk":"walk", "ride":"ride"}
        if mode not in modes: raise ValueError("navigation mode must be car, walk, or ride")
        return "https://uri.amap.com/navigation?" + urllib.parse.urlencode({"from":origin,"fromName":origin_name,"to":destination,"toName":destination_name,"mode":modes[mode],"callnative":"0"})

def _int(value: Any) -> int | None:
    try: return int(value) if value is not None else None
    except (TypeError, ValueError): return None

