"""Meituan Maps POI search. The public map API supplies location fields, not shop media."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable


Transport = Callable[[str, float], tuple[int, dict[str, Any]]]


def _get(url: str, timeout: float) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class MeituanMaps:
    base_url = "https://lbsapi.meituan.com/v1/search"

    def __init__(self, key: str | None = None, transport: Transport = _get, timeout: float = 8.0):
        self.key = key if key is not None else os.getenv("MEITUAN_MAPS_KEY", "")
        self.transport = transport
        self.timeout = timeout

    def search(self, keywords: str, city: str | None = None) -> list[dict[str, Any]]:
        if not keywords.strip() or len(keywords) > 80:
            raise ValueError("请提供有效的搜索词")
        params = {"keywords": keywords, "page": "1", "pagesize": "20"}
        if city:
            params.update(city=city, citylimit="true")
        return self._request("text", params)

    def nearby(self, location: str, keywords: str, radius: int = 3000, city: str | None = None) -> list[dict[str, Any]]:
        params = {"location": location, "keywords": keywords, "radius": str(radius), "page": "1", "pagesize": "20"}
        if city:
            params["city"] = city
        return self._request("nearby", params)

    def _request(self, endpoint: str, params: dict[str, str]) -> list[dict[str, Any]]:
        if not self.key:
            raise ValueError("美团地点搜索暂未配置")
        url = f"{self.base_url}/{endpoint}?{urllib.parse.urlencode({**params, 'key': self.key})}"
        try:
            code, payload = self.transport(url, self.timeout)
        except Exception as exc:
            raise RuntimeError("地点服务暂时不可用") from exc
        if code != 200 or str(payload.get("status")) != "200":
            raise RuntimeError(str(payload.get("msg") or "地点服务返回错误"))
        return [self._place(p) for p in payload.get("pois", []) if isinstance(p, dict)]

    @staticmethod
    def _place(p: dict[str, Any]) -> dict[str, Any]:
        # The documented map response has no image, introduction, price or rating.
        provider_id = str(p.get("id") or "")
        return {"id": f"meituan:{provider_id}", "provider": "meituan_maps", "provider_id": provider_id,
                "name": p.get("name") or "未命名地点", "address": p.get("address") or None,
                "location": p.get("location"), "city": p.get("cityname"),
                "category": p.get("type"), "distance": p.get("distance"),
                "image_url": None, "description": None, "raw_data": p}
