This project is a Jujutsu (jj) repository. Use jj for version control, including read-only checks: in a colocated repo git can report a detached HEAD and misleading unmerged paths, and mutating git commands fight jj's state. Always pass -m; never run a command that opens an editor or is interactive. Push only when the user asks.
The jj-state context, when present, shows the working copy (@) at the latest user message or context reset; run `jj st` or `jj log` for the current state.
{{task-flow}}
Use the jj skill for jj commands. Load the jj-workflow skill when @- is a merge (a mega merge), when work spans several branches at once, when tasks or agents run in parallel, or when a branch has to be checked on its own.
