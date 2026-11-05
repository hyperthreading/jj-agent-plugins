# Shared guidance verification

2026-11-06. **Acceptance is incomplete; the model campaign is stopped.** The 2026-11-05 runtime passed actual installation/first-request checks and eight mandatory smoke runs. Claude's external-change run was interrupted by its version-1 workspace-content rule; three Git controls and the comparison pilot remain unexecuted. The intent-aware guidance and contract-2 grader have model-free verification only.

The historical campaign used shared runtime `npsksrqk` / `0d46dd937a3fdb4d3959ed8d6bcbcab233ac5e9f` and compass `trlyksxs` / `403f8994a5f3e6ea302c9463944c467368b555c7`. The shared follow-up is change `tnnzznlv`, developed in `/Users/jun/workspace/jj-agent-guidance-shared`; compass records the exact copied source commit in `SHARED_VERSION` and its own verification note. The original live plugin checkout was not the runtime under test. Shared packages remain unpublished at 0.4.0.

## Intent contract, 2026-11-06

[ADR 0006](adr/0006-intent-aware-task-placement.md) resolves the user's preservation clarification. Continue an existing task in its change; start independent work from its intended base; stack a new dependent task on its dependency. Preserve unrelated changes and bookmarks. Keeping the current workspace in place is a separate, explicit request.

New fixtures record `grading_contract: 2` and fixed task metadata. The launcher monitors recorded protected changes/bookmarks, then snapshots at each completed non-capture jj turn before checking unsnapshotted edits. Historical runs without a version retain contract 1. `continue-task` exercises continuation without adding a case to the frozen paid schedule. No actual-client result establishes the revised guidance's behavior yet.

## Model-free checks

```bash
bash scripts/isolated.sh bash scripts/check.sh
```

The 2026-11-06 shared run passed:

| Check | Result |
|---|---|
| Generated preamble/task flow and both skill distributions | Match |
| Shared state fixtures | 7 cases; bash and previously verified compass TS agree except the declared unnamed-merge spelling |
| Packaged guidance, defaults, independent L0/L1 and lifecycle | 13 tests |
| Grader | 21 tests, including independent/dependent work, continuation identity, empty-change reuse, explicit workspace preservation, bookmark loss and contract-1 compatibility |
| Client control | 29 tests: admission, crash accounting, protocol usage, real loopback mock exchanges, cleanup, preservation stop and normalization |
| Enabled safeguards, full/minimal PATH, Muse recovery | 104 checks |
| Changed evaluator Python files | Syntax checks passed |

Log: `/private/var/folders/lv/q99glyrj5cngjzkp005_4j1h0000gn/T/opencode/jj-task-intent.pr6CjK/shared-check.log`; SHA-256 `996d1ffdb990b2ca781a968d3a772f8e9fbab77d3fe60a2abbfc179015828f90`. It is a local log; the command above reproduces the checks. The generated L0 is 1,053 UTF-8 bytes, four lines and 182 whitespace-delimited words. Model-specific token counts are unmeasured.

The earlier compass typecheck, 70 tests, GUI build and 14 separately installed tarball tests remain the historical runtime baseline. Regenerated compass checks are recorded in the OpenCode verification note. The campaign's original 10-test grader result and pin comparison remain in [its evidence export](../evals/results/2026-11-05/README.md).

Whole-hook latency remains in [BENCHMARK.md](../BENCHMARK.md): at 30,000 files, edited-prompt p50/p95 was 132.17/137.92ms. Prompt/reset snapshots are retained to see external edits despite exceeding the 100ms target. The existing safeguard suite still reproduces its known detection false positive and mid-turn external-edit gap; passing it does not resolve those limitations.

## Actual-client evidence, 2026-11-05

Clients: OpenCode 2.2.5, Codex 0.166.0, Claude Code 2.1.312; jj 0.46.0, Bun 1.4.4, APM 0.35.0. OpenCode and Codex used GPT-6.1 Terra / medium; Claude used Sonnet 5.5 / medium. Final client HTTP requests were captured at the loopback proxy before upstream dispatch, in addition to OpenCode's hook-time context and registration inventory.

