# jj-agent

Make Claude Code (and its subagents) use [Jujutsu](https://jj-vcs.github.io/jj/) instead of git, **only in jj repos**.

The plugin is opt-in per repository: a directory with `.jj/` (from `jj git init` or `jj git clone`) opts in. Everywhere else it does nothing. A repo converted in the middle of a session is picked up without a restart.

| Part | What it does |
|---|---|
| `skills/jj` | How to use jj without thinking much: a fixed task loop, an intent→command table, conflict and push recipes, and a `--help` fallback with a legacy→current command map. Verified against jj 0.46. |
| `shim/git` | A `git` wrapper first on the Bash tool's `PATH`. Outside jj repos it hands everything straight to git. Inside a jj repo it lets through calls made by jj itself and read-only git (`rev-parse`, `ls-files`, ...). It blocks anything that changes state and prints the jj equivalent. It checks for `.jj` on every call, so it starts guarding as soon as a repo is converted. |
| `SessionStart` | Puts the shim on `PATH` via `CLAUDE_ENV_FILE`. If the session starts in a jj repo, it tells Claude so. |
| `PostToolUse` | In jj repos only: runs `jj util snapshot` after each Edit/Write/Bash, so each step lands in `jj op log`. The first time Claude touches a jj repo in a session (it ran `jj git init`, or `cd`'d into one), it tells Claude once. |
| `UserPromptSubmit` | Catches a repo converted between turns, e.g. in your own terminal, and tells Claude once. |

Outside jj repos, each hook exits after a directory walk looking for `.jj`. No jj process runs and nothing is added to Claude's context.

## Install

```bash
claude plugin marketplace add /path/to/jj-agent-marketplace
claude plugin install jj-agent@yejun-jj
```

To try it without installing: `claude --plugin-dir /path/to/jj-agent-marketplace/plugins/jj-agent`.

Requirements:
- `jj` on `PATH`.
- `jq` is optional. The hooks fall back to grep/sed for reading hook input.

## Notes

- **Escape hatch for humans:** `JJ_SHIM_OFF=1 <command>` runs real git, for example for a release script that commits. The skill tells the agent not to use it.
- **The shim affects only Claude's Bash tool.** Your terminal is untouched.
- **What the shim cannot see:** git called by absolute path (`/usr/bin/git`), scripts that reset `PATH`, libgit2-based tools, and git MCP servers. That is why the snapshot hook exists: whatever slips through is still recoverable from `jj op log`.
- **Conflict markers:** the skill's preflight runs `jj config set --repo ui.conflict-marker-style git`. This changes how conflicts look in that repo for humans too.
- **Large repos:** if snapshots after every step feel slow, enable watchman (`core.fsmonitor = "watchman"`).
