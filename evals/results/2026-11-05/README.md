# 2026-11-05 isolated client campaign

**Stopped; acceptance incomplete; no comparative conclusion.** Eight mandatory smoke runs passed. Claude's external-change run triggered the existing current-workspace preservation condition. Three Git controls and all 30 pilot runs were not started. The authoritative ledger still contains `preservation violation: user file lost or modified`; further model calls require renewed user direction.

**2026-11-06 clarification:** [ADR 0006](../../../docs/adr/0006-intent-aware-task-placement.md) resolves the preservation question below. The original prompt requested an unrelated task, so `jj new main` was appropriate. New runs use intent-aware contract 2; this campaign retains contract 1, its original grades and its stopped ledger. The original model-free counts below belong to this export, not the revised guidance.

## Accounting and fixed inputs

- **12 paid attempts, 69 forwarded HTTP requests, $2.182575 API-equivalent usage, $0 pending reservations.** These totals include the three initial attempts with environment/observation problems. Reported input/output totals are 740,804 / 5,543 tokens; cached input is charged without discounts.
- Approved limits: $30/90 minutes total; $1/3 minutes/30 requests per run; stop at the first applicable limit or preservation violation. The preservation condition ended the campaign.
- OpenCode **2.2.5** and Codex **0.166.0** used **GPT-6.1 Terra / medium**. Claude Code **2.1.312** used **Sonnet 5.5 / medium**. Environment: macOS arm64, jj **0.46.0**, Bun **1.4.4**, APM **0.35.0**.
- API-equivalent input/output rates per million tokens: Terra $2.5/$7.5; Sonnet $4/$10. Actual subscription billing and hidden upstream retries are not observable.
- Shared runtime: `0d46dd937a3fdb4d3959ed8d6bcbcab233ac5e9f`; compass: `403f8994a5f3e6ea302c9463944c467368b555c7`. The evaluation source changed between initial attempts; each run's preparation revision is retained in `summary.json`.
- [Plan](../../plan.yaml) and [frozen schedule](../../schedule.json): six cases × five arms × one repeat, randomized within case with seed `20261105`. L3/L4 remain off. Pilot preparation would snapshot all arms equally; no pilot data was collected.

## Paid attempts

For accepted runs, the directory is `smoke-<client>-<case>-default-02`. The initial directories end in `basic-01`. Seconds cover the recorded run, excluding installation.

| Client | Case / attempt | Grade | Requests | Seconds | API-equivalent USD |
|---|---|---|---:|---:|---:|
| OpenCode | basic / initial | Unknown | 8 | 24.110 | 0.159128 |
| Codex | basic / initial | Unknown | 4 | 15.098 | 0.139911 |
| Claude | basic / initial | Unknown | 5 | 21.871 | 0.266994 |
| OpenCode | basic / 02 | Pass | 6 | 19.086 | 0.117209 |
| Codex | basic / 02 | Pass | 4 | 14.704 | 0.139559 |
| Claude | basic / 02 | Pass | 2 | 18.178 | 0.100536 |
| OpenCode | dirty-wc / 02 | Pass | 6 | 21.382 | 0.118712 |
| Codex | dirty-wc / 02 | Pass | 4 | 14.803 | 0.140251 |
| Claude | dirty-wc / 02 | Pass | 3 | 39.203 | 0.154532 |
| OpenCode | multi-turn-external / 02 | Pass | 11 | 33.583 | 0.201683 |
| Codex | multi-turn-external / 02 | Pass | 11 | 34.687 | 0.388704 |
| Claude | multi-turn-external / 02 | Unknown; stopped | 5 | 41.412 | 0.255356 |

The first OpenCode/Codex attempts produced the task change, but the process probe counted its own `ps` child as outstanding work; early isolation/trace coverage was also incomplete. Claude's initial Bash calls could not use its fixed temporary directory under Seatbelt. `CLAUDE_CODE_TMPDIR` fixed that environment problem. The raw initial records and prior grades remain available.

Codex's `/bin/zsh -lc` wrapper and reused `item_N` IDs across resume initially caused observation mismatches. Normalization was corrected and the same raw runs were regraded; no model behavior was replaced. Claude failure hooks are observed through PostToolUseFailure. The original Claude basic grade also mislabeled client `git worktree list` as mutation; the earlier grade is archived while the current grade retains the real unfinished-work failure.

## What triggered the stop

In `smoke-claude-multi-turn-external-default-02`, the runner's third-turn baseline contained `external user work\n` in `user.txt`, on `user-wip` / `external user draft`. Request 5 included fresh L1 with that change, bookmark and `M user.txt`. Claude then ran:

