# jj-agent-plugins

Make coding agents (Claude Code, Codex and Muse Code) use [Jujutsu](https://jj-vcs.github.io/jj/) instead of git, **only in jj repos**. Everywhere else the plugin does nothing.

- **Skill:** a non-interactive jj workflow the agent follows for every version-control action.
- **Git guard:** in Claude Code, a `git` shim on the agent's `PATH` blocks git commands that change state and names the jj equivalent.
- **Snapshots and git-change reports:** each edit and command lands in `jj op log`, named by the step that made it, under a change the agent describes with its task. When git changes the repo anyway (from a script, or in Codex and Muse Code where the shim cannot be used), the agent is told what happened and which operation to restore.

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

**Skill only:** if the agent follows the skill well enough without a git guard or snapshots, install `jj-skill` instead of `jj-agent` (same commands with `jj-skill@hyperthreading`, or `apm install hyperthreading/jj-agent-plugins/plugins/jj-skill`). It has no hooks, so there is nothing to trust or approve. See [plugins/jj-skill/README.md](plugins/jj-skill/README.md) for what it leaves out. Install one of the two, not both.

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
- `tests/`: `hooks-test.sh` (scenarios), `hooks-bench.sh` and `hooks-profile.sh` (latency), `skill-sync-test.sh` (the two skill copies match)

## License

MIT
