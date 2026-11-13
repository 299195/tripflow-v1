from __future__ import annotations

import pytest

from tripflow.evolution_eval import (
    EvaluationCase,
    HardConstraintGate,
    StrategyOutcome,
    apply_comparison_decision,
    compare_strategies,
    evaluate_strategy,
)
from tripflow.strategy import StrategyRegistry, StrategySpec, StrategyTransitionError


def _strategies() -> tuple[StrategySpec, StrategySpec]:
    return (
        StrategySpec("baseline-1", "baseline", "stable baseline"),
        StrategySpec("candidate-2", "candidate", "candidate ranking", parent_version="baseline-1"),
    )


def _cases() -> list[EvaluationCase]:
    return [
        EvaluationCase("case-1", {"kind": "normal"}, expected_acceptance=True),
        EvaluationCase("case-2", {"kind": "reservation"}, expected_acceptance=False),
        EvaluationCase("case-3", {"kind": "normal"}, expected_acceptance=True),
    ]


def test_evaluator_aggregates_external_metrics_without_model_judgement() -> None:
    baseline, _ = _strategies()

    def runner(_strategy, case):
        return StrategyOutcome(
            hard_constraint_violations=0,
            utility_score=0.8,
            predicted_acceptance=case.expected_acceptance,
            latency_ms=10,
        )

    report = evaluate_strategy(baseline, _cases(), runner)
    assert report.metrics.total_cases == 3
    assert report.metrics.completed_cases == 3
    assert report.metrics.hard_constraint_violations == 0
    assert report.metrics.hard_constraint_pass_rate == 1.0
    assert report.metrics.acceptance_accuracy == 1.0
    assert report.metrics.average_latency_ms == 10


def test_hard_constraint_regression_rejects_candidate() -> None:
    baseline, candidate = _strategies()
    cases = _cases()

    def runner(strategy, case):
        violations = 0 if strategy.version == baseline.version else (1 if case.case_id == "case-2" else 0)
        return {
            "hard_constraint_violations": violations,
            "utility_score": 0.9,
            "predicted_acceptance": True,
        }

    comparison = compare_strategies(baseline, candidate, cases, runner)
    assert comparison.gate.passed is False
    assert comparison.recommendation == "reject"
    assert comparison.gate.hard_constraint_regression == 1
    assert any("hard-constraint" in reason for reason in comparison.gate.reasons)


def test_candidate_can_be_approved_only_after_gate_and_explicit_decision() -> None:
    baseline, candidate = _strategies()

    def runner(strategy, case):
        return {
            "hard_constraint_violations": 0,
            "utility_score": 0.75 if strategy.version == baseline.version else 0.85,
            "predicted_acceptance": case.expected_acceptance,
            "latency_ms": 11 if strategy.version == candidate.version else 10,
        }

    comparison = compare_strategies(
        baseline,
        candidate,
        _cases(),
        runner,
        gate=HardConstraintGate(max_latency_ratio=1.5),
    )
    registry = StrategyRegistry()
    registry.register(baseline, status="approved")
    registry.register(candidate)
    release = apply_comparison_decision(registry, comparison, decision="approve")
    assert release.status == "approved"
    assert registry.get(candidate.version).status == "approved"
    assert release.metrics["gate"]["passed"] is True


def test_failed_candidate_is_rejected_and_cannot_be_approved() -> None:
    baseline, candidate = _strategies()

    def runner(strategy, _case):
        return {"hard_constraint_violations": 0 if strategy.version == baseline.version else 1, "utility_score": 0.9}

    comparison = compare_strategies(baseline, candidate, _cases(), runner)
    registry = StrategyRegistry()
    registry.register(baseline, status="approved")
    registry.register(candidate)
    release = apply_comparison_decision(registry, comparison, decision="reject")
    assert release.status == "rejected"
    with pytest.raises(StrategyTransitionError):
        registry.approve(candidate.version, metrics={}, gate_passed=True, reason="late approval")


def test_approve_is_blocked_when_gate_fails() -> None:
    baseline, candidate = _strategies()

    def runner(strategy, _case):
        return {"hard_constraint_violations": 1 if strategy.version == candidate.version else 0}

    comparison = compare_strategies(baseline, candidate, _cases(), runner)
    registry = StrategyRegistry()
    registry.register(baseline, status="approved")
    registry.register(candidate)
    with pytest.raises(ValueError, match="fails the hard-constraint gate"):
        apply_comparison_decision(registry, comparison, decision="approve")
    assert registry.get(candidate.version).status == "candidate"


def test_new_evaluation_errors_fail_the_release_gate() -> None:
    baseline, candidate = _strategies()

    def runner(strategy, case):
        if strategy.version == candidate.version and case.case_id == "case-2":
            raise RuntimeError("fixture timeout")
        return {"hard_constraint_violations": 0}

    comparison = compare_strategies(baseline, candidate, _cases(), runner)
    assert comparison.gate.passed is False
    assert comparison.gate.error_case_regression == 1
    assert any("evaluation errors" in reason for reason in comparison.gate.reasons)
