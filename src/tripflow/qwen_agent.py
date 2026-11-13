"""Optional Qwen Agent boundary using DashScope's OpenAI-compatible API.

Qwen is advisory only: it produces a structured explanation/constraint
summary after deterministic planning. It never creates or mutates activities
and never overrides the planner's hard-constraint result.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "constraints_checked": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["explanation", "constraints_checked", "warnings"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class QwenSettings:
    api_key: str
    model: str = "qwen-plus"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout_seconds: float = 15.0
    enabled: bool = True

    DEFAULT_MODEL = "qwen-plus"
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DEFAULT_TIMEOUT_SECONDS = 15.0

    @classmethod
    def from_env(cls) -> "QwenSettings | None":
        key = (os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
        if not key:
            return None
        base = (os.getenv("QWEN_API_BASE") or os.getenv("DASHSCOPE_BASE_URL") or cls.DEFAULT_BASE_URL).rstrip("/")
        model = os.getenv("QWEN_MODEL") or os.getenv("DASHSCOPE_MODEL") or cls.DEFAULT_MODEL
        enabled = os.getenv("QWEN_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        return cls(key, model, base, float(os.getenv("QWEN_TIMEOUT_SECONDS", cls.DEFAULT_TIMEOUT_SECONDS)), enabled)


HttpPost = Callable[[str, dict[str, str], bytes, float], bytes]


def urllib_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class QwenAgent:
    def __init__(self, settings: QwenSettings | None = None, post: HttpPost = urllib_post):
        self.settings = settings if settings is not None else QwenSettings.from_env()
        self.post = post

    @property
    def configured(self) -> bool:
        return self.settings is not None and self.settings.enabled

    def status(self) -> dict[str, Any]:
        """Return safe configuration metadata; never includes the API key."""
        if self.settings is None:
            return {"configured": False, "enabled": False, "mode": "deterministic_fallback"}
        return {"configured": True, "enabled": self.settings.enabled, "mode": "qwen_structured_advisory", "model_configured": bool(self.settings.model), "base_configured": bool(self.settings.base_url)}

    def explain_plan(self, plan: dict[str, Any]) -> dict[str, Any] | None:
        if not self.configured:
            return None
        assert self.settings is not None
        payload = {
            "model": self.settings.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "Explain a deterministic travel plan. Do not change the plan. Return only the requested JSON object."},
                {"role": "user", "content": json.dumps(plan, ensure_ascii=False, separators=(",", ":"))},
            ],
            "response_format": {"type": "json_schema", "json_schema": {"name": "tripflow_plan_explanation", "schema": JSON_SCHEMA, "strict": True}},
        }
        try:
            raw = self.post(self.settings.base_url + "/chat/completions", {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}, json.dumps(payload, ensure_ascii=False).encode("utf-8"), self.settings.timeout_seconds)
            response = json.loads(raw.decode("utf-8"))
            content = response["choices"][0]["message"]["content"]
            result = json.loads(content) if isinstance(content, str) else content
            self._validate(result)
            return {"status": "success", "mode": "qwen_structured_advisory", "model": self.settings.model, "data": result}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"status": "fallback", "mode": "deterministic_fallback", "error_type": type(exc).__name__}

    def draft_guide(self, message: str, city: str) -> dict[str, Any]:
        """Extract travel intent; downstream map search must verify every place."""
        if not self.configured:
            raise ValueError("Qwen is not configured")
        assert self.settings is not None
        schema = {"type": "object", "properties": {
            "title": {"type": "string"}, "summary": {"type": "string"},
            "style": {"type": "string"}, "place_queries": {"type": "array", "items": {"type": "string"}},
            "tips": {"type": "array", "items": {"type": "string"}}
        }, "required": ["title", "summary", "style", "place_queries", "tips"], "additionalProperties": False}
        payload = {"model": self.settings.model, "temperature": 0.4, "messages": [
            {"role": "system", "content": "你是旅行规划助手。根据用户需求提出不超过5个地点搜索词与简短攻略框架。地点只是待地图核实的搜索建议，不要断言价格、营业时间、交通耗时或预订状态。只返回符合 JSON Schema 的简体中文。"},
            {"role": "user", "content": json.dumps({"city": city, "request": message[:1200]}, ensure_ascii=False)}
        ], "response_format": {"type": "json_schema", "json_schema": {"name": "tripflow_guide", "schema": schema, "strict": True}}}
        raw = self.post(self.settings.base_url + "/chat/completions", {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}, json.dumps(payload, ensure_ascii=False).encode("utf-8"), self.settings.timeout_seconds)
        response = json.loads(raw.decode("utf-8"))
        content = response["choices"][0]["message"]["content"]
        guide = json.loads(content) if isinstance(content, str) else content
        if not isinstance(guide, dict) or any(not isinstance(guide.get(k), str) for k in ("title", "summary", "style")) or any(not isinstance(guide.get(k), list) for k in ("place_queries", "tips")):
            raise ValueError("invalid guide response")
        guide["place_queries"] = [x[:80] for x in guide["place_queries"] if isinstance(x, str) and x.strip()][:5]
        guide["tips"] = [x[:160] for x in guide["tips"] if isinstance(x, str)][:5]
        return guide

    @staticmethod
    def _validate(value: Any) -> None:
        if not isinstance(value, dict) or not isinstance(value.get("explanation"), str) or not isinstance(value.get("constraints_checked"), list) or not isinstance(value.get("warnings"), list):
            raise ValueError("Qwen response did not match the JSON schema")
