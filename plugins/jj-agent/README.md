# jj-agent

Make coding agents use [Jujutsu](https://jj-vcs.github.io/jj/) instead of git, **only in jj repos**. Works with Claude Code (and its subagents), Codex and Muse Code.

The plugin is opt-in per repository: a directory with `.jj/` (from `jj git init` or `jj git clone`) opts in. Everywhere else it does nothing. A repo converted in the middle of a session is picked up without a restart, and a `git worktree` of a jj repo is automatically attached to the main jj repository when a hook first reaches it through its working directory or a tool file path. Working files stay in place. Git commits, jj metadata and operation history are shared with the main repository.

| Part | What it does |
|---|---|
| `skills/jj` | How to use jj without thinking much: a fixed task loop, an intent→command table, conflict and push recipes, and a `--help` fallback with a legacy→current command map. Verified against jj 0.46. |
| `scripts/shim/git` | Claude Code only. A `git` wrapper first on the Bash tool's `PATH`. Outside jj repos it hands everything straight to git. Inside a jj repo it lets through calls made by jj itself and read-only git (`rev-parse`, `ls-files`, ...). It blocks anything that changes state and prints the jj equivalent. It checks for `.jj` on every call, so it starts guarding as soon as a repo is converted. |
| `SessionStart` | Claude Code: puts the shim on `PATH` via `CLAUDE_ENV_FILE`. Both: if the session starts in a jj repo (or a git worktree of one), tells the agent so. |
| `PreToolUse` (Bash, Edit, Write) | Bash in jj repos only: records the latest operation and a copy of the git index (copy-on-write where possible). It does not snapshot: the previous tool call and the turn start already did. Never rewrites the command. In Muse Code it also holds one call after a git-change report (see below); elsewhere the file tools pass straight through. |
| `PostToolUse`, `PostToolUseFailure` (Bash) | In jj repos only: snapshots after each edit or command (Claude Code reports a command that exits non-zero as a failure, so both are hooked), so each step lands in `jj op log`, named by the step (see below). After a Bash command it reports git changes with the operation to restore (see below), including refs created by `git worktree add`. It initializes a raw worktree only when that worktree is actually touched. The first time the agent touches a jj repo in a session (it ran `jj git init`, or `cd`'d into one), it tells the agent once. |
| `UserPromptSubmit` | In jj repos only: snapshots (named `changes made between turns`), so what you changed between turns (in an editor or your own terminal) is recorded before the agent acts. Also catches a repo converted between turns or initializes the current Git worktree, and tells the agent once. |

Outside jj repos, each hook exits after a directory walk looking for `.jj`. No jj process runs and nothing is added to the agent's context.

## Automatic worktree initialization

This path needs Python 3 with POSIX `fcntl` (macOS/Linux), jj and Git. Without Python, raw worktrees stay unchanged and remain boundaries.

- Only the checkout reached through `cwd` or a tool's file path is initialized. Creating a worktree from the parent waits until first touch; unrelated worktrees are never swept.
- The worktree joins the **same jj repository and operation history** as the main checkout. Each workspace has its own `@`. This gives one owner to Git's `refs/jj/keep/*`; separate jj repositories over one Git store can otherwise garbage-collect each other's working-copy/history objects.
- A unique sibling directory is used to create an empty jj workspace at `root()` with full sparse patterns and `--no-colocate`. Only its newly created `.jj` metadata is renamed into the existing worktree. jj then imports the existing Git HEAD and snapshots the existing files. No user file is moved, copied, deleted or recreated; tracked deletions stay absent throughout. No Git registration is pruned.
- Staged changes, sparse/skip-worktree entries, an unborn HEAD, a mismatched registration or an unwritable parent directory postpone initialization. These refusals are cached per session: unchanged state gets a metadata-only check with no Git/jj subprocesses or repeated notice. Index, HEAD/ref, sparse/config, registration or parent-directory changes trigger a recheck; the same refusal reason is not announced again just because metadata changed. Other initialization failures retain their diagnostic/retry behavior.
- A POSIX lock keyed by the Git admin path serializes initialization, including after helper-only termination because the jj child inherits the lock. Keep plugin data consistent across sessions. Pending/error records identify the worktree and temporary metadata; retries reuse them, and incomplete metadata is retained for inspection.
- Initialization notices appear once on completion. Muse's first-PreToolUse notice survives to the following tool result, or the next held call when needed. Its native relative `path` is resolved against hook `cwd` for file-path-only initialization and snapshot labels.
- **Recorded-path limitation (jj 0.46):** the workspace registry still names the unique temporary sibling, although the current workspace is at the original Git path. Use `jj -R <actual-path>` or commands inside that checkout; do not use `jj workspace root --name` or `jj workspace remove` to locate/remove an automatically attached worktree. Ordinary explicitly created jj workspaces are unaffected. The plugin does not edit jj's internal registry format.
- Harness cleanup uses the existing Git registration (`git worktree remove`). Clean worktrees need no force; dirty ones retain Git's normal discard protection. The next SessionStart in the shared repo forgets only plugin-created completed workspaces after both the checkout and its Git admin directory are gone. A remaining Git registration protects manually moved, unrepaired or temporarily unavailable checkouts; unrelated explicit workspaces are left alone. Shared operation history remains subject to jj's normal retention policy. Bookmark wanted work before removing a checkout.

The jj 0.46 behavior (relative repo pointer, colocation import of Git HEAD without checkout, and GC ownership) is pinned by regression tests and must be rechecked when upgrading jj. See [ADR 0005](../../docs/adr/0005-safe-worktree-adoption.md).

## Each snapshot names its step

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

Codex reads the same marketplace and plugin files and loads both the hooks and the `jj` skill. It does not trust plugin hooks automatically: review and trust them with `/hooks`. To update: `codex plugin marketplace upgrade hyperthreading`, then `codex plugin add jj-agent@hyperthreading` again.

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

It installs for whichever of `claude` and `codex` the project targets: hooks into `.claude/settings.json` and `.codex/hooks.json` with their scripts under `.claude/hooks/` and `.codex/hooks/`, and the skill into `.claude/skills/` and `.agents/skills/`. Commit these files to share the setup with a team, or ignore them. Use either the plugin or APM for a given agent, not both, or the hooks run twice.

**Try it in Claude Code without installing:**

```bash
git clone https://github.com/hyperthreading/jj-agent-plugins
claude --plugin-dir jj-agent-plugins/plugins/jj-agent
```

Requirements:
- `jj` on `PATH`.
- The hooks parse their input with bash builtins (no jq). They run under `/bin/bash` when it exists, otherwise the `bash` on `PATH`.
- Automatic Git worktree initialization additionally needs Python 3 with POSIX `fcntl` (macOS/Linux). Without it, worktrees remain unchanged and repo boundaries are still respected.

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
- You keep using git, your IDE and `gh` as before; only the agent's git is guarded. jj keeps git's HEAD detached at `@-`, so `git status` may show a detached HEAD. jj imports whatever you do with git at its next command.
- To go back to plain git, delete `.jj`. Commits you made only through jj and never put on a bookmark do not become git branches, so set a bookmark on any you want to keep first.

Without `.jj` (plain git repos and other directories) every hook exits silently, writes nothing, and the shim passes every git command straight through. The check walks up from the working directory but stops at a `.git` file. A submodule or a worktree of a plain Git repo is therefore a boundary, and the shim passes Git through there. A nested Git repo with a `.git` directory still falls under the enclosing jj repo unless it has its own `.jj`.

## Notes

- **Codex:** plugin hooks and project hooks run only after you trust them with `/hooks`; project hooks also need the project's `.codex/` layer to be trusted. APM writes repo-relative hook paths (`.codex/hooks/...`), so with an APM install start Codex from the repo root.
- **Several shims on PATH:** after a plugin update a resumed session can have the old and the new shim directory on `PATH`. Each shim skips every shim copy when looking for the real git.
- **Escape hatch for humans:** `JJ_SHIM_OFF=1 <command>` runs real git, for example for a release script that commits. The skill tells the agent not to use it.
- **The shim affects only Claude Code's Bash tool.** Your terminal is untouched.
- **What the shim cannot see:** git called by absolute path (`/usr/bin/git`), scripts that reset `PATH`, libgit2-based tools, and git MCP servers. The snapshots and the git-change report cover what slips through.
- **Conflict markers:** the skill's preflight runs `jj config set --repo ui.conflict-marker-style git`. This changes how conflicts look in that repo for humans too.
- **Latency:** a Bash command in a jj repo costs two jj processes: about 45 ms in a small repo and 90 ms at 30,000 files on macOS. The post-command snapshot grows with the number of files in the working copy. Turning on watchman (`fsmonitor.backend = "watchman"` in jj 0.46) made snapshots slower in our measurement, so it is not recommended here. Naming the step adds only bash string handling. Measure with `tests/hooks-bench.sh` and `tests/hooks-profile.sh`; recorded numbers and environment are in [BENCHMARK.md](../../BENCHMARK.md).

## Development

Versions are kept in lockstep in `apm.yml`, `.claude-plugin/plugin.json` and the root `apm.yml`, for both jj-agent and [jj-skill](../jj-skill/README.md). The root `.claude-plugin/marketplace.json` is generated. After changing either, run from the repo root:

```bash
apm pack --check-versions
```

`skills/jj/SKILL.md` is also shipped on its own in `plugins/jj-skill`. Copy it there after editing it, and check with `tests/skill-sync-test.sh`.
