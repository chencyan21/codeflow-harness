# Benchmark Failure Taxonomy

Benchmark failures must be classified so reports can separate agent behavior from external
environment issues.

| Category | Meaning | Counts As Agent Failure |
| --- | --- | --- |
| `agent_no_change` | Agent made no effective task change | yes |
| `agent_wrong_fix` | Agent changed code but failed task semantics | yes |
| `checks_failed` | Validation checks failed after the attempt | yes |
| `repair_failed` | Repair loop exhausted without success | yes |
| `sensor_blocked` | Harness sensor blocked the diff | depends on risk task |
| `semantic_review_blocked` | Semantic review blocked or required manual review | depends on risk |
| `policy_blocked` | Realtime policy blocked command/file write | depends on risk task |
| `setup_failed` | Workspace setup commands failed | no |
| `dependency_failed` | Dependency installation/runtime environment failed | no |
| `checkout_failed` | Git checkout, clone or patch application failed | no |
| `network_failed` | Network or DNS failure | no |
| `llm_api_failed` | Provider API failure, auth failure or rate limit | no |
| `llm_timeout` | Model call timed out | no |
| `checks_timeout` | Validation checks timed out | usually environment/task issue |
| `invalid_model_output` | Model returned malformed control output | yes |
| `workspace_dirty` | Workspace precondition failed | no |
| `benchmark_runner_error` | Benchmark script/framework error | no |
| `unknown` | Unclassified failure | review required |

Every formal report should include a failure taxonomy table and should not merge environment
failures into the agent pass rate.
