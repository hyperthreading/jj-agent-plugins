# Shared guidance implementation checks

Date: 2026-11-05. This is an isolated implementation candidate, not an adoption or release decision. The implementation starts from `f36f98bda089231e84a2066fed4adb30d541d241` and is developed in `/Users/jun/workspace/jj-agent-guidance-shared`. The original `random/jj-agent-plugins` checkout is not used as the runtime installation under test.

## Reproduce

```bash
bash scripts/isolated.sh bash scripts/check.sh
bash scripts/isolated.sh python3 tests/guidance-bench.py
```

The wrapper creates private HOME/XDG, jj/Git configuration and client data directories. Run it from this checkout. It does not copy credentials. For any actual client run, inspect system/managed and ancestor configuration sources as well; private HOME alone does not establish isolation.

## Results

| Check | Result |
|---|---|
| Generated preamble/task loop and both skill distributions | Match |
| Shared state fixtures | 7 cases pass in bash and compass TS; the unnamed-merge branch spelling is the only declared difference |
| Packaged guidance, defaults, independent L0/L1 and lifecycle | 13 tests pass |
| Grader fixtures | 9 tests pass, including wrong-change edits, script-internal Git loss without import op, and unknown for missing/truncated/background evidence |
| Enabled safeguards, full/minimal PATH, Muse recovery | 104 checks pass |
| Whole prompt/reset latency | Recorded in [BENCHMARK.md](../BENCHMARK.md); 30,000-file edited prompt p50 132.17ms, p95 137.92ms |

The packaged-hook tests copy the plugin or its scripts to a new directory; the APM-style test removes that plugin copy and runs only the copied script tree. They establish file self-containment, not that the APM installer produced those files. APM CLI is not installed in this environment, so `apm pack --check-versions` and actual APM installation have not run. Package versions remain at the existing 0.4.0; this candidate has not been published.

The state-error test reproduces a snapshot failure while ordinary recorded-state reads still work. It verifies that the hook reports stale state instead of emitting the old state as current. Existing detection regressions continue to cover recovery and the known false-positive/mid-turn gaps.

## Remaining actual-client evidence

No model evaluation has run. Budget and model selection are pending in [evals/plan.yaml](../evals/plan.yaml). The eval code currently prepares cases/arms, validates deterministic outcomes and normalizes candidate client log shapes. A selected-client launcher still needs isolated installation, session resume/compaction control, verified full observation and spend/step enforcement. See [evals/README.md](../evals/README.md).

Claude Code, Codex and OpenCode still require actual first-request, unchanged-request, external-change, workspace-switch, clear/resume/compaction delivery checks, final skill selection/body checks and the mandatory behavioral smoke. Client-specific controls for opting out of individual packaged skills must be confirmed there. Muse L1 and OpenCode L4 remain deferred. Passing model-free checks does not establish the design's C1–C7 completion or a comparative benefit.

The OpenCode implementation records the exact shared source revision in its `src/agent/SHARED_VERSION` and keeps its adapter/package verification with the accepted design.
