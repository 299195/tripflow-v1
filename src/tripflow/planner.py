"""Deterministic V1 planner.

The planner never invents provider data.  POIs and route results are inputs;
when no route provider is configured it emits an explicitly labelled straight
line estimate, which is suitable for reproducible offline planning only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable

from .domain.errors import ValidationError


@dataclass(frozen=True, slots=True)
class PlanInput:
    city: str
    date: str
    poi_ids: list[str]
    pois: dict[str, dict[str, Any]]
    start: str = "09:00"
    end: str = "18:00"
    stay_minutes: dict[str, int] | None = None
    fixed_booking: dict[str, str] | None = None
    route_overrides: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class PlannedActivity:
    poi_id: str
    sequence: int
    starts_at: str
    ends_at: str
    title: str
    reservation_required: bool = False
    reservation_ref: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedLeg:
    from_poi_id: str
    to_poi_id: str
    duration_minutes: int
    distance_meters: int
    source: str


@dataclass(frozen=True, slots=True)
class PlanResult:
    status: str
    reason_code: str | None
    activities: list[PlannedActivity]
    legs: list[PlannedLeg]
    explanation: str


RouteProvider = Callable[[dict[str, Any], dict[str, Any]], tuple[int, int, str] | None]


class DeterministicPlanner:
    """Build a stable sequential schedule and enforce hard constraints."""

    def plan(self, request: PlanInput, route_provider: RouteProvider | None = None) -> PlanResult:
        try:
            day = date.fromisoformat(request.date)
            window_start = self._parse_time(request.start)
            window_end = self._parse_time(request.end)
        except ValueError as exc:
            raise ValidationError(f"invalid planning date/time: {exc}") from exc
        if window_end <= window_start:
            raise ValidationError("planning end must be after start")
        if not request.poi_ids:
            raise ValidationError("at least one poi_id is required")
        if len(request.poi_ids) > 8:
            raise ValidationError("V1 supports at most 8 stops")
        missing = [p for p in request.poi_ids if p not in request.pois]
        if missing:
            raise ValidationError(f"missing POI records: {', '.join(missing)}")
        stays = request.stay_minutes or {}
        fixed = request.fixed_booking or {}
        cursor = datetime.combine(day, window_start)
        window_end_dt = datetime.combine(day, window_end)
        activities: list[PlannedActivity] = []
        legs: list[PlannedLeg] = []
        for index, poi_id in enumerate(request.poi_ids, 1):
            poi = request.pois[poi_id]
            duration = int(stays.get(poi_id, 90))
            if duration <= 0:
                raise ValidationError("stay duration must be positive")
            booking = fixed.get(poi_id) if isinstance(fixed, dict) else None
            if booking:
                booking_start = self._parse_datetime(day, booking["start"])
                booking_end = self._parse_datetime(day, booking["end"])
                if booking_end <= booking_start:
                    raise ValidationError("fixed booking end must be after start")
                if booking_start < cursor:
                    raise ValidationError("fixed booking conflicts with preceding activity")
                if booking_end > window_end_dt:
                    raise ValidationError("fixed booking is outside planning window")
                cursor = booking_start
            start_dt = cursor
            end_dt = start_dt + timedelta(minutes=duration)
            if booking:
                booking_end = self._parse_datetime(day, booking["end"])
                if end_dt > booking_end:
                    raise ValidationError("activity exceeds fixed booking window")
                end_dt = booking_end
            if end_dt > window_end_dt:
                raise ValidationError("stay exceeds planning window")
            activities.append(PlannedActivity(
                poi_id, index, start_dt.isoformat(timespec="minutes"),
                end_dt.isoformat(timespec="minutes"), str(poi.get("name", poi_id)),
                bool(booking), booking.get("reservation_ref") if isinstance(booking, dict) else None,
            ))
            cursor = end_dt
            if index < len(request.poi_ids):
                next_poi = request.pois[request.poi_ids[index]]
                override = (request.route_overrides or {}).get(f"{poi_id}->{request.poi_ids[index]}")
                if override == "ROUTE_UNAVAILABLE":
                    raise ValidationError("route unavailable")
                route = route_provider(poi, next_poi) if route_provider else None
                if route is None:
                    duration_m, distance_m, source = self._estimate(poi, next_poi)
                else:
                    duration_m, distance_m, source = route
                cursor += timedelta(minutes=duration_m)
                if cursor > window_end_dt:
                    raise ValidationError("travel time leaves no feasible itinerary")
                legs.append(PlannedLeg(poi_id, request.poi_ids[index], duration_m, distance_m, source))
        return PlanResult("feasible", None, activities, legs, "deterministic schedule validated")

    @staticmethod
    def _parse_time(value: str) -> time:
        return time.fromisoformat(value)

    @staticmethod
    def _parse_datetime(day: date, value: str) -> datetime:
        return datetime.combine(day, time.fromisoformat(value))

    @staticmethod
    def _estimate(a: dict[str, Any], b: dict[str, Any]) -> tuple[int, int, str]:
        try:
            lat1, lon1 = float(a["latitude"]), float(a["longitude"])
            lat2, lon2 = float(b["latitude"]), float(b["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("POI location is required for route estimation") from exc
        earth = 6_371_000
        x = radians(lon2 - lon1) * cos(radians((lat1 + lat2) / 2))
        y = radians(lat2 - lat1)
        distance = int(earth * sqrt(x * x + y * y))
        return max(5, int(round(distance / 250))), distance, "deterministic_straight_line_estimate"
