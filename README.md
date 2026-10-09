# jj-agent-plugins

Make coding agents (Claude Code and Codex) use [Jujutsu](https://jj-vcs.github.io/jj/) instead of git, **only in jj repos**. Everywhere else the plugin does nothing.

- **Skill:** a non-interactive jj workflow the agent follows for every version-control action.
- **Git guard:** in Claude Code, a `git` shim on the agent's `PATH` blocks git commands that change state and names the jj equivalent.
- **Snapshots and git-change reports:** each edit and command lands in `jj op log`. When git changes the repo anyway (from a script, or in Codex where the shim cannot be used), the agent is told what happened and which operation to restore.

## Install

Claude Code:

```bash
claude plugin marketplace add hyperthreading/jj-agent-plugins
claude plugin install jj-agent@yejun-jj
```

Codex:

```bash
codex plugin marketplace add hyperthreading/jj-agent-plugins
codex plugin add jj-agent@yejun-jj
```

Per project, for either agent, with [APM](https://microsoft.github.io/apm/):

```bash
apm install hyperthreading/jj-agent-plugins/plugins/jj-agent
```

Restart the agent session after installing. In Codex, trust the hooks with `/hooks`. Needs `jj` on `PATH`.

To use it in a repo, make the repo a jj repo. For an existing git repo:

```bash
jj git init
```

## Docs

- [plugins/jj-agent/README.md](plugins/jj-agent/README.md): what each part does, using it in an existing git repo, updating, and limits
- [docs/adr/0001-apm-portable-packaging.md](docs/adr/0001-apm-portable-packaging.md): design decisions (packaging, git guard, change detection)
- [BENCHMARK.md](BENCHMARK.md): hook latency and test environment
- `tests/`: `hooks-test.sh` (scenarios), `hooks-bench.sh` and `hooks-profile.sh` (latency)

## License

MIT
