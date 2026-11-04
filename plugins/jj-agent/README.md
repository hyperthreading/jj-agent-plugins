# jj-agent

Make coding agents use [Jujutsu](https://jj-vcs.github.io/jj/) instead of git, **only in jj repos**. Works with Claude Code (and its subagents), Codex and Muse Code.

The plugin activates in a directory with `.jj/` (from `jj git init` or `jj git clone`). A repo converted in the middle of a session is picked up without a restart. Git-worktree conversion requires a separate option.

| Part | What it does |
|---|---|
| `skills/jj` | How to use jj without thinking much: a fixed task loop, an intent→command table, conflict and push recipes, and a `--help` fallback with a legacy→current command map. Verified against jj 0.46. |
| `skills/jj-workflow` | Choose changes, mega merges and separate workspaces. It works without a supplied state context. |
| `SessionStart` | Sends the preamble and current state, including on resume, clear and compaction. Invalidates state deduplication. With guard enabled, puts the shim on Claude Code's `PATH` via `CLAUDE_ENV_FILE`. |
| `UserPromptSubmit` | Snapshots before reading current state. Sends changed state only, and the preamble on first entry into a jj repo. |
| `PreToolUse` (Bash, Edit, Write) | With detection enabled, records the latest operation and Git index before Bash; handles Muse's pending notices. Never rewrites commands. |
| `PostToolUse`, `PostToolUseFailure` (Bash) | Announces first entry into jj. Optional snapshots record each tool step; optional detection reports Git changes with a recovery point. Optional adoption converts new Git worktrees. |
| `scripts/shim/git` | Optional Claude Code guard. Blocks mutating Git inside jj; allows jj's own Git subprocesses and read-only Git used by scripts. The guidance tells the agent to use jj even for direct read-only checks. |

Outside jj repos, each hook exits after a directory walk looking for `.jj`. No jj process runs and nothing is added to the agent's context.

## Each snapshot names its step

Per-tool snapshots require `JJ_AGENT_SNAPSHOTS=1`. Prompt/reset snapshots prepare L1 and work independently of that option.

The skill has the agent describe `@` with the task before it starts working, so every snapshot of the work belongs to a described change. The hooks name each snapshot after the step that caused it: jj records a command's arguments with the operation it makes, and the hooks add `--config 'jj-agent.step=<step>'` to the snapshotting command. `jj op log` shows it on the `args:` line:

```
○  b4f85e018080 root@vm default@ 9 seconds ago, lasted 9 milliseconds
│  snapshot working copy
│  args: jj util snapshot --config 'jj-agent.step=Bash: Run unit tests'
○  9c24d485e1ab root@vm default@ 9 seconds ago, lasted 5 milliseconds
│  snapshot working copy
│  args: jj util snapshot --config 'jj-agent.step=Edit src/login.js'
○  347c2b1e8b6b root@vm default@ 9 seconds ago, lasted 5 milliseconds
│  describe commit 9e582e28e00759e173c28b5155abfafb4d6f8b3f
│  args: jj describe -m 'fix: login redirect loop'
```

For one change's steps, `jj evolog -r <id> --no-graph -T 'operation.description() ++ "  " ++ operation.attributes() ++ "\n"'`.

- **Shell command:** Claude Code's Bash tool description; without one (Codex, Muse Code), the first line of the command.
- **File tool:** the tool name and the path in the repo. A Codex patch: the files it touches.
- **Between turns:** `changes made between turns`.
- First line only, at most 100 bytes, cut at a character boundary (jj rejects an argument that is not valid UTF-8); `...` marks a cut. If jj still refuses it, the hook snapshots without the name.

No extra jj process runs. Asking Codex to prefix commands with a reason was tried and dropped: it changes how Codex applies its approval rules ([ADR 0004](../../docs/adr/0004-step-names-in-snapshots.md)).

## Git changes are reported, not just blocked

This section applies with `JJ_AGENT_DETECT=1`, which also enables per-tool snapshots.

Codex has no way for a hook to change `PATH` for later commands, so the shim cannot be used there. Instead, the post hook compares the repo after each Bash command with the state it started from, and tells the agent when git changed it:

- **git moved HEAD or refs** (`git commit`, `reset`, `checkout <branch>`, ...): jj records an `import git head`/`import git refs` operation.
- **git rewrote files** (`git checkout -- <path>`, `restore`, `stash`, `reset --hard`): the file's content changed during the command, and git filled in its index entry. jj writes index entries with an empty stat; git fills one in only when the file matches the index. That happens when git rewrites the file, and also when `git status` refreshes an unchanged file. A file that changed and was filled in was therefore written by git. This also catches git called from scripts, and the report lists the files.

The report names the command and the operation from just before it, plus `jj restore --from 'at_operation(<op>, @)' <paths>` (single files) and `jj op restore <op>` (whole repo). One known false alarm: within one command, a file is put back to its `@-` content without git (`jj restore`, `sed`) and git then reads it. The report says to ignore it in that case. One known gap: a file someone else edits while the agent is in the middle of a turn is not in the starting state, so git overwriting it is neither reported nor recoverable. It also works when `.git` is a `gitdir:` file (a git worktree, `--separate-git-dir`). In Claude Code this backs up the shim. See [ADR 0001](../../docs/adr/0001-apm-portable-packaging.md) for the design and its limits, and [ADR 0003](../../docs/adr/0003-detector-fixes.md) for later fixes.

## Install

The repo is a plugin marketplace (`hyperthreading`) that both Claude Code and Codex read: [hyperthreading/jj-agent-plugins](https://github.com/hyperthreading/jj-agent-plugins).

**Claude Code** (user scope, every repo):

```bash
claude plugin marketplace add hyperthreading/jj-agent-plugins
claude plugin install jj-agent@hyperthreading
```

Restart the session afterwards: hooks are read at session start (`/reload-plugins` does not pick up new hooks). To update: `claude plugin marketplace update hyperthreading`, then `claude plugin update jj-agent@hyperthreading`, then restart.

**Codex** (user scope, every repo):

```bash
codex plugin marketplace add hyperthreading/jj-agent-plugins
codex plugin add jj-agent@hyperthreading
```

Codex reads the same marketplace and plugin files and loads the hooks and both skills. It does not trust plugin hooks automatically: review and trust them with `/hooks`. To update: `codex plugin marketplace upgrade hyperthreading`, then `codex plugin add jj-agent@hyperthreading` again.

**Muse Code** (user scope):

```bash
muse plugins marketplace add hyperthreading hyperthreading/jj-agent-plugins
muse plugins install jj-agent@hyperthreading
muse plugins approve jj-agent
```

Muse loads the hooks only after `approve`. There is no shim (as in Codex). Muse adds hook context to the first developer message, ahead of the conversation, where the model misses it or takes it for something from before the session. So the git-change report goes into a tool result instead:
- after a command that succeeded, it comes back inside that command's result, after the original output;
- after a command that failed (or whose output is too big to repeat), the next Bash, Edit or Write call is held and the report is its result.

Either way the next state-changing call is held once, so a call the model queued together with the command cannot run before it has looked. A `jj` command right after a delivered report is let through. See [ADR 0002](../../docs/adr/0002-muse-code-support.md).

**Installed from `yejun-jj`?** The marketplace used to be called `yejun-jj`. Updating keeps the old name, so remove it and add it again (removing the marketplace also removes its plugins):

```bash
claude plugin marketplace remove yejun-jj
claude plugin marketplace add hyperthreading/jj-agent-plugins
claude plugin install jj-agent@hyperthreading

codex plugin remove jj-agent@yejun-jj
codex plugin marketplace remove yejun-jj
codex plugin marketplace add hyperthreading/jj-agent-plugins
codex plugin add jj-agent@hyperthreading
```

In Muse Code, add the marketplace again under the name `hyperthreading` and install from it. Use `jj-skill` in place of `jj-agent` if that is what you installed.

**Per project with [APM](https://microsoft.github.io/apm/)** (Claude Code and Codex, pinned in the project's `apm.lock.yaml`):

```bash
apm install hyperthreading/jj-agent-plugins/plugins/jj-agent
```

It installs for whichever of `claude` and `codex` the project targets: hooks into `.claude/settings.json` and `.codex/hooks.json` with their scripts under `.claude/hooks/` and `.codex/hooks/`, and the skills into `.claude/skills/` and `.agents/skills/`. Commit these files to share the setup with a team, or ignore them. Use either the plugin or APM for a given agent, not both, or the hooks run twice.

**Try it in Claude Code without installing:**

```bash
git clone https://github.com/hyperthreading/jj-agent-plugins
claude --plugin-dir jj-agent-plugins/plugins/jj-agent
```

Requirements:
- `jj` on `PATH`.
- Bash and standard shell utilities (`mktemp`, `head`, `cat`, `mkdir`, `rm`, `find`; optional safeguards also use Git/awk/cp). No jq or Python is needed by the installed hooks. They run under `/bin/bash` when it exists, otherwise the `bash` on `PATH`.

## Using it in an existing git repo

Turn the repo into a colocated jj repo; that is the only opt-in step:

```bash
cd /path/to/repo
jj git init
jj bookmark track main@origin   # for each remote branch you pull, if jj suggests it
```

- `.git` stays as it is and `.jj` is added next to it (git ignores it). Branches become bookmarks, the checked-out branch becomes the parent of the working-copy change `@`, and uncommitted changes carry over into `@`.
- With the plugin installed (Claude Code or Codex), there is nothing to install per repo. The repo is picked up without a restart: at the next prompt or tool call the agent is told it is now jj.
- With APM instead, run `apm install hyperthreading/jj-agent-plugins/plugins/jj-agent` in the repo (see Install).
- You keep using git, your IDE and `gh` as before. When enabled, the guard affects only the agent. jj keeps git's HEAD detached at `@-`, so `git status` may show a detached HEAD. jj imports whatever you do with git at its next command.
- To go back to plain git, delete `.jj`. Commits you made only through jj and never put on a bookmark do not become git branches, so set a bookmark on any you want to keep first.

Without `.jj` (plain git repos and other directories) every hook exits silently, writes nothing, and the shim passes every git command straight through. The check walks up from the working directory, so a git repo nested inside a jj working copy counts as part of that jj repo.

## Options and migration

Set environment variables before starting the client, or through its supported hook environment settings. Values are `1` (enabled) or `0` (disabled).

| Variable | Default | Effect |
|---|---|---|
| `JJ_AGENT_PREAMBLE` | `1` | Short jj rules and skill-selection guidance |
| `JJ_AGENT_STATE` | `1` | Prompt/reset state, including a preparatory snapshot; forced off for Muse |
| `JJ_AGENT_SNAPSHOTS` | `0` | Per-tool snapshots, separate from L1 preparation |
| `JJ_AGENT_GUARD` | `0` | Claude Code Git shim; does not enable snapshots or detection |
| `JJ_AGENT_DETECT` | `0` | Git-change detection; forces snapshots on for its recovery baseline |
| `JJ_AGENT_ADOPT_WORKTREES` | `0` | Convert Git worktrees of jj repos into colocated jj workspaces |

Both skills are packaged independently of these hook options. The clients' skill controls determine which packaged or external skills load; avoid duplicate names. OpenCode's distribution has separate `commandSkill` and `workflow` registration options.

Earlier versions enabled safeguards and worktree conversion automatically. To retain those behaviors:

```bash
export JJ_AGENT_SNAPSHOTS=1 JJ_AGENT_GUARD=1 JJ_AGENT_DETECT=1 JJ_AGENT_ADOPT_WORKTREES=1
claude  # or codex / muse; only Claude Code supports guard injection
```

Turning all safeguards off leaves preamble/state delivery working. For state-only delivery use `JJ_AGENT_PREAMBLE=0`; for preamble-only use `JJ_AGENT_STATE=0`.

The state renderer uses four read-only jj queries after snapshot preparation. It sends at most 15 changed paths, workspace and branch context, and conflict/divergence/mid-stack warnings. Failed snapshot preparation produces an error, not old state presented as current. `sessions/<id>.state` includes the workspace path, so moving between workspaces invalidates deduplication. A context reset sends both enabled layers again without waiting for another prompt.

Hook input/output paths are covered by deterministic tests. Actual client delivery after compaction and the three-client behavioral smoke remain to be verified with an agreed model-call budget; see [evaluation preparation](../../evals/README.md).

## Notes

- **Codex:** plugin hooks and project hooks run only after you trust them with `/hooks`; project hooks also need the project's `.codex/` layer to be trusted. APM writes repo-relative hook paths (`.codex/hooks/...`), so with an APM install start Codex from the repo root.
- **Several shims on PATH:** after a plugin update a resumed session can have the old and the new shim directory on `PATH`. Each shim skips every shim copy when looking for the real git.
- **Escape hatch for humans:** `JJ_SHIM_OFF=1 <command>` runs real git, for example for a release script that commits. The skill tells the agent not to use it.
- **The shim affects only Claude Code's Bash tool.** Your terminal is untouched.
- **What the shim cannot see:** git called by absolute path (`/usr/bin/git`), scripts that reset `PATH`, libgit2-based tools, and git MCP servers. The snapshots and the git-change report cover what slips through.
- **Conflict markers:** the skill's preflight runs `jj config set --repo ui.conflict-marker-style git`. This changes how conflicts look in that repo for humans too.
- **Latency:** the older enabled-detection path costs two jj processes per Bash call. The default now reads state on prompts/resets instead. Measure whole prompt hooks with `tests/guidance-bench.py`; enabled-safeguard measurements use `tests/hooks-bench.sh` and `tests/hooks-profile.sh`. Recorded numbers and environment are in [BENCHMARK.md](../../BENCHMARK.md).

## Development

Versions are kept in lockstep in `apm.yml`, `.claude-plugin/plugin.json` and the root `apm.yml`, for both jj-agent and [jj-skill](../jj-skill/README.md). The root `.claude-plugin/marketplace.json` is generated. After changing either, run from the repo root:

```bash
apm pack --check-versions
```

The skill sources are in `plugins/jj-skill/skills/`; the shared preamble and task loop are in `shared/`. Run `bash scripts/sync-shared.sh` from the repo root, then `bash tests/skill-sync-test.sh`. Packaged hooks read `scripts/shared/preamble.md`, never the source checkout's `shared/` directory.
