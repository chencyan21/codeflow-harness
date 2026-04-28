from __future__ import annotations

from codeflow.harness.policy import format_policy_for_prompt
from codeflow.models import HarnessPolicy, Spec


def build_guidance_context(spec: Spec, rules: str, policy: HarnessPolicy) -> str:
    criteria = "\n".join(f"- {item}" for item in spec.acceptance_criteria)
    constraints = "\n".join(f"- {item}" for item in spec.constraints)
    return "\n\n".join(
        [
            "Structured Spec:",
            f"Goal: {spec.goal}",
            "Acceptance criteria:",
            criteria,
            "Constraints:",
            constraints,
            "Project Rules:",
            rules.strip(),
            format_policy_for_prompt(policy),
        ]
    )
