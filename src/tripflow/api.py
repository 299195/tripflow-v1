"""FastAPI HTTP boundary for TripFlow V1.

The module intentionally keeps request bodies as dictionaries so the service
layer remains usable without Pydantic/FastAPI installed (for offline tests).
"""
from __future__ import annotations

import os
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .service import TripFlowService
from .domain.errors import ValidationError
from .v2_schemas import ExecutionEventRequest, FeedbackRequest, ReplanConfirmRequest, ReplanPreviewRequest
from .route_service import RouteProviderUnavailable


def create_app(service: TripFlowService | None = None):
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:  # clear error for the documented optional runtime
        raise RuntimeError("FastAPI is not installed; run: python -m pip install -e .") from exc

    app = FastAPI(title="TripFlow V1 API", version="0.1.0", description="Single-user, single-city deterministic travel planning API")
    runtime = service or TripFlowService(os.getenv("TRIPFLOW_DB", "tripflow.db"))

    import asyncio
    db_request_lock = asyncio.Lock()
    @app.middleware("http")
    async def serialize_single_user_requests(request, call_next):
        async with db_request_lock:
            return await call_next(request)

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(422, {"status": "invalid_input", "detail": str(exc)}) from exc
        except RouteProviderUnavailable as exc:
            raise HTTPException(502, {"status": "route_unavailable", "detail": str(exc)}) from exc

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "tripflow", "version": "0.1.0", "amap_configured": bool(os.getenv("AMAP_API_KEY")), "meituan_configured": bool(os.getenv("MEITUAN_MAPS_KEY")), "qwen": runtime.agent.status()}

    @app.get("/api/v1/pois/search")
    def search_pois(query: str, city: str | None = None) -> dict[str, Any]:
        warning = None
        if os.getenv("MEITUAN_MAPS_KEY"):
            from .meituan import MeituanMaps
            try:
                return {"status": "success", "provider": "meituan_maps", "data": MeituanMaps().search(query, city)}
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except RuntimeError as exc:
                warning = f"美团地点服务不可用：{exc}；以下为高德地点结果"
        if warning:
            local = []
        else:
            local = runtime.search_pois(query, city)
        if local:
            return {"status": "success", "provider": "local", "data": local}
        try:
            from tripflow_amap import AmapAdapter, AmapSettings
            result = AmapAdapter(AmapSettings.from_env()).search_pois(query, city=city)
            if not result.ok:
                raise HTTPException(502, {"status": result.meta.status, "provider": result.meta.provider, "error_code": result.meta.error_code, "error_message": result.meta.error_message, "unknown": result.meta.unknown})
            return {"status": "success", "provider": result.meta.provider, "data": [asdict(p) for p in result.data or []], "meta": asdict(result.meta), "warning": warning}
        except ValueError as exc:
            raise HTTPException(503, {"status": "not_configured", "detail": str(exc)}) from exc

    @app.get("/api/v1/pois/nearby")
    def nearby_pois(location: str, category: str = "美食", radius: int = 3000, city: str | None = None) -> dict[str, Any]:
        if category not in {"美食", "景点", "休闲娱乐", "咖啡", "酒店"} or not 100 <= radius <= 20000:
            raise HTTPException(422, "无效的类别或搜索范围")
        try:
            longitude, latitude = [float(v) for v in location.split(",")]
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                raise ValueError("invalid location")
            warning = None
            use_meituan = bool(os.getenv("MEITUAN_MAPS_KEY"))
            if use_meituan:
                from .meituan import MeituanMaps
                try:
                    return {"status": "success", "provider": "meituan_maps", "data": MeituanMaps().nearby(location, category, radius, city)}
                except RuntimeError as exc:
                    warning = f"美团地点服务不可用：{exc}；以下为高德地点结果"
            from tripflow_amap import AmapAdapter, AmapSettings
            result = AmapAdapter(AmapSettings.from_env()).nearby_pois(location, keywords=category, radius=radius, city=city)
            if not result.ok:
                raise HTTPException(502, {"status": result.meta.status, "error_message": result.meta.error_message})
            return {"status": "success", "provider": result.meta.provider, "data": [asdict(p) for p in result.data or []], "warning": warning}
        except ValueError as exc:
            raise HTTPException(422, "请输入有效的经度,纬度并配置地图服务") from exc

    @app.get("/api/v1/pois/{poi_id}")
    def confirm_poi(poi_id: str) -> dict[str, Any]:
        try:
            return {"status": "confirmed", "provider": "local", "data": runtime.confirm_poi(poi_id)}
        except KeyError:
            try:
                from tripflow_amap import AmapAdapter, AmapSettings
                result = AmapAdapter(AmapSettings.from_env()).confirm_place(poi_id)
                if not result.ok:
                    raise HTTPException(502, {"status": result.meta.status, "provider": result.meta.provider, "error_code": result.meta.error_code, "error_message": result.meta.error_message, "unknown": result.meta.unknown})
                return {"status": "success", "provider": result.meta.provider, "data": [asdict(p) for p in result.data or []], "meta": asdict(result.meta)}
            except ValueError as exc:
                raise HTTPException(503, {"status": "not_configured", "detail": str(exc)}) from exc

    @app.post("/api/v1/trips", status_code=201)
    def create_trip(body: dict[str, Any]) -> dict[str, Any]:
        return call(runtime.create_trip, body)

    @app.post("/api/v1/pois", status_code=201)
    def save_poi(body: dict[str, Any]) -> dict[str, Any]:
        return call(runtime.save_poi, body)

    @app.post("/api/v1/users/{user_id}/favorites", status_code=201)
    def favorite(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return call(runtime.favorite, user_id, body)

    @app.get("/api/v1/users/{user_id}/profile")
    def profile(user_id: str) -> dict[str, Any]:
        return call(runtime.profile, user_id)

    @app.post("/api/v1/guides/draft")
    def draft_guide(body: dict[str, Any]) -> dict[str, Any]:
        message = str(body.get("message", "")).strip()
        city = str(body.get("city", "")).strip()
        if not message or not city:
            raise HTTPException(422, "请填写目的地城市与旅行想法")
        try:
            guide = runtime.agent.draft_guide(message, city)
            mode = "assisted"
        except Exception:
            guide = {"title": f"{city}一日旅行灵感", "summary": "先从当地景点、美食和休闲地点中挑选，再安排适合自己的路线。", "style": "自由探索", "place_queries": [f"{city}景点", f"{city}美食", f"{city}咖啡"], "tips": ["出发前确认开放时间与预约要求"]}
            mode = "basic"
        candidates = []
        try:
            use_meituan = bool(os.getenv("MEITUAN_MAPS_KEY"))
            if use_meituan:
                from .meituan import MeituanMaps
                adapter = MeituanMaps()
            else:
                from tripflow_amap import AmapAdapter, AmapSettings
                adapter = AmapAdapter(AmapSettings.from_env())
            for query in guide["place_queries"]:
                if use_meituan:
                    places = adapter.search(query, city)
                else:
                    result = adapter.search_pois(query, city=city, offset=3)
                    places = [asdict(p) for p in result.data or []] if result.ok else []
                if places:
                    candidates.append({"query": query, "place": places[0], "verified": True})
                else:
                    candidates.append({"query": query, "place": None, "verified": False})
        except (ValueError, RuntimeError):
            candidates = [{"query": q, "place": None, "verified": False} for q in guide["place_queries"]]
        agent_trace = runtime.coordinator.run(itinerary_id=None, message=message, city=city, candidates=candidates)
        return {"status": "draft", "city": city, "guide": guide, "candidates": candidates, "saved": False, "mode": mode, "agent_trace": agent_trace}

    @app.post("/api/v1/trips/{trip_id}/itinerary/generate")
    def generate(trip_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return call(runtime.generate_itinerary, trip_id, body)

    @app.get("/api/v1/itineraries/{itinerary_id}")
    def itinerary(itinerary_id: str) -> dict[str, Any]:
        return call(runtime.get_itinerary, itinerary_id)

    @app.patch("/api/v1/itineraries/{itinerary_id}")
    def edit(itinerary_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return call(runtime.edit_itinerary, itinerary_id, body)

    @app.get("/api/v1/itineraries/{itinerary_id}/versions")
    def versions(itinerary_id: str) -> dict[str, Any]:
        return {"data": call(runtime.list_versions, itinerary_id)}

    @app.post("/api/v1/itineraries/{itinerary_id}/restore")
    def restore(itinerary_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return call(runtime.restore_version, itinerary_id, body["version_id"], body.get("change_reason", "恢复历史版本"))

    @app.post("/api/v1/itineraries/{itinerary_id}/execution-events", status_code=201)
    def execution_event(itinerary_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return call(runtime.execution_event, itinerary_id, body)

    @app.post("/api/v2/itineraries/{itinerary_id}/replan/preview")
    def replan_preview(itinerary_id: str, body: ReplanPreviewRequest) -> dict[str, Any]:
        return call(runtime.preview_replan, itinerary_id, body.model_dump())

    @app.post("/api/v2/itineraries/{itinerary_id}/replan/confirm")
    def replan_confirm(itinerary_id: str, body: ReplanConfirmRequest) -> dict[str, Any]:
        return call(runtime.confirm_replan, itinerary_id, body.model_dump())

    @app.get("/api/v2/itineraries/{itinerary_id}/versions/diff")
    def version_diff(itinerary_id: str, left_version_id: str, right_version_id: str) -> dict[str, Any]:
        return call(runtime.diff_versions, itinerary_id, left_version_id, right_version_id)

    @app.get("/api/v2/itineraries/{itinerary_id}/agent-runs")
    def agent_runs(itinerary_id: str) -> dict[str, Any]:
        return {"data": call(runtime.list_agent_runs, itinerary_id)}

    @app.post("/api/v2/itineraries/{itinerary_id}/feedback", status_code=201)
    def feedback(itinerary_id: str, body: FeedbackRequest, user_id: str = "local-traveler") -> dict[str, Any]:
        return call(runtime.record_feedback, user_id, itinerary_id, body.model_dump())

    @app.post("/api/v2/itineraries/{itinerary_id}/execution-events", status_code=201)
    def v2_execution_event(itinerary_id: str, body: ExecutionEventRequest) -> dict[str, Any]:
        data = body.model_dump()
        stored = dict(data)
        if stored["event_type"] in {"delayed", "closed"}:
            stored["note"] = json.dumps({"event_type": stored["event_type"], "delay_minutes": stored.get("delay_minutes", 0), "note": stored.get("note")}, ensure_ascii=False)
            stored["event_type"] = "note"
        event = call(runtime.execution_event, itinerary_id, stored)
        event["event_type"] = data["event_type"]
        if data["event_type"] in {"delayed", "closed", "skipped"}:
            event["replan_preview"] = call(runtime.preview_replan, itinerary_id, data)
        return event

    # Zero-build mobile web client. API routes are declared before the mount,
    # so the static fallback cannot shadow the backend endpoints.
    from fastapi.staticfiles import StaticFiles
    static_dir = Path(__file__).resolve().parents[2] / "frontend"
    if static_dir.is_dir():
        from fastapi.responses import FileResponse
        @app.get("/", include_in_schema=False)
        def product_home():
            return FileResponse(static_dir / "product.html")
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def run() -> None:
    import uvicorn
    uvicorn.run("tripflow.api:create_app", factory=True, host=os.getenv("TRIPFLOW_HOST", "127.0.0.1"), port=int(os.getenv("TRIPFLOW_PORT", "8000")), reload=False)


try:
    app = create_app() if os.getenv("TRIPFLOW_IMPORT_APP", "0") == "1" else None
except RuntimeError:
    app = None
