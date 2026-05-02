from __future__ import annotations

import json
import os
import re
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
    result = _semantic_json("spec", payload, client=client)
    if not result:
        return base_spec, None

    criteria = _strings(result.get("acceptance_criteria"))
    constraints = _strings(result.get("constraints"))
    notes = _strings(result.get("semantic_notes") or result.get("notes"))
    enhanced = Spec(
        task_type=str(result.get("task_type") or base_spec.task_type),
        goal=str(result.get("goal") or base_spec.goal),
        acceptance_criteria=_merge_unique(base_spec.acceptance_criteria, criteria),
        constraints=_merge_unique(base_spec.constraints, constraints),
        semantic_notes=notes,
    )
    return enhanced, {"status": "completed", "result": result}


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
    if not (policy.semantic_review or policy.require_semantic_review):
        return None
    payload = {
        "task": task,
        "diff": redact_text(diff[-20000:]),
        "changed_files": changed_files,
        "checks": [result.model_dump() for result in check_results],
        "sensor_report": sensor_report.model_dump() if sensor_report else None,
    }
    result = _semantic_json("review", payload, client=client)
    if not result:
        return None

    risk = str(result.get("risk_level") or "low").lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    return {
        "status": "completed",
        "risk_level": risk,
        "summary": str(result.get("summary") or ""),
        "findings": _strings(result.get("findings")),
        "recommendation": str(result.get("recommendation") or ""),
        "task_alignment": str(result.get("task_alignment") or ""),
        "test_coverage_notes": str(result.get("test_coverage_notes") or ""),
    }


def semantic_llm_available() -> bool:
    return _semantic_config() is not None


def _semantic_json(
    kind: str,
    payload: dict[str, Any],
    *,
    client: SemanticJsonClient | None,
) -> dict[str, Any] | None:
    if client:
        return client(kind, payload)
    config = _semantic_config()
    if config is None:
        return None
    try:
        return _call_openai_compatible(kind, payload, config)
    except Exception:
        return None


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


def _call_openai_compatible(kind: str, payload: dict[str, Any], config: dict[str, str]) -> dict[str, Any] | None:
    from openai import OpenAI

    if base_url := config.get("base_url"):
        client = OpenAI(api_key=config["api_key"], base_url=base_url)
    else:
        client = OpenAI(api_key=config["api_key"])
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
            "findings": ["specific concern or confirmation"],
            "recommendation": "commit|review|block with rationale",
            "task_alignment": "whether the diff appears aligned with the task",
            "test_coverage_notes": "test coverage assessment",
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
