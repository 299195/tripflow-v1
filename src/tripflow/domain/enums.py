from enum import StrEnum


class TripStatus(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ItineraryStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ActivityStatus(StrEnum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TravelMode(StrEnum):
    WALKING = "walking"
    TRANSIT = "transit"
    DRIVING = "driving"
    BICYCLING = "bicycling"


class ExecutionEventType(StrEnum):
    STARTED = "started"
    ARRIVED = "arrived"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    NOTE = "note"
