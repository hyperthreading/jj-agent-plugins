# jj-skill

The `jj` and `jj-workflow` skills on their own, with no hooks. `jj` has the complete default task loop, command tables, conflict/push recipes and command fallback. `jj-workflow` covers mega merges, parallel work and branch-only testing.

Both files are identical to the skills in jj-agent and target jj 0.46. They tell the agent to read current state itself when no `jj-state` context is available. The task loop protects user edits, descriptions and changes that have children; it does not rely on an external preamble.

## What you give up compared with jj-agent

| jj-agent part | Without it |
|---|---|
| Preamble and prompt/reset state | The agent selects the skills from their descriptions and reads its own state. There is no automatic state update or reset delivery. |
| Optional Git shim (Claude Code) | Nothing blocks state-changing Git. |
| Optional per-tool snapshots | jj snapshots when jj commands run. Edits since the last snapshot are not in the operation log yet. |
| Optional Git-change report | No hook reports Git changes or names a recovery point. |

The skill mentions a "this is a jj repo" block message, a "jj-agent: during the last command ..." report, and step names on snapshots (`jj-agent.step=...`). Those come from jj-agent's hooks and never appear with this plugin alone. The task name the skill has the agent put on `@` (`jj describe -m` before working) works without them.

Install one of jj-skill and jj-agent, not both: jj-agent already contains both skills.

## Install

The plugin is in the `hyperthreading` marketplace: [hyperthreading/jj-agent-plugins](https://github.com/hyperthreading/jj-agent-plugins).

**Claude Code:**

```bash
claude plugin marketplace add hyperthreading/jj-agent-plugins
claude plugin install jj-skill@hyperthreading
```

**Codex:**

```bash
codex plugin marketplace add hyperthreading/jj-agent-plugins
codex plugin add jj-skill@hyperthreading
```

**Muse Code:**

```bash
muse plugins marketplace add hyperthreading hyperthreading/jj-agent-plugins
muse plugins install jj-skill@hyperthreading
```

**Per project with [APM](https://microsoft.github.io/apm/):**

```bash
apm install hyperthreading/jj-agent-plugins/plugins/jj-skill
```

With no hooks there is no target restriction: the skill goes to every target the project has (`.claude/skills/`, and `.agents/skills/` for Codex, Copilot and others).

Requirements: `jj` on `PATH`.

## Development

These are the canonical skill files. The task-loop section in `jj/SKILL.md` is generated from `shared/task-flow.md`; edit that source instead of the generated region. Run `bash scripts/sync-shared.sh` and `bash tests/skill-sync-test.sh` from the repo root. The version is kept in lockstep with jj-agent (see [jj-agent's Development section](../jj-agent/README.md#development)).
