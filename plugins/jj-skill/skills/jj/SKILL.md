---
name: jj
description: Version control in Jujutsu (jj) repos. Use for ANY VCS action (status, diff, log, commit, amend, split, rebase, conflicts, undo, fetch, push, branches/bookmarks) when `jj root` succeeds or a .jj/ directory exists, including colocated .jj + .git repos. Use jj, never git, in these repos.
---

# jj (Jujutsu) for agents

Written against jj 0.46. Command names and flags change between releases. When one fails, follow **Fallback** below rather than guessing.

## Preflight (once per session)

```bash
jj root                                              # fails → not a jj repo, stop using this skill
jj --version
jj config set --repo ui.conflict-marker-style git    # conflict markers you already know how to read
```

## Hard rules

1. **No git in a jj repo.** Do not run git commands yourself, not even read-only ones. In a colocated repo git reports a detached HEAD, stray `.jjconflict-*` files and fake unmerged paths. `git commit/checkout/rebase/stash/reset` fight jj's state. Every git task has a jj equivalent in the tables below. Project scripts and tools that read git data are fine, such as build scripts calling `git rev-parse` or `gh pr create --head <bookmark>` after a push. If git is blocked with a "this is a jj repo" message, use the jj equivalent it lists. Never bypass the block (absolute path to git, editing PATH, env flags).
2. **Never open an editor or TUI.** The command will hang or fail.
   - Always pass a message: `describe -m`, `commit -m`, `split -m`, `squash -m` or `squash -u`.
   - Use `jj describe --stdin` for multi-line messages.
   - Never run: `diffedit`, `arrange`, `resolve` (except `resolve --list`), any `-i/--interactive`, `--editor`, `--tool`.
   - `jj split` without file paths is interactive. Always give paths.
3. **The working copy `@` is a commit.** Edits are recorded automatically. There is no staging area, no `add`, no `stash`.
4. **Refer to changes by change ID** (the short lowercase letters in `jj log`), not by commit hash. Change IDs survive rewrites.
5. **Rebases never stop on conflicts.** After any command that rewrites history (`rebase`, `squash`, `abandon`, `git fetch`, `restore`, `edit`), run the conflict check: `jj log -r 'conflicts()'`.
6. **Never pass `--ignore-immutable`.** If jj refuses to rewrite an immutable or pushed change, build on top with `jj new <id>`.
7. **Push only when the user asks.**

## Task loop (default workflow)

```bash
jj st                       # 1. Start: look at @, then name it after the task
jj describe -m "<task>"     #    @ is (empty): describe it
jj new -m "<task>"          #    @ has changes (an earlier task's, or not yours): start on top
# ... edit files ...        # 2. Work: edits go into @ automatically
jj commit -m "feat: ..."    # 3. Done: final message for @, and a fresh empty @ on top
```

- Describe before working, so every snapshot of the work is recorded under the task: `jj evolog` lists them.
- Choose by whether `@` is empty, not by whether it has a description. An empty `@` left by a task that edited nothing gets re-described; `jj new` on top of an empty `@` leaves an empty commit behind.
- The finished change is `@-`. An empty, undescribed `@` on top of it is normal.
- Several tasks in a row, or several logical steps in one task: repeat 1–3 for each.
- A small fix to the task just finished is not a new task: make it in the empty `@`, then `jj squash -u`.
- Parallel tasks share one working copy and mix their edits in `@`. Give each its own `jj workspace add <path>`. For a colocated workspace, use `jj workspace add --colocate <new-path>` (jj 0.46+). On first touch, jj-agent automatically initializes Git worktrees of jj repos with their own colocated jj metadata. Their Git commits/branches are shared, but their jj operation history is separate; advance the worktree branch after committing (`jj bookmark set <branch> -r @-`) to share finished work.

## Intent → command

