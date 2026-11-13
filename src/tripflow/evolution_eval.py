"""Deterministic offline strategy comparison for TripFlow V2.

The evaluator measures externally supplied outcomes. A strategy runner must
return hard-constraint and operational metrics; no language model is asked to
judge its own answer. The resulting comparison is suitable for a regression
dataset and for a human release decision.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Literal, Mapping

from .feedback import EvaluationSample
from .strategy import StrategyRegistry, StrategyRelease, StrategySpec


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    input_payload: Mapping[str, Any]
    expected_acceptance: bool | None = None
    hard_constraint_budget: int = 0

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        if self.hard_constraint_budget < 0:
            raise ValueError("hard_constraint_budget cannot be negative")
        try:
            copied = json.loads(json.dumps(dict(self.input_payload), ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError) as exc:
            raise ValueError("case input_payload must be JSON serializable") from exc
        object.__setattr__(self, "input_payload", copied)

    @classmethod
    def from_sample(cls, sample: EvaluationSample, *, hard_constraint_budget: int = 0) -> "EvaluationCase":
        return cls(
            case_id=sample.sample_id,
            input_payload=sample.input_payload,
            expected_acceptance=sample.expected_acceptance,
            hard_constraint_budget=hard_constraint_budget,
        )


@dataclass(frozen=True, slots=True)
class StrategyOutcome:
    """Measured result returned by a deterministic strategy runner."""

    hard_constraint_violations: int
    utility_score: float = 0.0
    predicted_acceptance: bool | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.hard_constraint_violations < 0:
            raise ValueError("hard_constraint_violations cannot be negative")
        if self.latency_ms < 0 or self.cost_usd < 0:
            raise ValueError("latency_ms and cost_usd cannot be negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StrategyOutcome":
        violations = value.get("hard_constraint_violations", value.get("constraint_violations"))
        if violations is None:
            raise ValueError("strategy result must include hard_constraint_violations")
        return cls(
            hard_constraint_violations=int(violations),
            utility_score=float(value.get("utility_score", 0.0)),
            predicted_acceptance=value.get("predicted_acceptance", value.get("accepted")),
            latency_ms=float(value.get("latency_ms", 0.0)),
            cost_usd=float(value.get("cost_usd", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    outcome: StrategyOutcome
    within_hard_constraint_budget: bool
    acceptance_match: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "outcome": asdict(self.outcome),
            "within_hard_constraint_budget": self.within_hard_constraint_budget,
            "acceptance_match": self.acceptance_match,
        }


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    strategy_version: str
    total_cases: int
    completed_cases: int
    error_cases: int
    hard_constraint_violations: int
    hard_constraint_pass_rate: float
    acceptance_observations: int
    acceptance_accuracy: float | None
    average_utility_score: float
    average_latency_ms: float
    total_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    strategy: StrategySpec
    metrics: EvaluationMetrics
    cases: tuple[CaseResult, ...]
    errors: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.to_dict(),
            "metrics": self.metrics.to_dict(),
            "cases": [case.to_dict() for case in self.cases],
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]
    hard_constraint_regression: int
    hard_constraint_pass_rate_delta: float
    utility_delta: float
    latency_ratio: float | None
    error_case_regression: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrategyComparison:
    baseline: EvaluationReport
    candidate: EvaluationReport
    gate: GateResult

    @property
    def recommendation(self) -> Literal["approve", "reject"]:
        return "approve" if self.gate.passed else "reject"

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "gate": self.gate.to_dict(),
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True, slots=True)
class HardConstraintGate:
    """Release threshold that prevents hard-constraint regression."""

    max_new_violations: int = 0
    min_pass_rate_delta: float = 0.0
    min_utility_delta: float = 0.0
    max_latency_ratio: float | None = None

    def __post_init__(self) -> None:
        if self.max_new_violations < 0:
            raise ValueError("max_new_violations cannot be negative")
        if self.max_latency_ratio is not None and self.max_latency_ratio <= 0:
            raise ValueError("max_latency_ratio must be positive")

    def evaluate(self, baseline: EvaluationMetrics, candidate: EvaluationMetrics) -> GateResult:
        regression = candidate.hard_constraint_violations - baseline.hard_constraint_violations
        pass_rate_delta = candidate.hard_constraint_pass_rate - baseline.hard_constraint_pass_rate
        utility_delta = candidate.average_utility_score - baseline.average_utility_score
        error_regression = candidate.error_cases - baseline.error_cases
        latency_ratio: float | None = None
        if baseline.average_latency_ms > 0:
            latency_ratio = candidate.average_latency_ms / baseline.average_latency_ms
        reasons: list[str] = []
        if regression > self.max_new_violations:
            reasons.append(f"hard-constraint violations increased by {regression}")
        if pass_rate_delta < self.min_pass_rate_delta:
            reasons.append(f"hard-constraint pass rate delta {pass_rate_delta:.4f} is below {self.min_pass_rate_delta:.4f}")
        if utility_delta < self.min_utility_delta:
            reasons.append(f"utility delta {utility_delta:.4f} is below {self.min_utility_delta:.4f}")
        if error_regression > 0:
            reasons.append(f"evaluation errors increased by {error_regression}")
        if self.max_latency_ratio is not None and latency_ratio is not None and latency_ratio > self.max_latency_ratio:
            reasons.append(f"latency ratio {latency_ratio:.4f} exceeds {self.max_latency_ratio:.4f}")
        if baseline.total_cases != candidate.total_cases:
            reasons.append("baseline and candidate used different case counts")
        return GateResult(
            passed=not reasons,
            reasons=tuple(reasons),
            hard_constraint_regression=regression,
            hard_constraint_pass_rate_delta=pass_rate_delta,
            utility_delta=utility_delta,
            latency_ratio=latency_ratio,
            error_case_regression=error_regression,
        )


Runner = Callable[[StrategySpec, EvaluationCase], StrategyOutcome | Mapping[str, Any]]


def evaluate_strategy(strategy: StrategySpec, cases: Iterable[EvaluationCase], runner: Runner) -> EvaluationReport:
    """Run a strategy against cases in stable order and aggregate measured metrics."""

    ordered = sorted(cases, key=lambda case: case.case_id)
    results: list[CaseResult] = []
    errors: list[dict[str, str]] = []
    for case in ordered:
        try:
            raw = runner(strategy, case)
            outcome = raw if isinstance(raw, StrategyOutcome) else StrategyOutcome.from_mapping(raw)
            within_budget = outcome.hard_constraint_violations <= case.hard_constraint_budget
            acceptance_match = None
            if case.expected_acceptance is not None and outcome.predicted_acceptance is not None:
                acceptance_match = case.expected_acceptance == outcome.predicted_acceptance
            results.append(CaseResult(case.case_id, outcome, within_budget, acceptance_match))
        except Exception as exc:
            errors.append({"case_id": case.case_id, "error": f"{type(exc).__name__}: {exc}"})

    completed = len(results)
    total = len(ordered)
    violations = sum(result.outcome.hard_constraint_violations for result in results)
    pass_rate = sum(result.within_hard_constraint_budget for result in results) / completed if completed else 0.0
    observed = [result.acceptance_match for result in results if result.acceptance_match is not None]
    accuracy = sum(observed) / len(observed) if observed else None
    metrics = EvaluationMetrics(
        strategy_version=strategy.version,
        total_cases=total,
        completed_cases=completed,
        error_cases=len(errors),
        hard_constraint_violations=violations,
        hard_constraint_pass_rate=pass_rate,
        acceptance_observations=len(observed),
        acceptance_accuracy=accuracy,
        average_utility_score=sum(result.outcome.utility_score for result in results) / completed if completed else 0.0,
        average_latency_ms=sum(result.outcome.latency_ms for result in results) / completed if completed else 0.0,
        total_cost_usd=sum(result.outcome.cost_usd for result in results),
    )
    return EvaluationReport(strategy=strategy, metrics=metrics, cases=tuple(results), errors=tuple(errors))


def compare_strategies(
    baseline: StrategySpec,
    candidate: StrategySpec,
    cases: Iterable[EvaluationCase],
    runner: Runner,
    *,
    gate: HardConstraintGate | None = None,
) -> StrategyComparison:
    """Evaluate baseline and candidate on the identical deterministic dataset."""

    case_list = list(cases)
    baseline_report = evaluate_strategy(baseline, case_list, runner)
    candidate_report = evaluate_strategy(candidate, case_list, runner)
    gate_result = (gate or HardConstraintGate()).evaluate(baseline_report.metrics, candidate_report.metrics)
    return StrategyComparison(baseline=baseline_report, candidate=candidate_report, gate=gate_result)


def apply_comparison_decision(
    registry: StrategyRegistry,
    comparison: StrategyComparison,
    *,
    decision: Literal["approve", "reject"],
    decided_by: str = "human-review",
) -> StrategyRelease:
    """Apply an explicit human release decision to a candidate registry entry."""

    metrics = {
        "baseline": comparison.baseline.metrics.to_dict(),
        "candidate": comparison.candidate.metrics.to_dict(),
        "gate": comparison.gate.to_dict(),
    }
    if decision == "approve":
        if not comparison.gate.passed:
            raise ValueError("cannot approve a candidate that fails the hard-constraint gate")
        return registry.approve(
            comparison.candidate.strategy.version,
            metrics=metrics,
            gate_passed=True,
            reason="offline gate passed and human review approved the candidate",
            decided_by=decided_by,
        )
    if decision == "reject":
        reason = "offline gate failed: " + "; ".join(comparison.gate.reasons) if comparison.gate.reasons else "human review rejected the candidate"
        return registry.reject(
            comparison.candidate.strategy.version,
            metrics=metrics,
            reason=reason,
            decided_by=decided_by,
        )
    raise ValueError(f"unsupported decision: {decision}")
