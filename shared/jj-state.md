# jj-state format

Read the workspace at each user prompt and context reset. Snapshot before reading so external edits are included. The state reader itself uses `--ignore-working-copy`; tool snapshots are a separate opt-in feature.

The first line is:

```text
Where the jj working copy was at the latest user message or context reset. It is not refreshed after every tool call; run `jj st` or `jj log` for the current state.
```

Then emit these lines, in order:

1. `Repository: <absolute workspace root> (jj).`, or `(jj, colocated with Git).` OpenCode adds its VCS backend sentence to this line.
2. `Workspace: <name>`, with `(of <names>)` when more than one workspace exists.
3. `@ (working copy): <change>`, file count, then at most 15 `  <status> <path>` lines. More files add `  ... and <count> more`.
4. One `@- (parent): <change>` for each parent.
5. If a parent is a merge, `Mega merge: @- (<id>) merges <branches>. Keep editing in @ and move edits into those branches; load the jj-workflow skill for how.`
6. Nearest bookmarks, breadth-first through at most 40 ancestor generations and 120 rows, stopping each walk at a bookmark and listing at most three. Prefer local bookmarks over remote bookmarks at each change.
7. `trunk(): <names>; @ is <ahead> ahead, <behind> behind`, omitted when trunk is the root commit. Counts beyond the read window use `+`; behind is capped at 100.
8. Warnings, ordered conflict, divergent, mid-stack. Mid-stack names the child changes and tells the agent to start a new change before editing.

A change has its eight-character change ID, first description line in double quotes or `(no description)`, bookmarks in brackets, and tags `(empty, conflict, divergent, immutable)` in that order when applicable. Tabs in descriptions become spaces. Ignore the synthetic `@git` bookmark.

If jj fails, emit the header, `Repository: <absolute workspace root>.`, at most six error lines, and a request to run `jj st`. A stale workspace instead points to `jj workspace update-stale`. Do not replace an error with a successful-looking empty state. Snapshot failure is a state failure even if the recorded state could still be read.

The bash reader names merged branches by a bookmark directly on the branch tip, otherwise its change ID. OpenCode may use the nearest ancestor bookmark instead. This is the only branch-name difference allowed by the fixtures.

## Fixtures

`fixtures/setup.sh <case> <new-directory>` builds `empty`, `dirty`, `mid-stack`, `mega`, `mega-unnamed`, `conflict`, or `no-trunk` using local jj operations. Both readers use these fixtures. `expected/*.txt` uses `<ROOT>` and change placeholders to avoid tying expectations to random IDs. `mega-unnamed` expects `<LEFT-TIP>` in bash's merge-branch line and `left` in OpenCode's; all other text must match.
