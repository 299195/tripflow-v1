"""Small, auditable multi-agent coordinator used by TripFlow V2.

Agents produce structured advisory artifacts. The deterministic planner and
transactional service remain the only components allowed to change itinerary
state.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class AgentArtifact:
    agent_name: str
    status: str
    output: dict[str, Any]
    policy_version: str = "v2-policy-1"
    model: str | None = None
    error: str | None = None


class TripFlowAgentCoordinator:
    """Run intent, place-verification and review nodes with a shared state."""

    def __init__(self, db=None, model_runner: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None):
        self.db = db
        self.model_runner = model_runner

    def run(self, *, itinerary_id: str | None, message: str, city: str, candidates: list[dict[str, Any]] | None = None, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        state: dict[str, Any] = {"city": city, "message": message[:1200], "candidates": candidates or [], "plan": plan}
        artifacts = []
        artifacts.append(self._run_node("intent", itinerary_id, correlation_id, state, self._intent))
        state["intent"] = artifacts[-1].output
        artifacts.append(self._run_node("place_verifier", itinerary_id, correlation_id, state, self._places))
        state["verified_places"] = artifacts[-1].output
        if plan is not None:
            artifacts.append(self._run_node("plan_reviewer", itinerary_id, correlation_id, state, self._review))
            state["review"] = artifacts[-1].output
        return {"correlation_id": correlation_id, "state": state, "agents": [a.__dict__ for a in artifacts]}

    def _run_node(self, name, itinerary_id, correlation_id, state, fallback):
        started = datetime.now(timezone.utc)
        status, error, model = "fallback", None, None
        try:
            if self.model_runner:
                output = self.model_runner(name, state)
                status, model = "completed", "configured-model"
            else:
                output = fallback(state)
        except Exception as exc:
            output, error = fallback(state), type(exc).__name__
        artifact = AgentArtifact(name, status, output, model=model, error=error)
        self._record(itinerary_id, correlation_id, artifact, state, started, datetime.now(timezone.utc))
        return artifact

    @staticmethod
    def _intent(state):
        text = state["message"]
        hard = []
        for token in ("预约", "必须", "不要排队", "步行"):
            if token in text:
                hard.append(token)
        return {"city": state["city"], "request": text, "hard_constraints": hard, "needs_clarification": not bool(state["city"])}

    @staticmethod
    def _places(state):
        verified, unknown = [], []
        for item in state.get("candidates", []):
            place = item.get("place") if isinstance(item, dict) else None
            if place and place.get("name") and (place.get("location") or (place.get("latitude") is not None and place.get("longitude") is not None)):
                verified.append({"id": place.get("id"), "name": place.get("name"), "provider": place.get("provider", "unknown")})
            else:
                unknown.append(item.get("query", "unknown") if isinstance(item, dict) else "unknown")
        return {"verified": verified, "unknown": unknown}

    @staticmethod
    def _review(state):
        plan = state.get("plan") or {}
        conflicts = plan.get("conflicts", [])
        return {"approved": not bool(conflicts), "conflicts": conflicts, "reason": "硬约束已通过" if not conflicts else "存在硬约束冲突"}

    def _record(self, itinerary_id, correlation_id, artifact, state, started, finished):
        if not self.db:
            return
        self.db.connection.execute(
            "INSERT INTO agent_runs(id,itinerary_id,correlation_id,agent_name,status,model,policy_version,input_json,output_json,error,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), itinerary_id, correlation_id, artifact.agent_name, artifact.status, artifact.model, artifact.policy_version, json.dumps({"city": state.get("city"), "message": state.get("message", "")[:200]}, ensure_ascii=False), json.dumps(artifact.output, ensure_ascii=False), artifact.error, started.isoformat(), finished.isoformat()),
        )
        self.db.connection.commit()
