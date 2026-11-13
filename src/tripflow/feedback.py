"""Deterministic feedback collection for TripFlow V2.

The feedback layer deliberately does not ask a model to grade its own output.
It stores small, auditable user signals and converts them into stable offline
evaluation samples. Runtime business services can later persist the same
records in SQLite; this module is dependency-free so it can also be used by
offline evaluation jobs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


FEEDBACK_LABELS = frozenset({"accepted", "rejected", "skipped", "reported"})
TARGET_TYPES = frozenset({"place", "proposal", "guide", "itinerary"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, *parts: str) -> str:
    value = "|".join(parts)
    return f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex[:16]}"


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe copy and fail early for ambiguous event payloads."""

    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("feedback metadata must be JSON serializable") from exc


@dataclass(frozen=True, slots=True)
class FeedbackEvent:
    """A user-observed outcome used for offline evaluation.

    ``label`` is a user action or report. It is not a model judgement. The
    optional ``metadata`` may contain an externally computed outcome such as
    a route source or a hard-constraint count, but the evaluator remains the
    authority for pass/fail metrics.
    """

    event_id: str
    target_type: str
    target_id: str
    label: str
    reason_code: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    itinerary_id: str | None = None
    proposal_id: str | None = None
    strategy_version: str | None = None
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if self.target_type not in TARGET_TYPES:
            raise ValueError(f"unsupported target_type: {self.target_type}")
        if not self.target_id.strip():
            raise ValueError("target_id is required")
        if self.label not in FEEDBACK_LABELS:
            raise ValueError(f"unsupported feedback label: {self.label}")
        if self.reason_code is not None and len(self.reason_code) > 80:
            raise ValueError("reason_code must be at most 80 characters")
        object.__setattr__(self, "metadata", _json_safe(dict(self.metadata)))

    @classmethod
    def create(
        cls,
        *,
        target_type: str,
        target_id: str,
        label: str,
        reason_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        user_id: str | None = None,
        itinerary_id: str | None = None,
        proposal_id: str | None = None,
        strategy_version: str | None = None,
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> "FeedbackEvent":
        stable_event_id = event_id or _stable_id(
            "feedback",
            target_type,
            target_id,
            label,
            reason_code or "",
            strategy_version or "",
            created_at or _utc_now(),
        )
        return cls(
            event_id=stable_event_id,
            target_type=target_type,
            target_id=target_id,
            label=label,
            reason_code=reason_code,
            metadata=metadata or {},
            user_id=user_id,
            itinerary_id=itinerary_id,
            proposal_id=proposal_id,
            strategy_version=strategy_version,
            created_at=created_at or _utc_now(),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FeedbackEvent":
        data = dict(payload)
        data.setdefault("metadata", {})
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    """A deterministic regression sample derived from a feedback event."""

    sample_id: str
    event_id: str
    input_payload: Mapping[str, Any]
    user_signal: str
    expected_acceptance: bool | None
    strategy_version: str | None
    created_at: str

    def __post_init__(self) -> None:
        if self.user_signal not in FEEDBACK_LABELS:
            raise ValueError(f"unsupported user_signal: {self.user_signal}")
        object.__setattr__(self, "input_payload", _json_safe(dict(self.input_payload)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sample_from_event(event: FeedbackEvent) -> EvaluationSample:
    """Convert one event to a replayable sample.

    Only explicit accept/reject signals become an acceptance label. A skipped
    or reported event remains unlabeled for acceptance and can still be used
    to reproduce a failure or a user interruption.
    """

    expected = {"accepted": True, "rejected": False}.get(event.label)
    payload = {
        "target_type": event.target_type,
        "target_id": event.target_id,
        "reason_code": event.reason_code,
        "metadata": dict(event.metadata),
        "itinerary_id": event.itinerary_id,
        "proposal_id": event.proposal_id,
    }
    return EvaluationSample(
        sample_id=_stable_id("sample", event.event_id),
        event_id=event.event_id,
        input_payload=payload,
        user_signal=event.label,
        expected_acceptance=expected,
        strategy_version=event.strategy_version,
        created_at=event.created_at,
    )


def generate_samples(events: Iterable[FeedbackEvent]) -> list[EvaluationSample]:
    """Generate de-duplicated samples in stable event-id order."""

    unique: dict[str, FeedbackEvent] = {}
    for event in events:
        if event.event_id in unique and unique[event.event_id] != event:
            raise ValueError(f"conflicting duplicate event_id: {event.event_id}")
        unique[event.event_id] = event
    return [sample_from_event(unique[event_id]) for event_id in sorted(unique)]


class FeedbackLedger:
    """Small deterministic event ledger for collection and offline export."""

    def __init__(self, events: Iterable[FeedbackEvent] | None = None) -> None:
        self._events: dict[str, FeedbackEvent] = {}
        for event in events or ():
            self.append(event)

    def append(self, event: FeedbackEvent) -> FeedbackEvent:
        previous = self._events.get(event.event_id)
        if previous is not None and previous != event:
            raise ValueError(f"conflicting duplicate event_id: {event.event_id}")
        self._events[event.event_id] = event
        return event

    def record(self, **kwargs: Any) -> FeedbackEvent:
        event = FeedbackEvent.create(**kwargs)
        return self.append(event)

    def events(self) -> list[FeedbackEvent]:
        return [self._events[key] for key in sorted(self._events)]

    def samples(self) -> list[EvaluationSample]:
        return generate_samples(self.events())

    def export_jsonl(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) for event in self.events())
        destination.write_text(content + ("\n" if content else ""), encoding="utf-8")
        return destination

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "FeedbackLedger":
        source = Path(path)
        if not source.exists():
            return cls()
        events = []
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(FeedbackEvent.from_dict(json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid feedback JSONL at line {line_number}") from exc
        return cls(events)
