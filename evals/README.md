# Guidance evaluation

**The 2026-11-05 campaign is stopped.** Eight mandatory smoke runs passed; Claude's external-change run triggered the version-1 current-workspace preservation condition. All three Git controls and the 30-run pilot remain unexecuted. [Results and evidence](results/2026-11-05/README.md) record the first attempts, the stop investigation and **$2.182575 API-equivalent usage**. On 2026-11-06 the user clarified that task intent determines the base; [ADR 0006](../docs/adr/0006-intent-aware-task-placement.md) records the new contract. Further model calls require renewed user direction; the approval in `plan.yaml` records the original campaign, not permission to restart it.

This directory prepares fixed cases, installs isolated clients, captures requests and tools, enforces request budgets, and grades repository outcomes. It uses Python's standard library; `.yaml` files use JSON syntax. The client launcher targets macOS Seatbelt and the selected loopback model gateway.

## Model-free checks

```bash
bash scripts/isolated.sh bash scripts/check.sh
bash evals/run.sh prepare /absolute/new/run dirty-wc default
bash evals/run.sh grade /absolute/new/run
bash evals/run.sh report /absolute/runs
```

The check script includes the grader and client-control suites. A prepared run grades **unknown** until execution evidence exists. Grader fixtures use fixed shell drivers in real repositories; they do not establish model behavior. Cases cover independent/dependent tasks, continuation, empty-change reuse, wrong-change edits, script-internal Git loss without an import operation, missing/truncated observations and unfinished background work. The same branch-from-main example passes contract 2 and fails the legacy workspace-content rule.

## Execution and limits

| File | Responsibility |
|---|---|
| `clients/launch.py` | Fresh fixture, copied packages, native installation, private client home, Seatbelt, resume, preservation checks and process cleanup |
| `clients/gateway.py` | Capture final client HTTP bodies, admit metered requests, cap output and collect streamed usage |
| `clients/budget.py` | Locked, durable campaign ledger with reservations before dispatch |
| `clients/delivery.py` | Check model/effort, L0, L1 and skill advertisements in the first request; OpenCode also checks registered skill bodies |
| `clients/finalize.py` | Pair CLI and passive observations, assess coverage, archive earlier grades and grade the repository |
| `clients/campaign.py` | Serial mandatory smoke; pilot requires explicit C1–C7 acceptance evidence |
| `clients/export.py` | Read a stopped campaign and export compact results and hashes without launching clients or changing its ledger |

The original approval is **$30 / 90 minutes total**, **$1 / 3 minutes / 30 model requests per run**, with an immediate preservation stop. Every forwarded HTTP request counts, including visible retries and auxiliary model calls. Turns share one run budget. The ledger refuses concurrent launchers, plan changes and reuse of a run ID. Missing usage retains its reservation and stops the campaign.

The selected models are `opencodex/gpt-6.1-terra#medium` for OpenCode, `gpt-6.1-terra` with medium effort for Codex, and `claude-sonnet-5-5` with medium effort for Claude Code. All three settings were observed in actual client requests. Sonnet's model name is rewritten to `anthropic/claude-sonnet-5-5` upstream.

API-equivalent rates per million tokens are Terra input/output **$2.5/$7.5** and Sonnet **$4/$10**. Cache discounts are not credited. These are approved accounting rates, not subscription billing. The proxy reserves serialized UTF-8 request bytes plus 8,192 framing tokens as an input bound, caps output at 8,192 tokens, and rejects opaque previous-response context and unpriced media/hosted tools. A reported token-bound breach stops execution. Hidden upstream retries and actual subscription charges are not observable.

After renewed approval, launch commands have this shape:

```bash
python3 evals/clients/launch.py /absolute/new/campaign/run opencode basic --capture-only
python3 evals/clients/delivery.py /absolute/new/campaign/run opencode
python3 evals/clients/campaign.py /absolute/new/campaign smoke
```

`--capture-only` records the client's request and rejects it before upstream dispatch. It does not establish model behavior. Native clients also support delivery captures with `--apm /absolute/path/to/apm`, `--package jj-skill`, `--no-preamble`, `--no-state` and `--disable-skill`. The Claude per-skill denial capture **failed to hide the advertisement**; it is retained as a C2 gap. Comparative arms are implemented only for OpenCode.

## Isolation and provenance

Each run has private HOME/XDG/client directories and jj/Git configuration. Only the `opencodex` connection is read from the host's OpenCode config; the upstream key stays in the proxy process. Client config uses an ephemeral local token. Installation occurs in the private environment before the sandboxed model session starts.

Seatbelt permits writes under the run's `home`, `tmp`, `repo` and `workspaces`; it denies other home-data reads except installed tool roots. Network access is limited to the local proxy, the private OpenCode server and Unix sockets. Before paid dispatch, `isolation.json` records probes for denied live-config reads, outside writes and direct upstream access, plus allowed proxy access and enumerated managed-source checks. This is a fixed-client evaluation boundary, not certification against hostile environment scrubbing, Unix-socket relays or in-process Git libraries.

