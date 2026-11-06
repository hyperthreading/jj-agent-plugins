# jj-agent-plugins

Make coding agents (Claude Code, Codex and Muse Code) use [Jujutsu](https://jj-vcs.github.io/jj/) instead of git, **only in jj repos**. Everywhere else the plugin does nothing.

- The default installation supplies a short preamble, current `jj-state` at prompts/context resets, and two skills: `jj` for commands and `jj-workflow` for branches, mega merges and workspaces. Muse receives the preamble and skills; its state delivery remains disabled.
- Per-tool snapshots, the Claude Code git guard, Git-change detection and Git-worktree adoption are opt-in. See [options and migration](plugins/jj-agent/README.md#options-and-migration).
- OpenCode's `jj-compass` copies the same guidance from this repository. Each distribution includes its own files and works without this checkout.

## Install

Claude Code:

```bash
claude plugin marketplace add hyperthreading/jj-agent-plugins
claude plugin install jj-agent@hyperthreading
```

Codex:

```bash
codex plugin marketplace add hyperthreading/jj-agent-plugins
codex plugin add jj-agent@hyperthreading
```

Muse Code:

```bash
muse plugins marketplace add hyperthreading hyperthreading/jj-agent-plugins
muse plugins install jj-agent@hyperthreading
muse plugins approve jj-agent
```

Per project, for Claude Code or Codex, with [APM](https://microsoft.github.io/apm/):

```bash
apm install hyperthreading/jj-agent-plugins/plugins/jj-agent
```

Restart the agent session after installing. In Codex, trust the hooks with `/hooks`; in Muse Code, `approve` does that. Needs `jj` on `PATH`.

Installed from the old `yejun-jj` marketplace? See [moving to `hyperthreading`](plugins/jj-agent/README.md#install).

**Skills only:** install `jj-skill` instead of `jj-agent` for the two complete skills without prompt hooks (same commands with `jj-skill@hyperthreading`, or `apm install hyperthreading/jj-agent-plugins/plugins/jj-skill`). The default task workflow remains in the `jj` skill. See [plugins/jj-skill/README.md](plugins/jj-skill/README.md). Install one of the two, not both.

To use it in a repo, make the repo a jj repo. For an existing git repo:

```bash
jj git init
```

## Docs

- [docs/DESIGN.md](docs/DESIGN.md): the whole design in one page (components, per-agent behavior, detection, Muse delivery, state, what was ruled out)
- [plugins/jj-agent/README.md](plugins/jj-agent/README.md): what each part does, using it in an existing git repo, updating, and limits
- [plugins/jj-skill/README.md](plugins/jj-skill/README.md): the skill alone, without hooks, and what that gives up
- [docs/adr/0001-apm-portable-packaging.md](docs/adr/0001-apm-portable-packaging.md): design decisions (packaging, git guard, change detection)
- [docs/adr/0002-muse-code-support.md](docs/adr/0002-muse-code-support.md): Muse Code support
- [docs/adr/0003-detector-fixes.md](docs/adr/0003-detector-fixes.md): git-change detection fixes (gitdir files, long operation logs)
- [docs/adr/0004-step-names-in-snapshots.md](docs/adr/0004-step-names-in-snapshots.md): task and step names in snapshots, and the Codex approval experiment
- [BENCHMARK.md](BENCHMARK.md): hook latency and test environment
- [shared/jj-state.md](shared/jj-state.md): shared state format and fixtures
- [evals/README.md](evals/README.md): model-free case preparation, grading and the budgeted validation handoff
- [docs/VERIFICATION.md](docs/VERIFICATION.md): measured candidate results and remaining client checks
- `tests/`: `guidance-test.py` (defaults, packaged hooks and lifecycle), `state-test.py` (shared fixtures), `hooks-test.sh` (opt-in regressions), `guidance-bench.py` (whole prompt hooks), `skill-sync-test.sh` (generated distributions)

## Shared source

Edit `shared/preamble.md`, `shared/task-flow.md` and `plugins/jj-skill/skills/`, then run `bash scripts/sync-shared.sh`. The task loop between generation markers in `jj/SKILL.md` comes from `shared/task-flow.md`. `bash tests/skill-sync-test.sh` rejects drift in either plugin or the hook's packaged preamble. OpenCode's `jj-compass/scripts/sync-shared.sh <this-checkout>` copies these files, the state specification and fixtures, and records the source revision.

For a skill-only client that also needs an always-present rule, copy the generated `plugins/jj-agent/scripts/shared/preamble.md` into its project instructions. Claude Code, Codex and OpenCode default installations deliver it automatically; they do not need this manual step.

## License

MIT
