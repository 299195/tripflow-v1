"""Run a deterministic TripFlow V2 feedback-to-release evaluation.

Examples:
    python eval/run_evolution_eval_v2.py
    python eval/run_evolution_eval_v2.py --candidate regression --decision reject
    python eval/run_evolution_eval_v2.py --decision approve

The default command only prints a report and does not publish a strategy.
Approval is an explicit command-line decision after the offline gate passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripflow.evolution_eval import (  # noqa: E402
    EvaluationCase,
    HardConstraintGate,
    apply_comparison_decision,
    compare_strategies,
)
from tripflow.feedback import FeedbackLedger  # noqa: E402
from tripflow.strategy import StrategyRegistry, StrategySpec  # noqa: E402


def build_feedback() -> FeedbackLedger:
    ledger = FeedbackLedger()
    rows = [
        ("event-01", "proposal-01", "accepted", "good_route", True),
        ("event-02", "proposal-02", "rejected", "too_many_stops", False),
        ("event-03", "proposal-03", "accepted", "reservation_kept", True),
        ("event-04", "proposal-04", "reported", "poi_closed", None),
        ("event-05", "proposal-05", "skipped", "user_skipped", None),
        ("event-06", "proposal-06", "accepted", "short_transfer", True),
    ]
    for event_id, proposal_id, label, reason, hard_case in rows:
        ledger.record(
            event_id=event_id,
            target_type="proposal",
            target_id=proposal_id,
            label=label,
            reason_code=reason,
            proposal_id=proposal_id,
            strategy_version="strategy-baseline-1",
            created_at="2026-01-01T00:00:00+00:00",
            metadata={"scenario": reason, "hard_case": hard_case},
        )
    return ledger


def build_runner(candidate_mode: str):
    def runner(strategy: StrategySpec, case: EvaluationCase):
        metadata = case.input_payload.get("metadata", {})
        label = case.expected_acceptance
        hard_case = metadata.get("hard_case") is True
        if strategy.version == "strategy-baseline-1":
            violations = 1 if hard_case else 0
            utility = 0.65 if hard_case else 0.78
            predicted = label
        elif candidate_mode == "regression":
            violations = 2 if hard_case or case.case_id.endswith("event-06") else 0
            utility = 0.66 if hard_case else 0.74
            predicted = label is True
        else:
            violations = 1 if hard_case else 0
            utility = 0.72 if hard_case else 0.86
            predicted = label
        return {
            "hard_constraint_violations": violations,
            "utility_score": utility,
            "predicted_acceptance": predicted,
            "latency_ms": 10.0 if strategy.version == "strategy-baseline-1" else 11.0,
            "cost_usd": 0.0,
        }

    return runner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=("improved", "regression"), default="improved")
    parser.add_argument("--decision", choices=("none", "approve", "reject"), default="none")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    ledger = build_feedback()
    samples = ledger.samples()
    cases = [EvaluationCase.from_sample(sample) for sample in samples]
    fixed_created_at = "2026-01-01T00:00:00+00:00"
    baseline = StrategySpec("strategy-baseline-1", "deterministic-baseline", "V1 stable ranking", {"ranker": "baseline"}, created_at=fixed_created_at)
    candidate = StrategySpec("strategy-candidate-2", "deterministic-candidate", "V2 candidate ranking", {"ranker": args.candidate}, parent_version=baseline.version, created_at=fixed_created_at)
    comparison = compare_strategies(baseline, candidate, cases, build_runner(args.candidate), gate=HardConstraintGate(max_latency_ratio=1.5))

    registry = StrategyRegistry(now_fn=lambda: fixed_created_at)
    registry.register(baseline, status="approved")
    registry.register(candidate)
    release = None
    if args.decision != "none":
        release = apply_comparison_decision(registry, comparison, decision=args.decision)

    report = {
        "feedback_event_count": len(ledger.events()),
        "generated_sample_count": len(samples),
        "comparison": comparison.to_dict(),
        "release": release.to_dict() if release else {"status": registry.get(candidate.version).status, "decision": "pending"},
        "model_self_evaluation_used": False,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
