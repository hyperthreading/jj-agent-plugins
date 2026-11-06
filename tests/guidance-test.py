#!/usr/bin/env python3
"""Exercise installed hook files against real, isolated jj repositories. No model calls."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jj-guidance-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo with spaces"
        self.repo.mkdir()
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("JJ_AGENT_", "CLAUDE_", "CODEX_", "MUSE_"))
        }
        config = self.root / "jj.toml"
        config.write_text('user.name = "Test"\nuser.email = "test@example.invalid"\n')
        self.env.update(JJ_CONFIG=str(config), CLAUDE_PLUGIN_DATA=str(self.root / "data"))
        self.plugin = self.root / "installed-plugin"
        shutil.copytree(SOURCE / "plugins/jj-agent", self.plugin)
        self.scripts = self.plugin / "scripts"
        self.jj("git", "init")
        (self.repo / "user.txt").write_text("base\n")
        self.jj("commit", "-m", "base")

    def jj(self, *args, cwd=None):
        return subprocess.run(
            ["jj", "--no-pager", "--color=never", *args],
            cwd=cwd or self.repo, env=self.env, check=True, text=True, capture_output=True,
        ).stdout.strip()

    def hook(self, event, *, session="test", cwd=None, options=None, tool="Bash", command="true", error=False):
        script = {"SessionStart": "session-start", "UserPromptSubmit": "user-prompt", "PreToolUse": "pre-tool", "PostToolUse": "post-tool"}[event]
        payload = dict(session_id=session, cwd=str(cwd or self.repo), hook_event_name=event,
                       tool_name=tool, tool_use_id="call", tool_input=dict(command=command), source="compact")
        result = subprocess.run(
            ["/bin/bash", str(self.scripts / f"{script}.sh")], input=json.dumps(payload),
            env={**self.env, **(options or {})}, cwd=self.root, capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stderr, "")
        if not result.stdout:
            return ""
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], event)
        text = output.get("additionalContext", "")
        if not error:
            self.assertNotIn("jj failed:", text)
        return text

    def op(self):
        return self.jj("op", "log", "--ignore-working-copy", "--no-graph", "-n", "1", "-T", "id")

    def test_packaged_defaults_and_deduplication(self):
        env_file = self.root / "env"
        env_file.touch()
        text = self.hook("SessionStart", options={"CLAUDE_ENV_FILE": str(env_file)})
        self.assertIn("including read-only checks", text)
        self.assertIn("has children", text)
        self.assertIn('<context key="jj-state">', text)
        self.assertIn("Workspace: default", text)
        self.assertEqual(env_file.read_text(), "")
        self.assertEqual(self.hook("UserPromptSubmit"), "")
        (self.repo / "user.txt").write_text("user edit\n")
        text = self.hook("UserPromptSubmit")
        self.assertIn("M user.txt", text)
        self.assertNotIn("Default flow", text)
        self.assertEqual(self.hook("UserPromptSubmit"), "")
        self.assertEqual((self.repo / "user.txt").read_text(), "user edit\n")

    def test_context_reset_and_session_identity(self):
        self.hook("SessionStart")
        self.assertEqual(self.hook("UserPromptSubmit"), "")
        for session in ("test", "second"):
            text = self.hook("SessionStart", session=session)
            self.assertIn("Default flow", text)
            self.assertIn('<context key="jj-state">', text)
            self.assertEqual(self.hook("UserPromptSubmit", session=session), "")

    def test_workspace_switch_with_identical_change(self):
        self.hook("SessionStart")
        other = self.root / "other"
        self.jj("workspace", "add", "--name", "other", str(other), "-m", "other")
        text = self.hook("UserPromptSubmit", cwd=other)
        self.assertIn(f"Repository: {other}", text)
        self.assertIn("Workspace: other", text)
        self.assertIn(f"Repository: {self.repo}", self.hook("UserPromptSubmit"))

    def test_tool_snapshots_are_opt_in(self):
        self.hook("SessionStart")
        before = self.op()
        (self.repo / "agent.txt").write_text("change\n")
        self.assertEqual(self.hook("PreToolUse"), "")
        self.assertEqual(self.hook("PostToolUse"), "")
        self.assertEqual(self.op(), before)
        self.assertFalse((self.root / "data/baselines/call").exists())
        self.hook("PostToolUse", options={"JJ_AGENT_SNAPSHOTS": "1"})
        self.assertNotEqual(self.op(), before)
        self.assertIn("jj-agent.step=", self.jj("op", "log", "--ignore-working-copy", "--no-graph", "-n", "1", "-T", "attributes"))

    def test_state_and_preamble_are_independent(self):
        text = self.hook("SessionStart", options={"JJ_AGENT_STATE": "0"})
        self.assertIn("Default flow", text)
        self.assertNotIn('<context key="jj-state">', text)
        text = self.hook("SessionStart", options={"JJ_AGENT_PREAMBLE": "0"})
        self.assertNotIn("Default flow", text)
        self.assertIn('<context key="jj-state">', text)
        self.assertEqual(self.hook("SessionStart", options={"JJ_AGENT_STATE": "0", "JJ_AGENT_PREAMBLE": "0"}), "")

    def test_muse_state_remains_disabled(self):
        text = self.hook("SessionStart", options={"MUSE_PLUGIN_ID": "jj-agent"})
        self.assertIn("Default flow", text)
        self.assertNotIn('<context key="jj-state">', text)

    def test_apm_scripts_do_not_need_the_checkout(self):
        apm = self.root / "apm-scripts"
        shutil.copytree(self.scripts, apm)
        shutil.rmtree(self.plugin)
        self.scripts = apm
        text = self.hook("SessionStart")
        self.assertIn("Default flow", text)
        self.assertIn("Workspace: default", text)

    def test_plain_git_is_untouched(self):
        plain = self.root / "plain"
        plain.mkdir()
        subprocess.run(["git", "init", "-q", str(plain)], env=self.env, check=True)
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
            self.assertEqual(self.hook(event, cwd=plain), "")
        self.assertFalse((plain / ".jj").exists())
        self.assertFalse((self.root / "data").exists())

    def test_git_worktrees_are_not_converted_by_default(self):
        worktree = self.root / "git-worktree"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "--detach", str(worktree)], env={**self.env, "JJ_SHIM_OFF": "1"}, check=True)
        self.assertEqual(self.hook("SessionStart", cwd=worktree), "")
        self.assertFalse((worktree / ".jj").exists())
        self.assertEqual((worktree / "user.txt").read_text(), "base\n")

    def test_failed_snapshot_never_reports_old_state_as_current(self):
        self.hook("SessionStart")
        wrapper = self.root / "bin"
        wrapper.mkdir()
        real_jj = shutil.which("jj")
        (wrapper / "jj").write_text(
            '#!/bin/bash\ncase " $* " in *" util snapshot "*) '
            'echo "Error: The working copy is stale" >&2; exit 1 ;; esac\n'
            f'exec "{real_jj}" "$@"\n'
        )
        (wrapper / "jj").chmod(0o755)
        text = self.hook("UserPromptSubmit", options={"PATH": f"{wrapper}:{self.env['PATH']}"}, error=True)
        self.assertIn("jj failed: Error: The working copy is stale", text)
        self.assertIn("jj workspace update-stale", text)
        self.assertNotIn("@ (working copy):", text)
        self.assertIn("@ (working copy):", self.hook("UserPromptSubmit"))

    def test_first_tool_entry_delivers_state_even_without_preamble(self):
        text = self.hook("PostToolUse", options={"JJ_AGENT_PREAMBLE": "0"})
        self.assertIn("Workspace: default", text)
        self.assertNotIn("Default flow", text)

    def test_detection_implies_snapshot_but_not_guard_or_adoption(self):
        options = {"JJ_AGENT_DETECT": "1", "JJ_AGENT_SNAPSHOTS": "0"}
        self.hook("SessionStart", options=options)
        self.hook("PreToolUse", options=options)
        self.assertTrue((self.root / "data/baselines/call").exists())
        (self.repo / "agent.txt").write_text("step\n")
        before = self.op()
        self.hook("PostToolUse", options=options)
        self.assertNotEqual(self.op(), before)
        self.assertFalse((self.root / "data/baselines/call").exists())

    def test_guard_is_opt_in_even_with_a_shim_already_on_path(self):
        (self.repo / "user.txt").write_text("user edit\n")
        self.jj("util", "snapshot")
        command = ["/bin/bash", str(self.scripts / "shim/git"), "checkout", "--", "user.txt"]
        enabled = subprocess.run(command, cwd=self.repo, env={**self.env, "JJ_AGENT_GUARD": "1", "JJ_SHIM_OFF": ""}, capture_output=True)
        self.assertNotEqual(enabled.returncode, 0)
        self.assertEqual((self.repo / "user.txt").read_text(), "user edit\n")
        disabled = subprocess.run(command, cwd=self.repo, env={**self.env, "JJ_AGENT_GUARD": "0"}, capture_output=True)
        self.assertEqual(disabled.returncode, 0)
        self.assertEqual((self.repo / "user.txt").read_text(), "base\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
