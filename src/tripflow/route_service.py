"""RouteProvider implementations used by the deterministic planner.

This module is deliberately small: the Amap adapter owns HTTP and response
parsing, while this module translates its result into the planner contract.
The planner never needs to know how a provider authenticates or serializes a
route response.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from tripflow_amap import AmapAdapter
from tripflow_amap.models import now_utc

from .planner import DeterministicPlanner, RouteProviderResult, RouteResult


class RouteProviderUnavailable(RuntimeError):
    """Raised when no explicit fallback estimate is allowed."""


@dataclass(slots=True)
class CachedRouteProvider:
    provider: Any
    db: Any
    ttl_minutes: int = 30

    def __call__(self, origin: dict[str, Any], destination: dict[str, Any]):
        origin_location = _poi_location(origin)
        destination_location = _poi_location(destination)
        raw_key = f"{origin_location}|{destination_location}|{getattr(self.provider, 'mode', 'walking')}"
        key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        row = self.db.connection.execute("SELECT * FROM route_cache WHERE cache_key=? AND expires_at>?", (key, now.isoformat())).fetchone()
        if row:
            payload = json.loads(row["route_json"])
            return RouteResult(payload["duration_minutes"], payload["distance_meters"], row["source"], payload.get("mode", row["mode"]), payload.get("raw_summary", {}), row["fetched_at"], bool(payload.get("estimated", False)))
        result = self.provider(origin, destination)
        self.db.connection.execute("INSERT OR REPLACE INTO route_cache(cache_key,origin,destination,mode,provider,distance_meters,duration_minutes,source,fetched_at,expires_at,route_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (key, origin_location, destination_location, getattr(self.provider, "mode", "walking"), "amap", result.distance_meters, result.duration_minutes, result.source, result.fetched_at or now.isoformat(), (now + timedelta(minutes=self.ttl_minutes)).isoformat(), json.dumps({"duration_minutes": result.duration_minutes, "distance_meters": result.distance_meters, "mode": result.mode, "raw_summary": result.raw_summary, "estimated": result.estimated}, ensure_ascii=False)))
        self.db.connection.commit()
        return result


@dataclass(frozen=True, slots=True)
class AmapRouteProvider:
    """Map an :class:`AmapAdapter` route call to a planner RouteProvider.

    The default mode is walking because V2's first real-route path is walking.
    An upstream failure can produce a clearly labelled deterministic estimate
    when ``allow_estimate`` is enabled.  The error is retained in the bounded
    ``raw_summary`` so the fallback is observable and never looks like Amap.
    """

    adapter: AmapAdapter
    mode: str = "walking"
    allow_estimate: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"walking", "driving", "cycling", "transit"}:
            raise ValueError(f"unsupported route mode: {self.mode}")

    def __call__(self, origin: dict[str, Any], destination: dict[str, Any]) -> RouteProviderResult:
        origin_location = _poi_location(origin)
        destination_location = _poi_location(destination)
        try:
            result = self.adapter.route(
                origin_location,
                destination_location,
                mode=self.mode,
                **_route_options(origin, destination),
            )
        except Exception as exc:
            return self._fallback(
                origin,
                destination,
                _error_summary("transport_error", str(exc)),
                fetched_at=now_utc().isoformat(),
            )

        route = result.data
        if result.ok and route is not None and route.duration_s is not None and route.distance_m is not None:
            path = route.paths[0] if route.paths else {}
            return RouteResult(
                duration_minutes=max(0, _ceil_minutes(route.duration_s)),
                distance_meters=max(0, route.distance_m),
                source="amap",
                mode=self.mode,
                raw_summary={
                    "provider": result.meta.provider,
                    "status": result.meta.status,
                    "infocode": result.meta.error_code or "10000",
                    "path_count": len(route.paths),
                    "selected_path": {
                        "distance": path.get("distance"),
                        "duration": path.get("duration"),
                        "step_count": len(path.get("steps", []) or []),
                    },
                    "unknown_fields": sorted(result.meta.unknown),
                },
                fetched_at=result.meta.queried_at.isoformat(),
                estimated=False,
            )

        error = _error_summary(
            result.meta.error_code or "route_error",
            result.meta.error_message or "Amap returned no usable route",
        )
        return self._fallback(
            origin,
            destination,
            error,
            fetched_at=result.meta.queried_at.isoformat(),
        )

    def _fallback(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        error: dict[str, Any],
        *,
        fetched_at: str,
    ) -> RouteResult:
        if not self.allow_estimate:
            raise RouteProviderUnavailable(str(error.get("message", "route provider unavailable")))
        duration, distance, _ = DeterministicPlanner._estimate(origin, destination)
        return RouteResult(
            duration_minutes=duration,
            distance_meters=distance,
            source="estimate:straight_line_after_amap_failure",
            mode=self.mode,
            raw_summary={
                "provider": "amap",
                "status": "fallback_estimate",
                "fallback": error,
                "estimation_method": "straight_line_distance_at_250m_per_minute",
            },
            fetched_at=fetched_at,
            estimated=True,
        )


def _poi_location(poi: dict[str, Any]) -> str:
    value = poi.get("location")
    if value:
        return str(value)
    try:
        return f"{float(poi['longitude']):.6f},{float(poi['latitude']):.6f}"
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("POI location is required for Amap route lookup") from exc


def _route_options(origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, str]:
    options: dict[str, str] = {}
    # Amap accepts origin/destination as coordinate strings.  Names are not
    # needed for route calculation and are intentionally not sent upstream.
    return options


def _ceil_minutes(duration_seconds: int) -> int:
    return max(1, (int(duration_seconds) + 59) // 60)


def _error_summary(code: str, message: str) -> dict[str, Any]:
    return {"code": str(code), "message": str(message)[:240]}
