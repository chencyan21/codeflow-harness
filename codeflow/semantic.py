from __future__ import annotations

import json
import os
import re
import fnmatch
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from codeflow.models import CheckResult, HarnessPolicy, HarnessSensorReport, Spec
from codeflow.redaction import redact_text

SemanticJsonClient = Callable[[str, dict[str, Any]], dict[str, Any] | None]


def enhance_spec_with_semantics(
    *,
    task: str,
    rules: str,
    policy: HarnessPolicy,
    base_spec: Spec,
    client: SemanticJsonClient | None = None,
) -> tuple[Spec, dict[str, Any] | None]:
    if not policy.semantic_spec:
        return base_spec, None
    payload = {
        "task": task,
        "project_rules": rules,
        "base_spec": base_spec.model_dump(),
        "required_checks": policy.required_checks,
    }
    result = _semantic_json_result(
        "spec",
        payload,
        client=client,
        timeout_seconds=policy.semantic_timeout_seconds,
    )
    if result["status"] != "completed":
        return base_spec, None
    semantic_data = result["result"]

    criteria = _strings(semantic_data.get("acceptance_criteria"))
    constraints = _strings(semantic_data.get("constraints"))
    notes = _strings(semantic_data.get("semantic_notes") or semantic_data.get("notes"))
    enhanced = Spec(
        task_type=str(semantic_data.get("task_type") or base_spec.task_type),
        goal=str(semantic_data.get("goal") or base_spec.goal),
        acceptance_criteria=_merge_unique(base_spec.acceptance_criteria, criteria),
        constraints=_merge_unique(base_spec.constraints, constraints),
        semantic_notes=notes,
    )
    return enhanced, {"status": "completed", "result": semantic_data}


def review_diff_with_semantics(
    *,
    task: str,
    diff: str,
    changed_files: list[str],
    check_results: list[CheckResult],
    sensor_report: HarnessSensorReport | None,
    policy: HarnessPolicy,
    client: SemanticJsonClient | None = None,
) -> dict[str, Any] | None:
    path_required = semantic_review_required_for_paths(policy, changed_files)
    if not (policy.semantic_review or policy.require_semantic_review or path_required):
        return None
    payload = {
        "task": task,
        "diff": redact_text(diff[-policy.semantic_max_diff_chars :]),
        "changed_files": changed_files,
        "checks": [result.model_dump() for result in check_results],
        "sensor_report": sensor_report.model_dump() if sensor_report else None,
    }
    result = _semantic_json_result(
        "review",
        payload,
        client=client,
        timeout_seconds=policy.semantic_timeout_seconds,
    )
    if result["status"] != "completed":
        blocking = policy.require_semantic_review or path_required or not policy.semantic_fail_open
        return {
            "status": "unavailable",
            "reason": result.get("reason", "unknown"),
            "message": result.get("message", ""),
            "risk_level": "high" if blocking else "medium",
            "summary": result.get("message", "Semantic review did not complete."),
            "findings": [
                {
                    "severity": "high" if blocking else "medium",
                    "file": "",
                    "reason": result.get("message", "Semantic review did not complete."),
                    "suggested_action": "Configure semantic review or rerun after the model/API issue is fixed.",
                }
            ],
            "recommendation": "block" if blocking else "manual_review",
            "task_alignment": "unknown",
            "test_coverage": {"level": "unknown", "notes": ""},
            "test_coverage_notes": "",
            "behavioral_risks": [],
            "security_risks": [],
            "data_migration_risks": [],
            "required_by_path": path_required,
        }

    semantic_data = result["result"]
    risk = str(semantic_data.get("risk_level") or "low").lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    test_coverage = _test_coverage(semantic_data.get("test_coverage"), semantic_data.get("test_coverage_notes"))
    return {
        "status": "completed",
        "risk_level": risk,
        "summary": str(semantic_data.get("summary") or ""),
        "findings": _findings(semantic_data.get("findings")),
        "recommendation": str(semantic_data.get("recommendation") or ""),
        "task_alignment": str(semantic_data.get("task_alignment") or "unknown"),
        "test_coverage": test_coverage,
        "test_coverage_notes": test_coverage["notes"],
        "behavioral_risks": _strings(semantic_data.get("behavioral_risks")),
        "security_risks": _strings(semantic_data.get("security_risks")),
        "data_migration_risks": _strings(semantic_data.get("data_migration_risks")),
        "required_by_path": path_required,
    }


def semantic_llm_available() -> bool:
    return _semantic_config() is not None


def semantic_review_required_for_paths(policy: HarnessPolicy, changed_files: list[str]) -> bool:
    return any(
        _matches_path(path, pattern)
        for path in changed_files
        for pattern in policy.semantic_required_for_paths
    )