- Isolated local-marketplace installs for Codex and Claude, copied compass installation, initial L0/current L1 and both skill advertisements passed. OpenCode registered both canonical skill bodies and loaded only the expected non-builtin plugins.
- APM `pack --check-versions --offline`, local installation, and native Codex/Claude APM delivery captures passed. This replaces the earlier APM-style-only evidence.
- L0-off, L1-off and standalone-skill captures passed in all three clients. Codex's per-path `skills.config` disabled the packaged `jj` advertisement. Claude's `Skill(jj-agent:jj)` deny rule did not hide it; independent packaged-skill replacement remains unresolved.
- Native resume and external-state delivery have actual evidence. Workspace switching, clear and in-turn compaction remain unverified. A resumed process is not a substitute for same-process unchanged-turn deduplication.

| Mandatory smoke | OpenCode | Codex | Claude |
|---|---|---|---|
| `basic` | Pass | Pass | Pass |
| `dirty-wc` | Pass | Pass | Pass |
| `multi-turn-external` | Pass | Pass | Interrupted; contract-1 preservation condition failed |
| Git `control` | Not run | Not run | Not run |

These are one-off smoke results, not reliability estimates. The three initial paid basic attempts remain `unknown` because of launcher/environment or observation problems; raw first failures and earlier grades were retained. Total accounting includes those attempts: **12 paid attempts, 69 forwarded requests, $2.182575 API-equivalent usage, $0 pending reservations**. The approved ceilings were $30/90 minutes total and $1/3 minutes/30 requests per run. The stop condition, rather than the budget, ended execution.

## Preservation stop

On turn 3 Claude ran `jj new main -m "Add feature.txt"` before writing and committing the task file. The current workspace's `user.txt` consequently became `base\n` instead of the protected `external user work\n`. The `user-wip` change's tree, description, parent change IDs, bookmark and file content remain intact. The failing request included fresh L1 naming `external user draft`, `user-wip` and `M user.txt`.

The original prompt requested an unrelated task in its own change, so branching from main was appropriate. The earlier assistant interpretation that Claude should have continued on the draft was incorrect. The recorded failure came from contract 1's workspace-content rule; the protected change was preserved. A deterministic regression passes this branch-away behavior under contract 2 and retains the contract-1 failure. The interrupted run remains **unknown with observed failures**. The ledger's preservation stop remains authoritative; no further model calls or ledger reset are authorized by the old approval.

Post-stop review added terminal preservation checking, request-settlement waiting before ledger release, cleanup on error, portable host-home paths and more complete provenance hashes for future runs. These refinements passed model-free checks; the stopped campaign did not execute this final launcher revision.

## C1–C7

| Criterion | Evidence now available | Remaining requirement |
|---|---|---|
| C1 Default installation | Native marketplace/APM and compass initial L0/L1/L2 delivery; OpenCode canonical body registration | Loaded skill-body/selection checks not completed for both skills on every installation path |
| C2 Independent configuration | Default L3/L4-off, L0/L1-off and standalone captures; adapter and hook combinations; Codex `jj` opt-out | Claude packaged-skill independence; remaining actual-client per-skill combinations |
| C3 State/lifecycle | Shared fixtures, adapter/hook cases, initial delivery, native resume, external-edit delivery | Same-process unchanged-turn deduplication, workspace switch, clear and in-turn compaction |
| C4 Standalone/source consistency | Complete task flow, both standalone advertisements, generated-source checks and fixed compass pin | Final selected/loaded standalone bodies on every native path |
| C5 Behavior/preservation | Eight historical smoke passes; preserved stop evidence; intent contract decided in ADR 0006 | Obtain approval and validate revised guidance/contract 2, including the stopped case and all three Git controls |
| C6 Grader | 21 deterministic tests plus historical actual-client normalization; unknown stays distinct from observed failure | No known fixture failure; contract-2 actual-client results remain unobserved |
| C7 Regression/reproduction | Shared suites, 29 control tests, historical isolation captures, installation/configuration/usage evidence and hashes | Intent-aware guidance and post-stop launcher changes have model-free verification only; complete client acceptance remains open |

The comparative conclusion is **inconclusive: the pilot did not start**. No adoption or release decision follows from the smoke passes. [ADR 0005](adr/0005-budgeted-guidance-validation.md) records the stop; [ADR 0006](adr/0006-intent-aware-task-placement.md) resolves the intent contract while retaining that stop.
