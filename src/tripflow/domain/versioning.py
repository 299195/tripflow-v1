from __future__ import annotations

from copy import deepcopy

from .entities import Activity, Itinerary, ItineraryVersion, TravelLeg
from .enums import ActivityStatus, ItineraryStatus, TravelMode
from .errors import ValidationError


class ItineraryVersionService:
    """Creates immutable snapshots and restores them as new versions."""

    def create(self, itinerary: Itinerary, change_reason: str) -> ItineraryVersion:
        next_number = self._next_number(itinerary)
        version = ItineraryVersion(
            itinerary_id=itinerary.id,
            version_number=next_number,
            change_reason=change_reason,
            snapshot_data=deepcopy(itinerary.snapshot()),
        )
        itinerary.current_version_id = version.id
        return version

    def restore(self, itinerary: Itinerary, source: ItineraryVersion, change_reason: str) -> ItineraryVersion:
        if source.itinerary_id != itinerary.id:
            raise ValidationError("version belongs to another itinerary")
        snapshot = deepcopy(source.snapshot_data)
        itinerary_data = snapshot.get("itinerary", {})
        itinerary.name = itinerary_data.get("name", itinerary.name)
        itinerary.status = ItineraryStatus(itinerary_data.get("status", itinerary.status.value))
        itinerary.activities = [
            Activity(
                itinerary_id=item["itinerary_id"], poi_id=item["poi_id"], sequence=item["sequence"],
                starts_at=item["starts_at"], ends_at=item["ends_at"], id=item["id"], title=item.get("title", ""),
                status=ActivityStatus(item.get("status", ActivityStatus.PLANNED.value)),
                reservation_required=item.get("reservation_required", False),
                reservation_ref=item.get("reservation_ref"), note=item.get("note"),
            )
            for item in snapshot.get("activities", [])
        ]
        itinerary.travel_legs = [
            TravelLeg(
                itinerary_id=item["itinerary_id"], from_activity_id=item["from_activity_id"],
                to_activity_id=item["to_activity_id"], mode=TravelMode(item["mode"]),
                duration_minutes=item["duration_minutes"], distance_meters=item["distance_meters"],
                id=item["id"], route_data=item.get("route_data", {}),
            )
            for item in snapshot.get("travel_legs", [])
        ]
        return self.create_with_origin(itinerary, change_reason, source.id)

    def create_with_origin(self, itinerary: Itinerary, change_reason: str, origin_id: str) -> ItineraryVersion:
        version = ItineraryVersion(
            itinerary_id=itinerary.id,
            version_number=self._next_number(itinerary),
            change_reason=change_reason,
            snapshot_data=deepcopy(itinerary.snapshot()),
            restored_from_version_id=origin_id,
        )
        itinerary.current_version_id = version.id
        return version

    @staticmethod
    def _next_number(itinerary: Itinerary) -> int:
        current = itinerary.version_count
        itinerary.version_count = current + 1
        return current + 1