def _semantic_json_result(
    kind: str,
    payload: dict[str, Any],
    *,
    client: SemanticJsonClient | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    if client:
        try:
            result = client(kind, payload)
        except Exception as exc:
            reason = _exception_reason(exc)
            return {"status": "unavailable", "reason": reason, "message": str(exc)}
        if isinstance(result, dict):
            return {"status": "completed", "result": result}
        return {
            "status": "unavailable",
            "reason": "invalid_json",
            "message": "Semantic client did not return a JSON object.",
        }
    config = _semantic_config()
    if config is None:
        return {
            "status": "unavailable",
            "reason": "missing_config",
            "message": "Semantic LLM configuration is missing.",
        }
    try:
        result = _call_openai_compatible(kind, payload, config, timeout_seconds=timeout_seconds)
    except Exception as exc:
        reason = _exception_reason(exc)
        return {"status": "unavailable", "reason": reason, "message": str(exc)}
    if isinstance(result, dict):
        return {"status": "completed", "result": result}
    return {
        "status": "unavailable",
        "reason": "invalid_json",
        "message": "Semantic model did not return a JSON object.",
    }


def _semantic_config() -> dict[str, str] | None:
    env_values = _load_codeflow_env()
    model = _first_nonempty(
        os.environ.get("CODEFLOW_SEMANTIC_MODEL"),
        os.environ.get("MSWEA_MODEL_NAME"),
        env_values.get("semantic_model"),
        env_values.get("model_id"),
        env_values.get("MODEL_ID"),
    )
    api_key = _first_nonempty(
        os.environ.get("OPENAI_API_KEY"),
        env_values.get("api_key"),
        env_values.get("API_KEY"),
    )
    base_url = _first_nonempty(
        os.environ.get("OPENAI_BASE_URL"),
        os.environ.get("OPENAI_API_BASE"),
        env_values.get("base_url"),
        env_values.get("BASE_URL"),
    )
    if not model or not api_key:
        return None
    config = {"model": model, "api_key": api_key}
    if base_url:
        config["base_url"] = base_url
    return config


def _load_codeflow_env() -> dict[str, str]:
    env_file = os.environ.get("CODEFLOW_ENV_FILE")
    path = Path(env_file).expanduser() if env_file else Path.cwd() / ".env"
    if not path.exists():
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def _call_openai_compatible(
    kind: str,
    payload: dict[str, Any],
    config: dict[str, str],
    *,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    from openai import OpenAI

    if base_url := config.get("base_url"):
        client = OpenAI(api_key=config["api_key"], base_url=base_url, timeout=timeout_seconds)
    else:
        client = OpenAI(api_key=config["api_key"], timeout=timeout_seconds)
    response = client.chat.completions.create(
        model=config["model"],
        messages=[
            {
                "role": "system",
                "content": (
                    "You are CodeFlow's semantic reviewer. Return only strict JSON. "
                    "Do not include markdown fences."
                ),
            },
            {"role": "user", "content": _prompt(kind, payload)},
        ],
        temperature=0,
    )
    content = response.choices[0].message.content or ""
    return _parse_json_object(content)


def _prompt(kind: str, payload: dict[str, Any]) -> str:
    schema: dict[str, Any]
    if kind == "spec":
        schema = {
            "task_type": "coding_task|bugfix|test|refactor|docs",
            "goal": "one precise goal",
            "acceptance_criteria": ["criterion"],
            "constraints": ["constraint"],
            "semantic_notes": ["short note"],
        }
    else:
        schema = {
            "risk_level": "low|medium|high",
            "summary": "semantic summary",
            "findings": [
                {
                    "severity": "low|medium|high",
                    "file": "path or empty",
                    "reason": "specific issue or confirmation",
                    "suggested_action": "what to inspect or change",
                }
            ],
            "recommendation": "commit|manual_review|block",
            "task_alignment": "aligned|partial|not_aligned|unknown",
            "test_coverage": {"level": "none|weak|adequate|strong", "notes": "coverage assessment"},
            "behavioral_risks": ["risk"],
            "security_risks": ["risk"],
            "data_migration_risks": ["risk"],
        }
    return json.dumps({"kind": kind, "schema": schema, "payload": payload}, ensure_ascii=False)


def _parse_json_object(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else None


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _findings(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    findings: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            severity = str(item.get("severity") or "medium").lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            findings.append(
                {
                    "severity": severity,
                    "file": str(item.get("file") or ""),
                    "reason": str(item.get("reason") or item.get("message") or ""),
                    "suggested_action": str(
                        item.get("suggested_action") or item.get("recommendation") or ""
                    ),
                }
            )
        else:
            text = str(item).strip()
            if text:
                findings.append(
                    {
                        "severity": "medium",
                        "file": "",
                        "reason": text,
                        "suggested_action": "",
                    }
                )
    return findings


def _test_coverage(value: object, fallback_notes: object) -> dict[str, str]:
    if isinstance(value, dict):
        level = str(value.get("level") or "unknown").lower()
        notes = str(value.get("notes") or fallback_notes or "")
    else:
        level = "unknown"
        notes = str(fallback_notes or "")
    if level not in {"none", "weak", "adequate", "strong", "unknown"}:
        level = "unknown"
    return {"level": level, "notes": notes}


def _matches_path(path: str, pattern: str) -> bool:
    normalized = path.strip("/")
    normalized_pattern = pattern.strip("/")
    if not normalized_pattern:
        return False
    if pattern.endswith("/"):
        return normalized == normalized_pattern or normalized.startswith(f"{normalized_pattern}/")
    return normalized == normalized_pattern or fnmatch.fnmatch(normalized, normalized_pattern)


def _exception_reason(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    text = f"{exc.__class__.__name__}: {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "api_error"


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*first, *second]:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _first_nonempty(*values: object) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
