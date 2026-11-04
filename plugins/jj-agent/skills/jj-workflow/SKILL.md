---
name: jj-workflow
description: Organize work in a Jujutsu (jj) repository across changes, branches, and workspaces. Load when @- has several parents (a mega merge), when work spans several branches, when tasks or agents run in parallel, or when a branch must be tested alone. Check jj log if no jj-state context is available. Use the jj skill for command details and the default single-task loop.
---

# jj-workflow

Use jj for version control in a jj repository. Use `jj st` and `jj log` to check the current working copy before changing files. A `jj-state` context is a snapshot from the latest user message or context reset, not a live view.

## Choose the layout

- For one task on one line of work, use the default task loop in the `jj` skill.
- If `@-` has several parents, inspect the graph and description to see whether this is a working mega merge. Follow the mega merge procedure below when several active branches are being built together.
- If parallel tasks would edit the same files, or a branch must be tested alone, use separate workspaces.
- When one branch needs another's code, stack the dependent branch on it rather than leave the two side by side.

## Mega merge

Use a mega merge when several active branches need to build and run together, or when the user asks for it.

1. Set it up with `jj new <branch> <branch> ... -m "megamerge"`, then `jj new -m ""` for an empty working copy above it.
2. Keep editing in that `@` across tasks. Do not create a new working change per task or commit the combined edits.
3. Move each edit into its branch with `jj absorb <paths>` or `jj squash --into <branch> -u <paths>`. Specify your paths when others share the working copy. Finish each task with its edits routed and `@` empty.
4. If work belongs to no existing branch, create a parent of the merge with `jj new --no-edit -A <base> -B <merge> -m "<task>"`, then move the edits into it.
5. When the branches have landed or the user is done with the merge, first check that the merge and `@` are empty. Drop them with `jj abandon <merge> @`, then return to one line of work with `jj new <branch-or-trunk> -m "<task>"`.

The branches keep the work. Do not abandon a merge or working copy that still contains unrouted edits.

## Workspaces

Use `jj workspace add <path> -r <revision>` for another working copy of the same repository. Choose a workspace when:

- Parallel tasks would edit the same files and mix their changes in `@`.
- A branch must build or pass tests on its own. Passing on the mega merge is not evidence that it passes alone.
- A fix belongs on another base, such as trunk, and should not disturb the current task.

Use the branch revision, not the mega merge, for a branch-only check. Record which revision and directory were tested. Rewriting a shared ancestor can make another workspace stale; run `jj workspace update-stale` there before continuing and preserve its local edits.
