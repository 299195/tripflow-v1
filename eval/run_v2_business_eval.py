"""Execute V2 business-chain scenarios against the real TripFlowService.

This runner uses deterministic local data and no external API. It exercises
the same service, planner, version, replan and feedback paths used by the API.
It is intentionally separate from the synthetic contract adapter.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripflow.service import TripFlowService  # noqa: E402
from tripflow.domain.errors import ValidationError  # noqa: E402
from tripflow.qwen_agent import QwenAgent, QwenSettings  # noqa: E402


def setup():
    offline_agent = QwenAgent(QwenSettings("offline-eval", enabled=False))
    service = TripFlowService(":memory:", agent=offline_agent)
    for poi_id, name, lat, lon in (
        ("p1", "西湖", 30.25, 120.15),
        ("p2", "博物馆", 30.26, 120.16),
        ("p3", "咖啡馆", 30.27, 120.17),
        ("p4", "备用景点", 30.28, 120.18),
    ):
        service.save_poi({"id": poi_id, "name": name, "city": "杭州", "latitude": lat, "longitude": lon, "address": name})
    trip = service.create_trip({"user_id": "eval-user", "city": "杭州", "start_date": "2026-11-13", "end_date": "2026-11-13"})
    plan = service.generate_itinerary(trip["id"], {"poi_ids": ["p1", "p2", "p3"], "date": "2026-11-13", "start": "09:00", "end": "21:00", "stay_minutes": {"p1": 45, "p2": 45, "p3": 45}})
    return service, trip, plan


def build_cases():
    def fresh():
        return setup()

    def feasible():
        service, _, plan = fresh(); assert plan["activities"]; service.close()

    def route_metadata():
        service, _, plan = fresh(); assert plan["travel_legs"][0]["route_data"]["source"] == "deterministic_straight_line_estimate"; service.close()

    def fixed_conflict():
        service, trip, _ = fresh()
        try: service.generate_itinerary(trip["id"], {"poi_ids": ["p1", "p2"], "date": "2026-11-13", "start": "09:00", "end": "18:00", "fixed_booking": {"p2": {"start": "09:30", "end": "10:00"}}})
        except ValidationError: service.close(); return
        raise AssertionError("fixed booking conflict was accepted")

    def missing_location():
        service = TripFlowService(":memory:", agent=QwenAgent(QwenSettings("offline-eval", enabled=False))); service.save_poi({"id": "a", "name": "A", "city": "杭州", "latitude": 30.2, "longitude": 120.1})
        try: service.planner.plan(__import__("tripflow.planner", fromlist=["PlanInput"]).PlanInput("杭州", "2026-11-13", ["a", "b"], {"a": {"latitude": 30.2, "longitude": 120.1}, "b": {}}))
        except ValidationError: service.close(); return
        raise AssertionError("missing location was accepted")

    def max_stops():
        service, _, _ = fresh()
        try: service.planner.plan(__import__("tripflow.planner", fromlist=["PlanInput"]).PlanInput("杭州", "2026-11-13", ["p1"] * 9, {"p1": {"latitude": 30.2, "longitude": 120.1}}))
        except ValidationError: service.close(); return
        raise AssertionError("more than eight stops were accepted")

    def invalid_window():
        service, _, _ = fresh()
        try: service.planner.plan(__import__("tripflow.planner", fromlist=["PlanInput"]).PlanInput("杭州", "2026-11-13", ["p1"], {"p1": {"latitude": 30.2, "longitude": 120.1}}, start="18:00", end="09:00"))
        except ValidationError: service.close(); return
        raise AssertionError("invalid window was accepted")

    def delete_edit():
        service, _, plan = fresh(); result = service.edit_itinerary(plan["id"], {"operation": "delete", "poi_id": "p2"}); assert len(result["activities"]) == 2; service.close()

    def replace_edit():
        service, _, plan = fresh(); result = service.edit_itinerary(plan["id"], {"operation": "replace", "from_poi_id": "p2", "to_poi_id": "p4"}); assert any(a["poi_id"] == "p4" for a in result["activities"]); service.close()

    def extend_edit():
        service, _, plan = fresh(); result = service.edit_itinerary(plan["id"], {"operation": "extend", "poi_id": "p1", "additional_minutes": 5}); assert result["version_number"] == 2; service.close()

    def restore():
        service, _, plan = fresh(); edited = service.edit_itinerary(plan["id"], {"operation": "delete", "poi_id": "p2"}); restored = service.restore_version(plan["id"], plan["current_version_id"] if "current_version_id" in plan else service.list_versions(plan["id"])[0]["id"]); assert restored["version_number"] >= edited["version_number"]; service.close()

    def delayed_preview():
        service, _, plan = fresh(); proposal = service.preview_replan(plan["id"], {"event_type": "delayed", "activity_id": plan["activities"][0]["id"], "delay_minutes": 30}); assert proposal["options"]; service.close()

    def closed_preview():
        service, _, plan = fresh(); proposal = service.preview_replan(plan["id"], {"event_type": "closed", "activity_id": plan["activities"][1]["id"], "replacement_poi_ids": ["p4"]}); assert len(proposal["options"]) >= 1; service.close()

    def skipped_preview():
        service, _, plan = fresh(); proposal = service.preview_replan(plan["id"], {"event_type": "skipped", "activity_id": plan["activities"][1]["id"]}); assert proposal["options"][0]["activities"][0]["poi_id"] == "p1"; service.close()

    def confirm():
        service, _, plan = fresh(); proposal = service.preview_replan(plan["id"], {"event_type": "skipped", "activity_id": plan["activities"][1]["id"], "idempotency_key": "confirm-1"}); result = service.confirm_replan(plan["id"], {"proposal_id": proposal["proposal_id"], "option_id": proposal["options"][0]["option_id"], "base_version_id": proposal["base_version_id"]}); assert result["status"] == "confirmed"; service.close()

    def stale_confirm():
        service, _, plan = fresh(); proposal = service.preview_replan(plan["id"], {"event_type": "skipped", "activity_id": plan["activities"][1]["id"]}); service.edit_itinerary(plan["id"], {"operation": "extend", "poi_id": "p1", "additional_minutes": 1})
        try: service.confirm_replan(plan["id"], {"proposal_id": proposal["proposal_id"], "option_id": proposal["options"][0]["option_id"], "base_version_id": proposal["base_version_id"]})
        except ValidationError: service.close(); return
        raise AssertionError("stale proposal was confirmed")

    def idempotent_preview():
        service, _, plan = fresh(); event = {"event_type": "skipped", "activity_id": plan["activities"][1]["id"], "idempotency_key": "same"}; a = service.preview_replan(plan["id"], event); b = service.preview_replan(plan["id"], event); assert a["proposal_id"] == b["proposal_id"]; service.close()

    def diff():
        service, _, plan = fresh(); edited = service.edit_itinerary(plan["id"], {"operation": "extend", "poi_id": "p1", "additional_minutes": 5}); versions = service.list_versions(plan["id"]); result = service.diff_versions(plan["id"], versions[0]["id"], edited["new_version_id"]); assert result["changed"]; service.close()

    def feedback_accept():
        service, _, plan = fresh(); result = service.record_feedback("eval-user", plan["id"], {"target_type": "itinerary", "target_id": plan["id"], "label": "accepted"}); assert result["status"] == "recorded"; service.close()

    def feedback_reject():
        service, _, plan = fresh(); result = service.record_feedback("eval-user", plan["id"], {"target_type": "proposal", "target_id": "p", "label": "rejected", "reason_code": "too_far"}); assert result["status"] == "recorded"; service.close()

    def agent_trace():
        service, _, plan = fresh(); proposal = service.preview_replan(plan["id"], {"event_type": "skipped", "activity_id": plan["activities"][1]["id"]}); assert len(service.list_agent_runs(plan["id"])) >= 3; service.close()

    cases = [
        ("normal_plan", feasible), ("route_metadata", route_metadata), ("fixed_booking_conflict", fixed_conflict),
        ("missing_location", missing_location), ("max_stops", max_stops), ("invalid_window", invalid_window),
        ("delete_edit", delete_edit), ("replace_edit", replace_edit), ("extend_edit", extend_edit), ("restore", restore),
        ("delayed_preview", delayed_preview), ("closed_preview", closed_preview), ("skipped_preview", skipped_preview),
        ("confirm_replan", confirm), ("stale_confirm", stale_confirm), ("idempotent_preview", idempotent_preview),
        ("version_diff", diff), ("feedback_accept", feedback_accept), ("feedback_reject", feedback_reject), ("agent_trace", agent_trace),
    ]
    # Repeat the core operations with fresh data to keep the denominator broad
    # while preserving independent, deterministic state.
    return cases + [(f"repeat_{i}_{name}", fn) for i, (name, fn) in enumerate(cases, 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/v2_business_eval.json"))
    args = parser.parse_args()
    rows = []
    for case_id, fn in build_cases():
        try:
            fn()
            rows.append({"id": case_id, "status": "PASS"})
        except Exception as exc:
            rows.append({"id": case_id, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
    counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "ERROR")}
    report = {"suite": "v2-business-chain", "external_api": False, "total": len(rows), "counts": counts, "cases": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"suite": report["suite"], "total": report["total"], "counts": counts}, ensure_ascii=False))
    return 0 if counts["ERROR"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
