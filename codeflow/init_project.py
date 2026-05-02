from __future__ import annotations

from pathlib import Path


DEFAULT_PROJECT_RULES = """# Project Rules

- Keep changes minimal and relevant.
- Do not delete existing tests.
- Do not bypass failing tests.
- Do not modify secrets, credentials, or environment files.
- Add or update tests for new behavior.
- Prefer small patches over broad rewrites.
"""


DEFAULT_CODEFLOW_YAML = """harness:
  required_checks:
    - pytest -q
    - ruff check .

  max_repair_rounds: 3
  max_diff_lines: 500

  allowed_paths: []

  forbidden_paths:
    - .env
    - .env.*
    - secrets/
    - credentials/
    - "*.pem"
    - "*.key"

  high_risk_paths:
    - app/auth/
    - app/db/
    - migrations/
    - config/

  require_test_change: true
  allow_dependency_change: false
  allow_delete_tests: false
  allow_shell_checks: false
  semantic_spec: true
  semantic_review: true
  require_semantic_review: false
  semantic_timeout_seconds: 60
  semantic_max_diff_chars: 20000
  semantic_fail_open: true
  semantic_required_for_paths:
    - app/auth/
    - migrations/

  governance:
    block_commit_on_failed_checks: true
    block_commit_on_high_risk: false
    require_human_approval: true
    rerun_checks_before_commit: true
"""


def init_project(repo: str, *, force: bool = False) -> list[Path]:
    root = Path(repo).expanduser().resolve()
    codeflow_dir = root / ".codeflow"
    rules_path = codeflow_dir / "project_rules.md"
    policy_path = codeflow_dir / "codeflow.yaml"
    existing = [path for path in (rules_path, policy_path) if path.exists()]
    if existing and not force:
        rendered = ", ".join(str(path.relative_to(root)) for path in existing)
        raise RuntimeError(f"CodeFlow config already exists: {rendered}. Use --force to overwrite.")

    codeflow_dir.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(DEFAULT_PROJECT_RULES, encoding="utf-8")
    policy_path.write_text(DEFAULT_CODEFLOW_YAML, encoding="utf-8")
    return [rules_path, policy_path]