OpenCode uses an owned `serve --stdio --hostname 127.0.0.1 --port <port>` process and `run --server`, with a private password. `--standalone` selects a port the narrow network policy cannot know in advance. Server shutdown, child cleanup and request settlement finish before the ledger lock is released. The launcher requires a loopback HTTP upstream with an explicit port and installed tools reachable through the host's `.local` tool roots or system paths.

`versions.json` identifies jj and the source revision at fixture preparation. Source copies, active configurations, installation logs, final requests, responses, baseline/final trees, op logs, Trace2 and client events remain under each run. New launches also hash the complete copied package source (excluding dependencies) and evaluator files. The stopped campaign predates that complete launcher-hash capture; its export hashes retained files after the run and does not claim a retroactive snapshot of every imported launcher module.

## Arm artifacts and multi-turn cases

`prepare` writes `guidance/` outside the test repository. `static/AGENTS.md` contains the preamble and both complete skill bodies without frontmatter; `l0-l2` and `default` use the same content. Standalone skills retain the task loop. `nudge` contains one sentence. No comparison arm enables L3 or L4. The frozen schedule is six cases × five arms × one repeat, randomized within each case using seed `20261105`.

`continue-task` is an additional model-free fixture, outside that frozen schedule and the approved mandatory smoke list. Contract-2 independent-task prompts now explicitly request main. Future results must identify their contract and prompt revision; the original passes do not establish compliance with those revised prompts.

Comparison options set `preparedState=true`: the runner snapshots every arm before each prompt and records preparation time separately. Default smoke uses normal prompt preparation with `preparedState=false`. Reset-boundary equalization still needs actual-client lifecycle validation before the pilot.

`multi-turn-external` resumes one conversation for three prompts. Before turn 2 the runner records an unchanged boundary. Before turn 3 it writes `external user work\n`, names the change `external user draft`, creates `user-wip` and replaces the protected baseline. Native resume emits SessionStart again; it is not evidence of unchanged-turn deduplication in a continuously running native client.

## Observations and grading

```bash
python3 evals/clients/finalize.py /absolute/existing/run codex
python3 evals/clients/export.py /absolute/stopped/campaign /absolute/new/export
```

Finalization changes derived evidence and snapshots final repository state. Previous grades are retained as `evidence/grade-<hash>.json`. Export is read-only against the campaign and requires a new destination. Raw requests and tool records are retained separately from derived grades.

The normalizer was exercised against OpenCode 2.2.5, Codex 0.166.0 and Claude Code 2.1.312. It handles nested OpenCode tools, Claude PostToolUseFailure, Codex shell wrappers and item IDs reused after resume. `coverage.json` records command pairing, tracing inheritance and isolation. Missing or unfinished observations stay **unknown**, even when the repository looks correct. Lexical command annotations and inherited process markers do not certify aliases, arbitrary nested languages or deliberately scrubbed environments.

Trace2 records Git argv, directory, ancestry and exit status. Git subprocesses called by jj are excluded by ancestry. Client read-only metadata probes are distinguished from mutation; direct model-issued Git remains a guidance violation in jj repositories. Script mutations are detected even without an `import git` operation. Trace2 does not cover libgit2.

New runs record `grading_contract: 2` in `case.json`. Preservation and task placement are separate checks:

- Preservation checks protected trees, descriptions, parent change IDs and existing bookmark targets. A different workspace file view is allowed. `keep_workspace: true`, used by `branch-alone`, additionally requires the original working-copy change and user-file contents.
- `task.mode: new` fixes the requested base in the baseline and requires the completed task to be based on it. An existing change is reusable only when it was the original empty, childless working copy already on that base. This covers both independent and dependent new tasks.
- `task.mode: continue` fixes the target change and requires completion in that same change with its original parents. Both task modes reject changes outside the requested paths. Output and final-topology checks still apply.

During execution the launcher checks recorded protected changes and bookmarks. For contract 2, after each non-capture jj turn it snapshots with `jj-agent.step="eval turn validation"` before checking again. This detects unsnapshotted damage at the turn boundary without comparing a transient checkout file view. It does not guarantee immediate detection before the next snapshot. The final grader also snapshots; these evaluator operations are separate from runtime L3 and are not agent violations.

Runs without a version, including the stopped campaign, retain contract 1 and its current-workspace user-file rule. The interrupted run remains `unknown` with its original observed failures, and the stop ledger remains authoritative. Unsupported contract versions grade `unknown`. Arms without L1 are not penalized for missing state messages.

Outstanding acceptance includes actual workspace-switch/clear/in-turn-compaction delivery, remaining skill-body selection checks, Claude packaged-skill independence, the stopped smoke and three Git controls. The pilot remains gated. See [verification](../docs/VERIFICATION.md) for C1–C7.
