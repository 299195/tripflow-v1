import unittest

from tripflow.domain import (
    Activity, ActivityStatus, Itinerary, ItineraryStatus, InvalidStateTransition,
    POI, Trip, TripStatus, User, ValidationError,
)
from tripflow.domain.versioning import ItineraryVersionService


class DomainStateTests(unittest.TestCase):
    def test_trip_state_machine_rejects_illegal_transition(self):
        trip = Trip(User().id, "杭州", "2026-12-01", "2026-12-02")
        with self.assertRaises(InvalidStateTransition):
            trip.transition_to(TripStatus.COMPLETED)
        trip.transition_to(TripStatus.PLANNING)
        trip.transition_to(TripStatus.READY)

    def test_itinerary_and_activity_state_machines(self):
        itinerary = Itinerary("trip-1")
        with self.assertRaises(InvalidStateTransition):
            itinerary.transition_to(ItineraryStatus.ACTIVE)
        itinerary.transition_to(ItineraryStatus.CONFIRMED)
        activity = Activity(itinerary.id, "poi-1", 1, "2026-12-01T10:00", "2026-12-01T11:00")
        with self.assertRaises(InvalidStateTransition):
            activity.transition_to(ActivityStatus.COMPLETED)

    def test_itinerary_has_maximum_eight_activities(self):
        itinerary = Itinerary("trip-1")
        for sequence in range(1, 9):
            itinerary.add_activity(Activity(itinerary.id, f"poi-{sequence}", sequence, f"2026-12-01T{sequence:02d}:00", f"2026-12-01T{sequence:02d}:30"))
        with self.assertRaises(ValidationError):
            itinerary.add_activity(Activity(itinerary.id, "poi-9", 9, "2026-12-01T20:00", "2026-12-01T21:00"))

    def test_schedule_rejects_time_overlap_and_unconfirmed_reservation(self):
        itinerary = Itinerary("trip-1")
        itinerary.add_activity(Activity(itinerary.id, "poi-1", 1, "2026-12-01T10:00", "2026-12-01T11:00"))
        with self.assertRaises(ValidationError):
            itinerary.add_activity(Activity(itinerary.id, "poi-2", 2, "2026-12-01T10:30", "2026-12-01T11:30"))

        reserved = Activity(
            itinerary.id, "poi-3", 3, "2026-12-01T12:00", "2026-12-01T13:00",
            reservation_required=True,
        )
        with self.assertRaises(ValidationError):
            itinerary.add_activity(reserved)


class VersionTests(unittest.TestCase):
    def test_create_and_restore_are_new_immutable_versions(self):
        itinerary = Itinerary("trip-1")
        itinerary.add_activity(Activity(itinerary.id, "poi-1", 1, "2026-12-01T10:00", "2026-12-01T11:00"))
        service = ItineraryVersionService()
        first = service.create(itinerary, "初始规划")
        itinerary.activities[0].title = "修改后的标题"
        second = service.create(itinerary, "手动编辑标题")
        restored = service.restore(itinerary, first, "恢复到初始规划")
        self.assertEqual(first.version_number, 1)
        self.assertEqual(second.version_number, 2)
        self.assertEqual(restored.version_number, 3)
        self.assertEqual(restored.restored_from_version_id, first.id)
        self.assertEqual(itinerary.activities[0].title, "")
        self.assertEqual(itinerary.current_version_id, restored.id)

    def test_version_requires_reason(self):
        with self.assertRaises(ValidationError):
            ItineraryVersionService().create(Itinerary("trip-1"), " ")
