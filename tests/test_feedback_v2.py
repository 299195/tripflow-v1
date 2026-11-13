from __future__ import annotations

import pytest

from tripflow.feedback import FeedbackEvent, FeedbackLedger, generate_samples


def test_feedback_event_is_validated_and_round_trips() -> None:
    event = FeedbackEvent.create(
        event_id="event-1",
        target_type="proposal",
        target_id="proposal-1",
        label="rejected",
        reason_code="too_far",
        metadata={"distance_meters": 2400},
        created_at="2026-01-01T00:00:00+00:00",
    )

    assert FeedbackEvent.from_dict(event.to_dict()) == event
    assert event.to_dict()["metadata"] == {"distance_meters": 2400}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_type": "unknown", "target_id": "x", "label": "accepted"},
        {"target_type": "place", "target_id": "x", "label": "unknown"},
        {"target_type": "place", "target_id": "x", "label": "accepted", "metadata": {"bad": object()}},
    ],
)
def test_feedback_event_rejects_invalid_payload(kwargs) -> None:
    with pytest.raises(ValueError):
        FeedbackEvent.create(event_id="invalid", **kwargs)


def test_ledger_is_idempotent_and_generates_stable_samples() -> None:
    first = FeedbackEvent.create(
        event_id="event-a",
        target_type="proposal",
        target_id="proposal-a",
        label="accepted",
        created_at="2026-01-01T00:00:00+00:00",
    )
    second = FeedbackEvent.create(
        event_id="event-b",
        target_type="proposal",
        target_id="proposal-b",
        label="reported",
        reason_code="closed",
        created_at="2026-01-01T00:00:01+00:00",
    )
    ledger = FeedbackLedger([second, first])
    ledger.append(first)

    samples = ledger.samples()
    assert [sample.event_id for sample in samples] == ["event-a", "event-b"]
    assert samples[0].expected_acceptance is True
    assert samples[1].expected_acceptance is None

    conflicting = FeedbackEvent.create(
        event_id="event-a",
        target_type="proposal",
        target_id="different",
        label="rejected",
        created_at="2026-01-01T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="conflicting duplicate"):
        ledger.append(conflicting)


def test_jsonl_export_and_import_preserves_event_order(tmp_path) -> None:
    ledger = FeedbackLedger()
    ledger.record(
        event_id="event-2",
        target_type="place",
        target_id="place-2",
        label="skipped",
        reason_code="not_interested",
        created_at="2026-01-01T00:00:02+00:00",
    )
    ledger.record(
        event_id="event-1",
        target_type="place",
        target_id="place-1",
        label="accepted",
        created_at="2026-01-01T00:00:01+00:00",
    )
    path = ledger.export_jsonl(tmp_path / "feedback.jsonl")
    restored = FeedbackLedger.from_jsonl(path)
    assert [event.event_id for event in restored.events()] == ["event-1", "event-2"]
    assert generate_samples(restored.events()) == restored.samples()
