# jj-skill

The `jj` skill from [jj-agent](../jj-agent/README.md) on its own, with no hooks. Use it when the agent follows the skill well enough that you do not need git blocked or every step snapshotted.

The skill is the same file as in jj-agent: a fixed task loop, an intent→command table, conflict and push recipes, and a `--help` fallback with a legacy→current command map. Verified against jj 0.46. It applies only where `jj root` succeeds; elsewhere the agent does not load it.

## What you give up compared with jj-agent

| jj-agent part | Without it |
|---|---|
| git shim (Claude Code) | Nothing blocks state-changing git. The agent avoids git only because the skill says so. |
| Snapshot after every edit and command | jj snapshots only when a jj command runs. Edits made since the last jj command are not in `jj op log` yet, so a git command that overwrites them (`git checkout -- f`, `git stash`, `git reset --hard`) loses them. |
| Git-change report | Nobody tells the agent that git changed the repo. |
| Session-start / first-touch notice | The agent is not told that a directory is a jj repo. It picks the skill from its description, which names `.jj/` and `jj root`. |

The skill mentions a "this is a jj repo" block message, a "jj-agent: during the last command ..." report, and step names on snapshots (`jj-agent.step=...`). Those come from jj-agent's hooks and never appear with this plugin alone. The task name the skill has the agent put on `@` (`jj describe -m` before working) works without them.

Install one of jj-skill and jj-agent, not both: jj-agent already contains the skill, and with both the agent sees it twice.

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

`skills/jj/SKILL.md` is a copy of `plugins/jj-agent/skills/jj/SKILL.md`. Edit one, copy it over the other, and check with `tests/skill-sync-test.sh`. The version is kept in lockstep with jj-agent (see [jj-agent's Development section](../jj-agent/README.md#development)).
