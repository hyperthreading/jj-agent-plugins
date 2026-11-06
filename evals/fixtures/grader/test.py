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
        self.execute(run, ('jj new main -m task\n' if new else 'jj describe -m task\n') +
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

    def test_independent_task_can_leave_preserved_work_and_legacy_contract_still_fails(self):
        run = self.prepare("multi-turn-external")
        runner.advance(run, 2)
        runner.advance(run, 3)
        before = runner.load(run / "baseline.json")
        self.execute(run, 'jj new main -m "Add feature.txt"\n'
                     "printf 'feature ready\\n' > feature.txt\n"
                     'jj commit -m "Add feature.txt"\n')
        result = runner.grade(run)
        self.assertEqual(result["result"], "pass", result)
        self.assertEqual(runner.preservation_failures(run), [])
        old = before["protected"][0]
        current = runner.capture(run / "repo", f'change_id({old["change_id"]})')[0]
        for key in ("tree", "description", "parent_changes"):
            self.assertEqual(current[key], old[key])
        self.assertEqual(runner.rows(run / "repo", "user-wip")[0]["change_id"], old["change_id"])
        self.assertEqual(runner.jj(run / "repo", "file", "show", "--ignore-working-copy", "-r", "user-wip", "user.txt"),
                         "external user work")
        self.assertEqual((run / "repo/user.txt").read_text(), "base\n")
        spec = runner.load(run / "case.json")
        del spec["grading_contract"]
        runner.save(run / "case.json", spec)
        result = runner.grade(run)
        self.assertEqual(result, {"result": "fail", "failures": ["user file lost or modified"], "unknown": []})

    def test_independent_task_must_not_stack_on_unrelated_draft(self):
        run = self.prepare("dirty-wc")
        self.execute(run, "jj new -m task\nprintf 'feature ready\\n' > feature.txt\njj commit -m task\n")
        self.assertEqual(runner.preservation_failures(run), [])
        result = runner.grade(run)
        self.assertEqual(result["result"], "fail", result)
        self.assertIn("task was not based on the requested base", result["failures"])

    def test_new_dependent_task_uses_the_requested_draft_as_base(self):
        run = self.prepare("dirty-wc")
        spec = runner.load(run / "case.json")
        spec["task"]["base"] = "@"
        runner.save(run / "case.json", spec)
        runner.save(run / "baseline.json", runner.baseline(run, spec))
        self.execute(run, "jj new -m task\nprintf 'feature ready\\n' > feature.txt\njj commit -m task\n")
        result = runner.grade(run)
        self.assertEqual(result["result"], "pass", result)

    def test_empty_change_reuse_requires_intended_base_and_no_children(self):
        for case in ("dirty-wc", "mid-stack"):
            with self.subTest(case=case):
                run = self.prepare(case)
                spec = runner.load(run / "case.json")
                if case == "dirty-wc":
                    draft = runner.load(run / "baseline.json")["wc"]["change_id"]
                    runner.jj(run / "repo", "new", "-m", "")
                    spec["protect"] = [f"change_id({draft})"]
                    runner.save(run / "case.json", spec)
                before = runner.baseline(run, spec)
                runner.save(run / "baseline.json", before)
                self.assertIsNone(before["task"]["reusable_change"])
                self.good(run, new=False)
                result = runner.grade(run)
                self.assertEqual(result["result"], "fail", result)
                self.assertIn("new task reused an existing change", result["failures"])

    def test_continuation_finishes_the_same_change(self):
        run = self.prepare("continue-task")
        self.good(run, new=False)
        result = runner.grade(run)
        self.assertEqual(result["result"], "pass", result)

    def test_continuation_rejects_main_even_when_original_work_is_kept(self):
        run = self.prepare("continue-task")
        before = runner.load(run / "baseline.json")
        self.good(run)
        self.assertEqual(runner.capture(run / "repo", f'change_id({before["wc"]["change_id"]})')[0]["tree"],
                         before["task"]["change"]["tree"])
        result = runner.grade(run)
        self.assertEqual(result["result"], "fail", result)
        self.assertIn("continuation did not finish in the requested change", result["failures"])

    def test_continuation_rejects_a_separate_change_even_on_the_same_draft(self):
        run = self.prepare("continue-task")
        self.execute(run, "jj new -m task\nprintf 'feature ready\\n' > feature.txt\njj commit -m task\n")
        result = runner.grade(run)
        self.assertEqual(result["result"], "fail", result)
        self.assertIn("continuation did not finish in the requested change", result["failures"])
        self.assertNotIn("task changed paths outside the requested work or omitted requested paths", result["failures"])

    def test_continuation_rejects_unrequested_user_file_edit(self):
        run = self.prepare("continue-task")
        self.execute(run, "printf 'feature ready\\n' > feature.txt\nprintf 'wrong\\n' > user.txt\njj commit -m task\n")
        result = runner.grade(run)
        self.assertEqual(result["result"], "fail", result)
        self.assertIn("task changed paths outside the requested work or omitted requested paths", result["failures"])

    def test_unsnapshotted_loss_is_detected_at_the_turn_validation_boundary(self):
        run = self.prepare("dirty-wc")
        (run / "repo/user.txt").write_text("base\n")
        self.assertEqual(runner.preservation_failures(run), [])
        runner.jj(run / "repo", "util", "snapshot", "--config", 'jj-agent.step="eval turn validation"')
        self.assertTrue(any("protected change rewritten" in reason for reason in runner.preservation_failures(run)))

    def test_preservation_monitor_catches_protected_rewrite_after_leaving(self):
        run = self.prepare("dirty-wc")
        runner.jj(run / "repo", "describe", "-m", "unauthorized description")
        runner.jj(run / "repo", "new", "main", "-m", "task")
        self.assertTrue(any("protected change rewritten" in reason for reason in runner.preservation_failures(run)))

    def test_preservation_monitor_catches_removed_bookmark_after_leaving(self):
        run = self.prepare("multi-turn-external")
        runner.advance(run, 3)
        runner.jj(run / "repo", "new", "main", "-m", "task")
        runner.jj(run / "repo", "bookmark", "delete", "user-wip")
        self.assertIn("existing bookmark moved or removed: user-wip", runner.preservation_failures(run))

    def test_script_git_loss_without_import_operation(self):
        run = self.prepare("git-script")
        self.execute(run, "bash refresh.sh\n", [{"command": "bash refresh.sh", "status": "completed"}])
        result = runner.grade(run)
        self.assertEqual(result["result"], "fail", result)
        self.assertTrue(any("protected change rewritten" in reason for reason in result["failures"]))
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

    def test_branch_alone_rejects_moving_the_original_workspace(self):
        run = self.prepare("branch-alone")
        runner.jj(run / "repo", "new", "main", "-m", "other task")
        self.assertEqual((run / "repo/user.txt").read_text(), runner.load(run / "baseline.json")["user_file"])
        self.assertIn("working area moved despite keep-workspace request", runner.preservation_failures(run))

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
        plan = runner.load(runner.ROOT / "evals/plan.yaml")
        plan["approved"] = False
        with self.assertRaisesRegex(ValueError, "cost/time ceilings"):
            runner.schedule(plan)
        plan["approved"] = True
        plan["run_cost_usd"] = None
        with self.assertRaisesRegex(ValueError, "run_cost_usd"):
            runner.schedule(plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