| Intent | Command |
|---|---|
| Status | `jj st` |
| Recent history | `jj log` (more: `jj log -r '::@' -n 20`) |
| Diff of current change | `jj diff` (`--git` for unified patch, `--stat` for summary) |
| Diff / show a change | `jj diff -r <id>` / `jj show <id>` |
| File at a revision | `jj file show -r <id> <path>` |
| Blame | `jj file annotate <path>` |
| Set message of @ / other change | `jj describe -m "..."` / `jj describe <id> -m "..."` |
| Finish current change | `jj commit -m "..."` |
| Start new change on X | `jj new <id> -m "..."` |
| Amend previous change (`git commit --amend`) | `jj squash -u` (moves @ into @-, keeps @-'s message) |
| Move some files into an earlier change | `jj squash --into <id> -u <paths>` |
| Auto-route fixes to the changes that last touched those lines | `jj absorb` |
| Split change | `jj split -r <id> -m "first part" <paths>` (paths go to the first part) |
| Discard working-copy edits to a file | `jj restore <path>` |
| Drop a change (content is discarded; children re-parented) | `jj abandon <id>` |
| Move a change and its descendants | `jj rebase -s <id> -o <dest>` |
| Move only one change | `jj rebase -r <id> -o <dest>` |
| Move whole local branch onto trunk | `jj rebase -b @ -o 'trunk()'` |
| Cherry-pick | `jj duplicate <id> -o <dest>` |
| Revert a change | `jj revert -r <id> -B @` |
| Parallel checkout (`git worktree`) | `jj workspace add <path>` |

## Conflicts

```bash
jj log -r 'conflicts()'            # which changes are conflicted (marked ×)
jj new <conflicted-id>             # work on top of the oldest conflicted change
jj resolve --list                  # conflicted files
# edit each file: keep the correct content, delete ALL marker lines
jj st                              # should say the conflict is resolved
jj squash -u                       # fold the resolution into the conflicted change
jj log -r 'conflicts()'            # repeat until empty
```

Descendants of the fixed change are rebased automatically and often resolve themselves, so re-check before fixing the next one. If the markers contain `%%%%%%%` or `+++++++`, the preflight config was not applied. Those are diff-style markers: the `%%%%%%%` section is a diff to apply onto the `+++++++` side.

## Remote (colocated git repo)

```bash
jj git fetch
jj rebase -b @ -o 'trunk()'                # then run the conflict check
jj bookmark set <name> -r @-               # bookmark = git branch; @- is the finished change
jj git push -b <name> --dry-run            # check first
jj git push -b <name>
```

- New bookmarks push without extra flags.
- Quick push without naming: `jj git push -c @-`. This creates a `push-<id>` bookmark.
- Push refuses changes with an empty description. Fix it with `jj describe <id> -m`.
- Follow a remote branch: `jj bookmark track <name>@origin`.
- Move an existing bookmark: `jj bookmark move <name> --to <id>`. Note it takes `--to`, not `-r`.
- After the user updates a PR, use the same bookmark: `jj bookmark set <name> -r @-`, then push.

## Undo / recovery

```bash
jj op log -n 10                    # every operation, newest first
jj op show <op-id>                 # what an operation changed
jj op restore <op-id>              # return the whole repo to the state after <op-id>
```

- `jj undo` undoes the latest operation. Repeated calls walk further back, and `jj redo` re-applies.
- The latest operation may be an automatic "snapshot working copy" rather than your command. Read `jj op log` first and prefer `jj op restore <op-id>`.
- Restore only to undo your own operations from this session. Ask the user before restoring past anything you did not do.
- `jj evolog -r <id>` lists every recorded state of one change. With jj-agent's hooks, `jj op log` shows on each snapshot the step that made it (`args: ... --config 'jj-agent.step=...'`).
- **"jj-agent: during the last command ..., git ..."**: git changed the repo, possibly from inside a script you ran. If you put those files back yourself (e.g. `jj restore`), ignore it. The message names the operation from just before that command. Run `jj op show` on the operations after it to see what changed. If the change was not intended, restore single files with `jj restore --from 'at_operation(<op>, @)' <paths>`, or the whole repo with `jj op restore <op>`; the latter also drops everything else that command did. Then redo the step with jj.

## Fallback

When a command fails with `unrecognized subcommand`, `unexpected argument`, or a deprecation warning:

1. Run `jj <command> --help` (or `jj help -k revsets|templates|bookmarks|config`). Adapt to what it says and retry once.
2. Check the legacy table below. Model memory often has old names.
3. Still failing: stop and report the exact error. **Never switch to git as a workaround.**

| Old / remembered | Current |
|---|---|
| `jj branch ...` | `jj bookmark ...` |
| `jj checkout X` | `jj new X` |
| `jj move` | `jj squash --from X --into Y` |
| `jj obslog` | `jj evolog` |
| `jj rebase -d X` | `jj rebase -o X` (`-d` still works as an alias) |
| `jj undo <op-id>` | `jj op revert <op-id>` or `jj op restore <op-id>` |
| `jj bookmark move N -r X` | `jj bookmark move N --to X` |
| `jj git push --allow-new` | not needed (flag removed) |
| `jj git init --colocate` | `jj git init` (colocates by default) |
| `jj squash` / `split` with no `-m`/`-u`/paths | add them, or it opens an editor |

## Misreadings to avoid

- `jj abandon` discards the change's content. It does not move it into the parent. To keep the content, use `jj squash`.
- After `jj commit` or `jj new`, `@` is empty, so "push @" pushes nothing useful. The finished work is `@-`.
- `trunk()` resolves to `main`/`master` on the remote. With no remote it resolves to `root()`.
