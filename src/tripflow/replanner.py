from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


class Replanner:
    """Create bounded candidate snapshots without mutating the database."""

    def build(self, activities: list[dict[str, Any]], event: dict[str, Any], replacement_pois: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        target = event.get("activity_id")
        index = next((i for i, item in enumerate(activities) if item["id"] == target), None)
        if index is None:
            raise ValueError("activity_id is required and must belong to the itinerary")
        replacement_pois = replacement_pois or {}
        candidates = []
        if event["event_type"] == "delayed":
            delay = int(event.get("delay_minutes", 0))
            candidates.append(self._shift(activities, index, delay, "延误后顺延"))
            candidates.append(self._drop(activities, index, "延误后跳过当前地点"))
        elif event["event_type"] in {"closed", "skipped"}:
            candidates.append(self._drop(activities, index, "移除不可用地点"))
        for replacement_id in event.get("replacement_poi_ids", []):
            if replacement_id in replacement_pois:
                candidates.append(self._replace(activities, index, replacement_pois[replacement_id], "替换不可用地点"))
        unique = []
        seen = set()
        for option in candidates:
            signature = tuple((a["poi_id"], a["starts_at"], a["ends_at"]) for a in option["activities"])
            if signature not in seen:
                seen.add(signature)
                unique.append(option)
        return unique[:3]

    @staticmethod
    def _shift(activities, index, minutes, reason):
        result = [dict(a) for a in activities]
        for i in range(index, len(result)):
            result[i]["starts_at"] = (datetime.fromisoformat(result[i]["starts_at"]) + timedelta(minutes=minutes)).isoformat(timespec="minutes")
            result[i]["ends_at"] = (datetime.fromisoformat(result[i]["ends_at"]) + timedelta(minutes=minutes)).isoformat(timespec="minutes")
        return {"reason": reason, "activities": result, "warnings": ["后续活动整体顺延，请确认末站是否超出时间窗"]}

    @staticmethod
    def _drop(activities, index, reason):
        result = [dict(a) for i, a in enumerate(activities) if i != index]
        for seq, activity in enumerate(result, 1):
            activity["sequence"] = seq
        return {"reason": reason, "activities": result, "warnings": ["当前地点被移除，后续路线需要重新获取"]}

    @staticmethod
    def _replace(activities, index, poi, reason):
        result = [dict(a) for a in activities]
        result[index].update({"poi_id": poi["id"], "title": poi.get("name", poi["id"])})
        return {"reason": reason, "activities": result, "warnings": ["替换地点后的路线需要重新获取"]}
