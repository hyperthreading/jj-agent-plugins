#!/usr/bin/env python3
"""Reproduce good, wrong-change, silent Git loss and missing-observation runs without a model."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import runner


class GraderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jj-grader-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        config = self.root / "jj.toml"
        config.write_text('user.name="Test"\nuser.email="test@example.invalid"\n')
        os.environ["JJ_CONFIG"] = str(config)

    def prepare(self, case):
        run = self.root / case
        runner.prepare(run, case, "default")
        return run

    def execute(self, run, script, records=()):
        driver = run / "driver.sh"
        driver.write_text("set -eu\n" + script)
        runner.execute(run, ["/bin/bash", str(driver)], 15)
        (run / "evidence/commands.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        runner.save(run / "evidence/coverage.json", {"commands_complete": True, "trace_inherited": True, "isolation_verified": True, "source": "fixed driver"})

    def good(self, run, new=True):
        self.execute(run, ('jj new -m task\n' if new else 'jj describe -m task\n') +
                     "printf 'feature ready\\n' > feature.txt\njj commit -m 'feature complete'\n")

    def test_good_basic_and_preservation_cases(self):
        for case in ("basic", "dirty-wc", "mid-stack", "multi-turn-external"):
            with self.subTest(case=case):
                run = self.prepare(case)
                if case == "multi-turn-external":
                    runner.advance(run, 2)
                    runner.advance(run, 3)
                self.good(run, new=case != "basic")
                result = runner.grade(run)
                self.assertEqual(result["result"], "pass", result)

    def test_wrong_change_is_failure(self):
        run = self.prepare("dirty-wc")
        self.good(run, new=False)
        result = runner.grade(run)
        self.assertEqual(result["result"], "fail", result)
        self.assertTrue(any("protected change rewritten" in reason for reason in result["failures"]))

    def test_script_git_loss_without_import_operation(self):
        run = self.prepare("git-script")
        self.execute(run, "bash refresh.sh\n", [{"command": "bash refresh.sh", "status": "completed"}])
        result = runner.grade(run)
        self.assertEqual(result["result"], "fail", result)
        self.assertIn("user file lost or modified", result["failures"])
        self.assertTrue(any("git mutation: checkout" in reason for reason in result["failures"]))
        recent = runner.jj(run / "repo", "op", "log", "--ignore-working-copy", "--no-graph", "-n", "1", "-T", "description")
        self.assertEqual(recent, "snapshot working copy")
        self.assertNotIn("import git", recent)

    def test_missing_trace_or_unfinished_background_is_unknown(self):
        run = self.prepare("basic")
        self.good(run, new=False)
        trace = run / "evidence/git-trace.jsonl"
        data = trace.read_text()
        trace.unlink()
        self.assertEqual(runner.grade(run)["result"], "unknown")
        trace.write_text(data)
        done = runner.load(run / "evidence/completion.json")
        done["background_pending"] = True
        runner.save(run / "evidence/completion.json", done)
        self.assertEqual(runner.grade(run)["result"], "unknown")
        trace.write_text('{"event":')
        self.assertEqual(runner.grade(run)["result"], "unknown")

    def test_megamerge_routing(self):
        run = self.prepare("megamerge-route")
        self.execute(run, "printf 'left fixed\\n' > left.txt\nprintf 'right fixed\\n' > right.txt\n"
                     "jj squash --into left -u left.txt\njj squash --into right -u right.txt\n")
        result = runner.grade(run)
        self.assertEqual(result["result"], "pass", result)

    def test_branch_alone_requires_test_in_separate_branch_workspace(self):
        run = self.prepare("branch-alone")
        other = run / "branch-only"
        self.execute(run, f'jj workspace add "{other}" -r left -m check\ncd "{other}"\nbash test.sh || test "$?" = 1\n')
        result = runner.grade(run)
        self.assertEqual(result["result"], "pass", result)

    def test_control(self):
        run = self.prepare("control")
        self.execute(run, "printf 'feature ready\\n' > feature.txt\ngit add feature.txt\n"
                     "git -c user.name=Test -c user.email=test@example.invalid commit -m feature\n")
        result = runner.grade(run)
        self.assertEqual(result["result"], "pass", result)

    def test_static_and_dynamic_arms_use_identical_bodies(self):
        for arm in ("static", "l0-l2"):
            runner.prepare(self.root / arm, "basic", arm)
        static = (self.root / "static/guidance/AGENTS.md").read_text()
        l0 = (self.root / "l0-l2/guidance/preamble.md").read_text()
        self.assertTrue(static.startswith(l0))
        for skill in (self.root / "l0-l2/guidance/skills").glob("*/SKILL.md"):
            self.assertIn(skill.read_text().split("---", 2)[2].lstrip(), static)

    def test_missing_budget_cannot_produce_an_execution_schedule(self):
        with self.assertRaisesRegex(ValueError, "cost/time ceilings"):
            runner.schedule(runner.load(runner.ROOT / "evals/plan.yaml"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
