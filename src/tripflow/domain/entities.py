from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from .enums import ActivityStatus, ExecutionEventType, ItineraryStatus, TravelMode, TripStatus
from .errors import ValidationError
from .state_machine import transition


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


TRIP_TRANSITIONS = {
    TripStatus.DRAFT: frozenset({TripStatus.PLANNING, TripStatus.CANCELLED}),
    TripStatus.PLANNING: frozenset({TripStatus.READY, TripStatus.DRAFT, TripStatus.CANCELLED}),
    TripStatus.READY: frozenset({TripStatus.IN_PROGRESS, TripStatus.PLANNING, TripStatus.CANCELLED}),
    TripStatus.IN_PROGRESS: frozenset({TripStatus.COMPLETED, TripStatus.CANCELLED}),
    TripStatus.COMPLETED: frozenset(),
    TripStatus.CANCELLED: frozenset(),
}
ITINERARY_TRANSITIONS = {
    ItineraryStatus.DRAFT: frozenset({ItineraryStatus.CONFIRMED, ItineraryStatus.ARCHIVED}),
    ItineraryStatus.CONFIRMED: frozenset({ItineraryStatus.ACTIVE, ItineraryStatus.DRAFT, ItineraryStatus.ARCHIVED}),
    ItineraryStatus.ACTIVE: frozenset({ItineraryStatus.COMPLETED, ItineraryStatus.ARCHIVED}),
    ItineraryStatus.COMPLETED: frozenset({ItineraryStatus.ARCHIVED}),
    ItineraryStatus.ARCHIVED: frozenset(),
}
ACTIVITY_TRANSITIONS = {
    ActivityStatus.PLANNED: frozenset({ActivityStatus.CONFIRMED, ActivityStatus.SKIPPED, ActivityStatus.CANCELLED}),
    ActivityStatus.CONFIRMED: frozenset({ActivityStatus.IN_PROGRESS, ActivityStatus.PLANNED, ActivityStatus.SKIPPED, ActivityStatus.CANCELLED}),
    ActivityStatus.IN_PROGRESS: frozenset({ActivityStatus.COMPLETED, ActivityStatus.SKIPPED, ActivityStatus.CANCELLED}),
    ActivityStatus.COMPLETED: frozenset(),
    ActivityStatus.SKIPPED: frozenset(),
    ActivityStatus.CANCELLED: frozenset(),
}


@dataclass(slots=True)
class User:
    id: str = field(default_factory=new_id)
    display_name: str = ""
    timezone: str = "Asia/Shanghai"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Trip:
    user_id: str
    city: str
    start_date: str
    end_date: str
    id: str = field(default_factory=new_id)
    title: str = ""
    status: TripStatus = TripStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValidationError("end_date must not be before start_date")

    def transition_to(self, target: TripStatus) -> None:
        self.status = transition(self.status, target, TRIP_TRANSITIONS)


@dataclass(slots=True)
class POI:
    name: str
    city: str
    latitude: float
    longitude: float
    id: str = field(default_factory=new_id)
    amap_id: str | None = None
    address: str | None = None
    category: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FavoriteSpot:
    user_id: str
    poi_id: str
    id: str = field(default_factory=new_id)
    note: str | None = None
    preference_tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Activity:
    itinerary_id: str
    poi_id: str
    sequence: int
    starts_at: str
    ends_at: str
    id: str = field(default_factory=new_id)
    title: str = ""
    status: ActivityStatus = ActivityStatus.PLANNED
    reservation_required: bool = False
    reservation_ref: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValidationError("activity ends_at must be after starts_at")
        if self.sequence < 1:
            raise ValidationError("activity sequence must be positive")

    def transition_to(self, target: ActivityStatus) -> None:
        self.status = transition(self.status, target, ACTIVITY_TRANSITIONS)


@dataclass(slots=True)
class TravelLeg:
    itinerary_id: str
    from_activity_id: str
    to_activity_id: str
    mode: TravelMode
    duration_minutes: int
    distance_meters: int
    id: str = field(default_factory=new_id)
    route_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.duration_minutes < 0 or self.distance_meters < 0:
            raise ValidationError("travel leg measures must not be negative")


@dataclass(slots=True)
class Itinerary:
    trip_id: str
    name: str = "主行程"
    id: str = field(default_factory=new_id)
    status: ItineraryStatus = ItineraryStatus.DRAFT
    activities: list[Activity] = field(default_factory=list)
    travel_legs: list[TravelLeg] = field(default_factory=list)
    current_version_id: str | None = None
    version_count: int = field(default=0, repr=False)

    def transition_to(self, target: ItineraryStatus) -> None:
        self.status = transition(self.status, target, ITINERARY_TRANSITIONS)

    def add_activity(self, activity: Activity) -> None:
        if activity.itinerary_id != self.id:
            raise ValidationError("activity belongs to another itinerary")
        if len(self.activities) >= 8:
            raise ValidationError("V1 itinerary supports at most 8 activities")
        if any(a.sequence == activity.sequence for a in self.activities):
            raise ValidationError("activity sequence must be unique")
        self.activities.append(activity)
        self.activities.sort(key=lambda item: item.sequence)
        try:
            self.validate_schedule()
        except ValidationError:
            self.activities.remove(activity)
            raise

    def validate_schedule(self) -> None:
        """Reject overlapping activities and incomplete reservation commitments."""
        ordered = sorted(self.activities, key=lambda item: item.starts_at)
        for previous, current in zip(ordered, ordered[1:]):
            if current.starts_at < previous.ends_at:
                raise ValidationError(
                    f"activities {previous.id} and {current.id} overlap"
                )
        for activity in self.activities:
            if activity.reservation_required and not activity.reservation_ref:
                raise ValidationError(
                    f"activity {activity.id} requires a reservation reference"
                )

    def snapshot(self) -> dict[str, Any]:
        return {
            "itinerary": {"id": self.id, "trip_id": self.trip_id, "name": self.name, "status": self.status.value},
            "activities": [asdict(a) for a in self.activities],
            "travel_legs": [asdict(l) for l in self.travel_legs],
        }


@dataclass(slots=True)
class ItineraryVersion:
    itinerary_id: str
    version_number: int
    change_reason: str
    snapshot_data: dict[str, Any]
    id: str = field(default_factory=new_id)
    restored_from_version_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.change_reason.strip():
            raise ValidationError("change_reason is required")
        if self.version_number < 1:
            raise ValidationError("version_number must be positive")


@dataclass(slots=True)
class ExecutionEvent:
    itinerary_id: str
    event_type: ExecutionEventType
    occurred_at: datetime
    id: str = field(default_factory=new_id)
    activity_id: str | None = None
    note: str | None = None
