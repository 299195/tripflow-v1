from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
T = TypeVar("T")

@dataclass(frozen=True)
class ApiMeta:
    status: str
    provider: str
    queried_at: datetime
    query_time_ms: int
    error_code: str | None = None
    error_message: str | None = None
    unknown: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ApiResult(Generic[T]):
    data: T | None
    meta: ApiMeta
    @property
    def ok(self) -> bool: return self.meta.status == "success"

@dataclass(frozen=True)
class Place:
    id: str | None
    name: str
    address: str | None
    location: str | None
    typecode: str | None
    city: str | None
    district: str | None
    raw_data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Route:
    mode: str
    origin: str
    destination: str
    distance_m: int | None
    duration_s: int | None
    paths: list[dict[str, Any]]
    raw_data: dict[str, Any] = field(default_factory=dict)

def now_utc() -> datetime: return datetime.now(timezone.utc)

