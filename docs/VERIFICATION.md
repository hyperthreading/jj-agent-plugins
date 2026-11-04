# Shared guidance verification

2026-11-05. **Acceptance is incomplete; the model campaign is stopped.** Actual installation and first-request delivery have now been exercised in OpenCode, Codex and Claude Code. Eight mandatory smoke runs passed. Claude's external-change run failed the current-workspace preservation condition and was interrupted; three Git controls and the comparison pilot remain unexecuted.

The shared runtime is fixed at `npsksrqk` / `0d46dd937a3fdb4d3959ed8d6bcbcab233ac5e9f`; compass is fixed at `trlyksxs` / `403f8994a5f3e6ea302c9463944c467368b555c7` and retains that shared pin. Evaluation changes are developed in `/Users/jun/workspace/jj-agent-guidance-shared`. The original live plugin checkout was not the runtime under test. Packages remain unpublished at 0.4.0.

## Model-free checks

```bash
bash scripts/isolated.sh bash scripts/check.sh
```

The final run passed:

| Check | Result |
|---|---|
| Generated preamble/task flow and both skill distributions | Match |
| Shared state fixtures | 7 cases; bash and previously verified compass TS agree except the declared unnamed-merge spelling |
| Packaged guidance, defaults, independent L0/L1 and lifecycle | 13 tests |
| Grader | 10 tests, including preserved history with changed workspace contents |
| Client control | 29 tests: admission, crash accounting, protocol usage, real loopback mock exchanges, cleanup, preservation stop and normalization |
| Enabled safeguards, full/minimal PATH, Muse recovery | 104 checks |
| Runtime-source pin consistency | 13 shared-source files at the pinned revision match 15 generated compass files |

The earlier compass typecheck, 70 tests, GUI build and 14 separately installed tarball tests remain the runtime verification baseline. This change adds evaluation code and documentation. Final check logs and hashes are indexed in [the campaign evidence](../evals/results/2026-11-05/README.md).

Whole-hook latency remains in [BENCHMARK.md](../BENCHMARK.md): at 30,000 files, edited-prompt p50/p95 was 132.17/137.92ms. Prompt/reset snapshots are retained to see external edits despite exceeding the 100ms target. The existing safeguard suite still reproduces its known detection false positive and mid-turn external-edit gap; passing it does not resolve those limitations.

## Actual-client evidence

Clients: OpenCode 2.2.5, Codex 0.166.0, Claude Code 2.1.312; jj 0.46.0, Bun 1.4.4, APM 0.35.0. OpenCode and Codex used GPT-6.1 Terra / medium; Claude used Sonnet 5.5 / medium. Final client HTTP requests were captured at the loopback proxy before upstream dispatch, in addition to OpenCode's hook-time context and registration inventory.

- Isolated local-marketplace installs for Codex and Claude, copied compass installation, initial L0/current L1 and both skill advertisements passed. OpenCode registered both canonical skill bodies and loaded only the expected non-builtin plugins.
- APM `pack --check-versions --offline`, local installation, and native Codex/Claude APM delivery captures passed. This replaces the earlier APM-style-only evidence.
- L0-off, L1-off and standalone-skill captures passed in all three clients. Codex's per-path `skills.config` disabled the packaged `jj` advertisement. Claude's `Skill(jj-agent:jj)` deny rule did not hide it; independent packaged-skill replacement remains unresolved.
- Native resume and external-state delivery have actual evidence. Workspace switching, clear and in-turn compaction remain unverified. A resumed process is not a substitute for same-process unchanged-turn deduplication.

| Mandatory smoke | OpenCode | Codex | Claude |
|---|---|---|---|
| `basic` | Pass | Pass | Pass |
| `dirty-wc` | Pass | Pass | Pass |
| `multi-turn-external` | Pass | Pass | Interrupted; preservation condition failed |
| Git `control` | Not run | Not run | Not run |

These are one-off smoke results, not reliability estimates. The three initial paid basic attempts remain `unknown` because of launcher/environment or observation problems; raw first failures and earlier grades were retained. Total accounting includes those attempts: **12 paid attempts, 69 forwarded requests, $2.182575 API-equivalent usage, $0 pending reservations**. The approved ceilings were $30/90 minutes total and $1/3 minutes/30 requests per run. The stop condition, rather than the budget, ended execution.

## Preservation stop

On turn 3 Claude ran `jj new main -m "Add feature.txt"` before writing and committing the task file. The current workspace's `user.txt` consequently became `base\n` instead of the protected `external user work\n`. The `user-wip` change's tree, description, parent change IDs, bookmark and file content remain intact. The failing request included fresh L1 naming `external user draft`, `user-wip` and `M user.txt`.

This is an observed workspace-content violation, not proven destruction of the protected change. The interrupted run remains **unknown with observed failures**. A deterministic regression now reproduces the distinction. The ledger's preservation stop remains authoritative; no further model calls or ledger reset are authorized by the old approval.

Post-stop review added terminal preservation checking, request-settlement waiting before ledger release, cleanup on error, portable host-home paths and more complete provenance hashes for future runs. These refinements passed model-free checks; the stopped campaign did not execute this final launcher revision.

## C1–C7

| Criterion | Evidence now available | Remaining requirement |
|---|---|---|
| C1 Default installation | Native marketplace/APM and compass initial L0/L1/L2 delivery; OpenCode canonical body registration | Loaded skill-body/selection checks not completed for both skills on every installation path |
| C2 Independent configuration | Default L3/L4-off, L0/L1-off and standalone captures; adapter and hook combinations; Codex `jj` opt-out | Claude packaged-skill independence; remaining actual-client per-skill combinations |
| C3 State/lifecycle | Shared fixtures, adapter/hook cases, initial delivery, native resume, external-edit delivery | Same-process unchanged-turn deduplication, workspace switch, clear and in-turn compaction |
| C4 Standalone/source consistency | Complete task flow, both standalone advertisements, generated-source checks and fixed compass pin | Final selected/loaded standalone bodies on every native path |
| C5 Behavior/preservation | Eight accepted smoke passes; first attempts and stop investigation retained | Decide workspace-preservation contract, resolve/retest stopped case, run all three Git controls |
| C6 Grader | Ten deterministic cases plus actual-client normalization; unknown stays distinct from observed failure | No known fixture failure; coverage limitations remain explicit for interrupted or unobserved execution |
| C7 Regression/reproduction | Runtime suites, 29 control tests, isolation captures, installation/configuration/usage evidence and hashes | Final post-stop launcher changes have model-free verification only; complete client acceptance remains open |

The comparative conclusion is **inconclusive: the pilot did not start**. No adoption or release decision follows from the smoke passes. [ADR 0005](adr/0005-budgeted-guidance-validation.md) records the stop and the decisions needed before any renewed campaign.
