"""Reproducible V1 evaluation runner; no business implementation is bundled."""
import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixtures.contract import load_cases, validate_result  # noqa: E402
from tripflow.qwen_agent import QwenAgent  # noqa: E402


def get_adapter(spec):
    if not spec:
        return None, "not provided"
    module_name, class_name = spec.split(":", 1)
    try:
        return getattr(importlib.import_module(module_name), class_name)(), None
    except Exception as exc:
        return None, f"load failed: {type(exc).__name__}: {exc}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=os.environ.get("TRIPFLOW_ADAPTER"))
    ap.add_argument("--report", default="reports/latest.json")
    args = ap.parse_args()
    data_version, api_mode, cases = load_cases()
    adapter, adapter_error = get_adapter(args.adapter)
    rows = []
    for case in cases:
        if adapter is None:
            rows.append({"id": case.id, "status": "NOT_EXECUTED", "detail": "business adapter unavailable"})
            continue
        try:
            result = adapter.handle(case.kind, case.request)
            ok, detail = validate_result(case, result)
            rows.append({"id": case.id, "status": "PASS" if ok else "FAIL", "detail": detail, "actual": result})
        except TimeoutError as exc:
            rows.append({"id": case.id, "status": "FAIL", "detail": f"unexpected timeout: {exc}"})
        except Exception as exc:
            rows.append({"id": case.id, "status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"})
    counts = {s: sum(r["status"] == s for r in rows) for s in ("PASS", "FAIL", "ERROR", "NOT_EXECUTED")}
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_version": data_version,
        "api_mode": api_mode,
        "real_api": False,
        "adapter": args.adapter,
        "adapter_error": adapter_error,
        "qwen": QwenAgent().status() | {"live_validation": os.environ.get("TRIPFLOW_QWEN_LIVE_RESULT", "not_run")},
        "total_denominator": len(rows),
        "counts": counts,
        "metrics": {
            "scenario_contract_pass_rate": {"numerator": counts["PASS"], "denominator": len(rows), "condition": "adapter executed and exact expected status/reason_code matched"},
            "execution_coverage": {"numerator": len(rows) - counts["NOT_EXECUTED"], "denominator": len(rows), "condition": "adapter was available and case was invoked"},
        },
        "cases": rows,
    }
    out = ROOT / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out), "data_version": data_version, "real_api": False, "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
