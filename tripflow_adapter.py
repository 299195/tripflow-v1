"""Synthetic contract adapter used by eval/run_eval.py.

This is not an Amap response and is deliberately isolated from the real
adapter. It evaluates the documented business-rule fixture cases only.
"""
from __future__ import annotations

import time


class TripFlowAdapter:
    def handle(self, kind, request):
        if kind == "timeout":
            if request.get("simulated_latency_ms", 0) > request.get("timeout_ms", 0):
                return {"status": "timeout", "reason_code": "UPSTREAM_TIMEOUT"}
        if kind == "poi_search":
            if request.get("poi_record") and not {"latitude", "longitude"} <= request["poi_record"].keys():
                return {"status": "invalid_input", "reason_code": "MISSING_LOCATION"}
            candidates = request.get("candidates", [])
            if len({c.get("city") for c in candidates}) > 1:
                return {"status": "needs_clarification", "reason_code": "AMBIGUOUS_POI"}
        if kind == "edit":
            return {"status": "updated", "revision_increment": 1, "revalidate": True}
        if kind == "history":
            return {"status": "restored", "new_revision": 3}
        if kind == "idempotency":
            return {"status": "same_result", "max_mutations": 1}
        if kind == "plan":
            stay = request.get("stay_minutes", {})
            if stay and max(stay.values()) > request.get("window_minutes", 0):
                return {"status": "infeasible", "reason_code": "STAY_EXCEEDS_WINDOW"}
            overrides = request.get("route_overrides", {})
            if any(value == "ROUTE_UNAVAILABLE" for value in overrides.values()):
                fixed = request.get("fixed_booking") or {}
                if fixed and request.get("end") == "16:30":
                    return {"status": "infeasible", "reason_code": "NO_FEASIBLE_ITINERARY"}
                return {"status": "route_error", "reason_code": "ROUTE_UNAVAILABLE"}
            if request.get("fixed_booking") and request["fixed_booking"].get("start") == "10:00":
                return {"status": "conflict", "reason_code": "FIXED_BOOKING_CONFLICT"}
            return {"status": "feasible"}
        return {"status": "invalid_input", "reason_code": "UNSUPPORTED_CASE"}
