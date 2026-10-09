# jj-agent

Make coding agents use [Jujutsu](https://jj-vcs.github.io/jj/) instead of git, **only in jj repos**. Works with Claude Code (and its subagents) and Codex.

The plugin is opt-in per repository: a directory with `.jj/` (from `jj git init` or `jj git clone`) opts in. Everywhere else it does nothing. A repo converted in the middle of a session is picked up without a restart.

| Part | What it does |
|---|---|
| `skills/jj` | How to use jj without thinking much: a fixed task loop, an intent→command table, conflict and push recipes, and a `--help` fallback with a legacy→current command map. Verified against jj 0.46. |
| `scripts/shim/git` | Claude Code only. A `git` wrapper first on the Bash tool's `PATH`. Outside jj repos it hands everything straight to git. Inside a jj repo it lets through calls made by jj itself and read-only git (`rev-parse`, `ls-files`, ...). It blocks anything that changes state and prints the jj equivalent. It checks for `.jj` on every call, so it starts guarding as soon as a repo is converted. |
| `SessionStart` | Claude Code: puts the shim on `PATH` via `CLAUDE_ENV_FILE`. Both: if the session starts in a jj repo, tells the agent so. |
| `PreToolUse` (Bash) | In jj repos only: runs `jj util snapshot` right before the command and records the operation id and the git index hash. Never blocks or rewrites the command. |
| `PostToolUse` | In jj repos only: runs `jj util snapshot` after each edit or command, so each step lands in `jj op log`. After a Bash command it reports git changes with the operation to restore (see below). The first time the agent touches a jj repo in a session (it ran `jj git init`, or `cd`'d into one), it tells the agent once. |
| `UserPromptSubmit` | Catches a repo converted between turns, e.g. in your own terminal, and tells the agent once. |

Outside jj repos, each hook exits after a directory walk looking for `.jj`. No jj process runs and nothing is added to the agent's context.

## Git changes are reported, not just blocked

Codex has no way for a hook to change `PATH` for later commands, so the shim cannot be used there. Instead, every Bash command in a jj repo runs between two snapshots, and the post hook tells the agent when git changed the repo:

- **git moved HEAD or refs** (`git commit`, `reset`, `checkout <branch>`, ...): jj records an `import git head`/`import git refs` operation.
- **git rewrote working-copy files** (`git checkout -- <path>`, `restore`, `stash`, `reset --hard`): the content of `.git/index` changed while no jj command ran. This also catches git called from scripts.
- **the command text runs a state-changing git subcommand and files changed.** This is a fallback for commands that also ran jj.

The report names the operation from just before the command, plus `jj op restore <op>` (whole repo) and `jj restore --from 'at_operation(<op>, @)' <paths>` (single files). In Claude Code this backs up the shim. See [ADR 0001](../../docs/adr/0001-apm-portable-packaging.md) for the design and its limits.

## Install

Claude Code, as a plugin:

```bash
claude plugin marketplace add /path/to/jj-agent-marketplace
claude plugin install jj-agent@yejun-jj
```

Claude Code or Codex, with [APM](https://microsoft.github.io/apm/) (installs for whichever of the two the project targets):

```bash
apm install /path/to/jj-agent-marketplace/plugins/jj-agent
```

To try it in Claude Code without installing: `claude --plugin-dir /path/to/jj-agent-marketplace/plugins/jj-agent`.

Requirements:
- `jj` on `PATH`.
- `jq` is optional. The hooks fall back to grep/sed for reading hook input.

## Notes

- **Codex:** project hooks run only after the project's `.codex/` layer is trusted and the hooks are reviewed with `/hooks`. APM writes repo-relative hook paths (`.codex/hooks/...`), so start Codex from the repo root.
- **Escape hatch for humans:** `JJ_SHIM_OFF=1 <command>` runs real git, for example for a release script that commits. The skill tells the agent not to use it.
- **The shim affects only Claude Code's Bash tool.** Your terminal is untouched.
- **What the shim cannot see:** git called by absolute path (`/usr/bin/git`), scripts that reset `PATH`, libgit2-based tools, and git MCP servers. The snapshots and the git-change report cover what slips through.
- **Conflict markers:** the skill's preflight runs `jj config set --repo ui.conflict-marker-style git`. This changes how conflicts look in that repo for humans too.
- **Large repos:** every Bash command now runs two snapshots. If that feels slow, enable watchman (`core.fsmonitor = "watchman"`).

## Development

Versions are kept in lockstep in `apm.yml`, `.claude-plugin/plugin.json` and the root `apm.yml`. The root `.claude-plugin/marketplace.json` is generated. After changing either, run from the repo root:

```bash
apm pack --check-versions
```
