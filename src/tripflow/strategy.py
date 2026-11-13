"""Versioned deterministic strategy registry for TripFlow V2.

Strategies are configuration and code-version identifiers. This module does
not generate prompts, call a model, or approve itself. An offline evaluator
must provide measured metrics before a candidate can be approved.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Mapping


StrategyStatus = Literal["candidate", "approved", "rejected", "retired"]
VALID_STATUSES = frozenset({"candidate", "approved", "rejected", "retired"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _copy_json(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValueError("strategy parameters and metrics must be JSON serializable") from exc


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """A named, immutable strategy version evaluated offline."""

    version: str
    name: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    parent_version: str | None = None
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("strategy version is required")
        if not self.name.strip():
            raise ValueError("strategy name is required")
        if not self.description.strip():
            raise ValueError("strategy description is required")
        object.__setattr__(self, "parameters", _copy_json(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrategyRelease:
    """Mutable lifecycle state represented as immutable snapshots."""

    strategy: StrategySpec
    status: StrategyStatus = "candidate"
    metrics: Mapping[str, Any] = field(default_factory=dict)
    decision_reason: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"unsupported strategy status: {self.status}")
        object.__setattr__(self, "metrics", _copy_json(self.metrics))

    @property
    def version(self) -> str:
        return self.strategy.version

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.to_dict(),
            "status": self.status,
            "metrics": dict(self.metrics),
            "decision_reason": self.decision_reason,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
        }


class StrategyTransitionError(ValueError):
    """Raised when a strategy lifecycle transition violates the release policy."""


class StrategyRegistry:
    """In-memory registry with explicit candidate approval transitions."""

    def __init__(self, releases: list[StrategyRelease] | None = None, *, now_fn: Callable[[], str] = _utc_now) -> None:
        self._releases: dict[str, StrategyRelease] = {}
        self._now = now_fn
        for release in releases or []:
            self.register_release(release)

    def register(self, strategy: StrategySpec, *, status: StrategyStatus = "candidate") -> StrategyRelease:
        return self.register_release(StrategyRelease(strategy=strategy, status=status))

    def register_release(self, release: StrategyRelease) -> StrategyRelease:
        if release.version in self._releases:
            raise StrategyTransitionError(f"strategy version already exists: {release.version}")
        self._releases[release.version] = release
        return release

    def get(self, version: str) -> StrategyRelease:
        try:
            return self._releases[version]
        except KeyError as exc:
            raise KeyError(f"unknown strategy version: {version}") from exc

    def list(self) -> list[StrategyRelease]:
        return [self._releases[version] for version in sorted(self._releases)]

    def approve(
        self,
        version: str,
        *,
        metrics: Mapping[str, Any],
        gate_passed: bool,
        reason: str,
        decided_by: str = "human-review",
    ) -> StrategyRelease:
        release = self.get(version)
        if release.status != "candidate":
            raise StrategyTransitionError(f"only candidates can be approved: {version}")
        if not gate_passed:
            raise StrategyTransitionError("hard-constraint gate must pass before approval")
        if not reason.strip():
            raise ValueError("approval reason is required")
        updated = StrategyRelease(
            strategy=release.strategy,
            status="approved",
            metrics=metrics,
            decision_reason=reason,
            decided_at=self._now(),
            decided_by=decided_by,
        )
        self._releases[version] = updated
        return updated

    def reject(
        self,
        version: str,
        *,
        metrics: Mapping[str, Any],
        reason: str,
        decided_by: str = "offline-gate",
    ) -> StrategyRelease:
        release = self.get(version)
        if release.status != "candidate":
            raise StrategyTransitionError(f"only candidates can be rejected: {version}")
        if not reason.strip():
            raise ValueError("rejection reason is required")
        updated = StrategyRelease(
            strategy=release.strategy,
            status="rejected",
            metrics=metrics,
            decision_reason=reason,
            decided_at=self._now(),
            decided_by=decided_by,
        )
        self._releases[version] = updated
        return updated

    def retire(self, version: str, *, reason: str, decided_by: str = "human-review") -> StrategyRelease:
        release = self.get(version)
        if release.status != "approved":
            raise StrategyTransitionError(f"only approved strategies can be retired: {version}")
        if not reason.strip():
            raise ValueError("retirement reason is required")
        updated = StrategyRelease(
            strategy=release.strategy,
            status="retired",
            metrics=release.metrics,
            decision_reason=reason,
            decided_at=self._now(),
            decided_by=decided_by,
        )
        self._releases[version] = updated
        return updated