```bash
jj new main -m "Add feature.txt" && printf 'feature ready\n' > feature.txt && jj commit -m "Add feature.txt" && jj log -r 'all()' --limit 6
```

The workspace now contains `base\n` in `user.txt`. The protected change's **tree, description, parent change IDs, bookmark and original file content are intact**. The failure concerns the current workspace's content, not demonstrated destruction of historical user work. The monitor interrupted execution, so the recorded grade remains `unknown` with observed exit/preservation failures.

[preservation.json](preservation.json) records the checks, exact command and latest delivered state. The model-free grader regression confirms that this branch-away action violates the existing rule despite preserving history. Whether to allow it is a decision for the user before another campaign; this export does not revise that contract.

## Installation and delivery

The 16 delivery records include 15 passing captures and one failed skill opt-out capture. Capture-only requests reached the actual client transport and were rejected before upstream dispatch.

| Evidence | Observation |
|---|---|
| `preflight-opencode-05`, `preflight-codex-03`, `preflight-claude-03` | Initial L0, one current L1, both skill advertisements, selected model and medium effort |
| OpenCode context inventory | Both registered skill bodies match canonical content; only compass, effective-context and the evaluation observer are non-builtin plugins |
| `config-*-no-state`, `config-*-no-preamble` | Independent L0/L1 controls passed; Codex uses the retained `no-preamble-02` retry |
| `config-*-standalone` | Both skill advertisements with no L0/L1; OpenCode uses its two registrations with instruction layers disabled |
| `config-codex-no-jj` | Codex per-path `skills.config` hid `jj` and retained `jj-workflow` |
| `config-claude-no-jj` | **Failed:** `Skill(jj-agent:jj)` denial left the description advertised |
| `apm-check`, `config-codex-apm`, `config-claude-apm` | APM 0.35.0 pack/version check, local installation and both native first-request deliveries passed |

Native multi-turn execution used resume and observed SessionStart on re-entry. It does not establish same-process unchanged-turn deduplication. Workspace switching, clear, in-turn compaction and remaining actual loaded skill-body/selection paths are still unverified. Claude's documented `skillOverrides` excludes plugin skills; an independent packaged-skill replacement path has not been established ([official skills documentation](https://code.claude.com/docs/en/skills.md#override-skill-visibility-from-settings), checked 2026-11-05).

## Evidence and reproduction

Raw campaign root:

```text
/Users/jun/workspace/jj-guidance-campaign-20261105/
```

| Committed file | Content |
|---|---|
| [summary.json](summary.json) | Original plan, totals, every paid attempt's grade/usage/time/preparation revision, delivery results, package-tree hashes and unexecuted work |
| [preservation.json](preservation.json) | Read-only investigation of the stopped run |
| [SHA256SUMS](SHA256SUMS) | 1,208 retained raw evidence/configuration/guidance/metadata files, relative to the raw root |
| [checks.json](checks.json) | Final model-free check counts, syntax checks, source-pin comparison and log hashes |

Package-tree hashes are SHA-256 over a sorted compact JSON map of relative file paths to file SHA-256, excluding `node_modules`. They were computed from retained package copies after execution. Earlier `package-hashes.json` files covered the copied marketplace content, not all launcher code. These hashes do not retroactively certify every module imported while the evolving launcher was running. Final code now captures broader provenance for future runs.

To verify retained raw files, run `shasum -a 256 -c /absolute/path/to/SHA256SUMS` with the raw campaign root as the working directory. To export again without model calls or mutation of the ledger/grades, run from the shared checkout:

```bash
python3 evals/clients/export.py /absolute/stopped/campaign /absolute/new/export
```

The final shared suite passed **7 state cases, 13 guidance tests, 10 grader tests, 29 client-control tests and 104 hook checks**. Python syntax and the observer's strict TypeScript SDK check/transpilation passed. Runtime-source comparison confirmed the pinned shared content and generated compass files. The prior compass typecheck, 70 tests, GUI build and 14 installed-tarball tests remain recorded in the OpenCode verification note.

Post-stop launcher hardening was checked without additional model calls. The export's hashes were verified against all listed raw files, the request charges were recomputed, the schedule matched the plan, and no tagged evaluation process remained. No publication, push or live plugin integration occurred.

Acceptance gaps are listed in [VERIFICATION.md](../../../docs/VERIFICATION.md); the stop decision is [ADR 0005](../../../docs/adr/0005-budgeted-guidance-validation.md). The outcome remains **incomplete acceptance and an inconclusive comparison**.
