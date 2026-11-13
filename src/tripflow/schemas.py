from dataclasses import dataclass

from .domain.enums import ActivityStatus, ItineraryStatus, TripStatus


@dataclass(frozen=True, slots=True)
class TripCreate:
    user_id: str
    city: str
    start_date: str
    end_date: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class ActivityInput:
    poi_id: str
    sequence: int
    starts_at: str
    ends_at: str
    reservation_required: bool = False


@dataclass(frozen=True, slots=True)
class VersionCreate:
    change_reason: str


@dataclass(frozen=True, slots=True)
class TripView:
    id: str
    status: TripStatus
    city: str


@dataclass(frozen=True, slots=True)
class ItineraryView:
    id: str
    status: ItineraryStatus
    activity_count: int


@dataclass(frozen=True, slots=True)
class ActivityView:
    id: str
    status: ActivityStatus
    sequence: int
