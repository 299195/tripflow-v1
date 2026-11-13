from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ExecutionEventRequest(BaseModel):
    event_type: Literal["started", "arrived", "completed", "skipped", "note", "delayed", "closed"]
    activity_id: str | None = None
    occurred_at: str | None = None
    note: str | None = None
    delay_minutes: int = Field(default=0, ge=0, le=720)
    replacement_poi_ids: list[str] = Field(default_factory=list, max_length=3)


class ReplanPreviewRequest(BaseModel):
    event_type: Literal["delayed", "closed", "skipped"]
    activity_id: str | None = None
    delay_minutes: int = Field(default=0, ge=0, le=720)
    replacement_poi_ids: list[str] = Field(default_factory=list, max_length=3)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ReplanConfirmRequest(BaseModel):
    proposal_id: str
    option_id: str
    base_version_id: str
    idempotency_key: str | None = Field(default=None, max_length=128)
    change_reason: str = Field(default="确认重规划方案", min_length=1, max_length=200)


class FeedbackRequest(BaseModel):
    target_type: Literal["place", "proposal", "guide", "itinerary"]
    target_id: str
    label: Literal["accepted", "rejected", "skipped", "reported"]
    reason_code: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)
