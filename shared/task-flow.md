Default flow, one change per task: use `jj new -m "<task>"` if @ has children or contains other work; otherwise name an empty @ with `jj describe -m "<task>"`; finish with `jj commit -m "<message>"`.

1. Read `jj st` and `jj log` before editing. If `@-` is a merge, load `jj-workflow` before choosing this default loop; a mega merge keeps its working copy open across tasks.
2. Unless the user asked to change that change, do not edit or describe an `@` that has children. Start a new change so the existing change and its descendants keep their content.
3. Otherwise choose by whether `@` is empty, not whether it already has a description. Preserve another task's edits and description by starting on top. Name your change before editing so its snapshots belong to the task.
4. After `jj commit`, the finished change is `@-`. The empty, undescribed `@` above it is normal. Repeat the loop for the next task.
5. A small fix to the task just finished can be made in the empty `@` and folded into your own previous change with `jj squash -u`. Do not fold unrelated user edits into it.

For parallel tasks, several branches, or a branch-only check, load `jj-workflow` to choose the workspace and change layout. In a workspace converted from a git worktree (announced with `bookmark '<name>' at @-`), advance that bookmark after committing with `jj bookmark set <name> -r @-` so tools inspecting the worktree branch see the finished change.
