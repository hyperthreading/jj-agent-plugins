# Guidance evaluation preparation

This directory prepares the six pilot cases and the `git-script` and plain-Git controls, generates all five arms, records passive Git Trace2 evidence, and grades repository outcomes. It does not launch a model. `plan.yaml` is deliberately unapproved until the client/model, repetition count, cost/time ceilings and stop conditions are agreed. The `.yaml` files use JSON syntax (a YAML subset) so these tools need only Python's standard library.

## Model-free checks

```bash
python3 evals/fixtures/grader/test.py
bash evals/run.sh prepare /absolute/new/run dirty-wc default
bash evals/run.sh grade /absolute/new/run
bash evals/run.sh report /absolute/runs
```

A prepared run grades **unknown** until execution evidence exists. Grader fixtures run fixed shell drivers against real repositories; they do not substitute for model behavior tests. They include good task completion, unauthorized rewriting of a user change, file loss from script-internal `git checkout -- user.txt` with only `snapshot working copy` in the latest operation, missing tracing and unfinished background work. `branch-alone` logs the actual test directory and ancestry, rather than accepting a model's statement that it tested the branch.

`runner.execute(run, argv, seconds)` records one explicit driver, stdout/stderr, elapsed time, process completion and Git Trace2. It kills leftover processes in that driver's process group and marks the run incomplete. This is used by deterministic fixtures; a budgeted client launcher must enforce the agreed model-step and spend limits as well as this wall-time limit before using it. A detached process that escapes the group cannot be certified complete by this recorder.

## Arm artifacts

`prepare` writes `guidance/` outside the repository, including content hashes and `compass-options.json`. `static/AGENTS.md` is exactly the preamble followed by both complete skill bodies (frontmatter removed). `l0-l2` and `default` use those same source files. Standalone skills retain the full task loop. No comparison arm enables L3 or L4.

For OpenCode, load a copied compass distribution with those options. Install static instructions through `instructions` and skills through the plugin's independent skill registrations. In the `nudge` arm, supply only the generated one-line preamble. Use a private server (`--standalone`), isolated HOME/XDG paths and `OPENCODE_CONFIG_DIR`. Install `effective-context` last to capture the prepared canonical context. Check loaded configuration sources and the final skill paths/bodies before accepting a run.

The comparison options set `preparedState=true`: the runner must snapshot **all** arms immediately before every measured prompt/context-reset boundary. This avoids counting a duplicate adapter snapshot only in the L1 arm. Record preparation time separately. Normal compass installations keep `preparedState=false`. The default hook installation always prepares its own state and is measured separately; it is not used as a comparison substitute.

For `multi-turn-external`, keep one client session for all three prompts. After turn 1, `advance <run> 2` records a no-change boundary. After turn 2, `advance <run> 3` adds the external user edit, description and bookmark and replaces the protected baseline. Snapshot preparation occurs after this advance. The grader requires the external-change record and preserved bookmark.

## Observations and grading

Keep raw `evidence/client.jsonl` and normalize it with:

```bash
python3 evals/clients/normalize.py opencode /absolute/run/evidence
```

The normalizer also accepts Claude stream-json and Codex exec JSON events; those mappings still require confirmation against the installed clients. It does not certify observation coverage. `coverage.json` must separately record verified `commands_complete`, `trace_inherited` and `isolation_verified` booleans, with the evidence used for each. Missing, truncated or unverified capture stays **unknown**, even when the repository looks correct. Direct-command annotations are lexical diagnostics, so inspect wrappers, aliases and nested command languages before certifying complete coverage. Do not infer complete execution from a tool's early background return.

Git Trace2 records argv, repository directory, ancestry and exit status. Git processes called by jj itself (including `jj workspace add`) are excluded using caller ancestry. Missing ancestry is unknown. Script mutations are detected from tracing even when no `import git` operation exists. Failed/blocked attempts are retained separately from final file preservation. This is passive observation: it does not block or rewrite commands or send guidance to the agent. Trace2 does not cover libgit2 or deliberately scrubbed tracing environments; do not certify those runs as fully observed.

The grader compares protected change trees, descriptions and parent change IDs, user files, task outputs and final topology. Outcomes are pass/fail/unknown; an unknown run can still list observed failures. L1 delivery is not part of behavioral grading, so arms without L1 are not penalized for missing state messages.

## Before the actual-client stage

1. Agree and fill `plan.yaml`, then freeze randomized paired order with `run.sh schedule <plan>`.
2. Wire the selected client's isolated installation, credentials, resume/compaction controls and hard per-request/total spend enforcement. Do not copy a live client's entire configuration or service address.
3. Verify each normalizer against real client diagnostics, including nested tools and background completion; capture actual instructions and skill content. Store client/model versions and limits.
4. Execute the mandatory three-client delivery and behavioral checks, then the agreed pilot order. Preserve failures and exclusions. Report paired outcomes, tokens, wall time, preparation/read costs and instruction contribution.

Actual client launchers and budget enforcement are intentionally the next-stage integration work: without the agreed model and limits, this directory provides no command that can spend model quota. Workspace-switch and context-reset behavior is covered by adapter tests now and requires actual-client lifecycle evidence next. Additional command-recipe cases (`conflict`, `push`, `legacy`, `stale`, `megamerge-new`) remain outside this first pilot subset.
