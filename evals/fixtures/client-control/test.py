#!/usr/bin/env python3
"""Admission, crash accounting and protocol fixtures; no model or credential access."""
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import secrets
import tempfile
import threading
import urllib.request
import urllib.error
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clients"))
from budget import Budget, LimitReached
from gateway import Gateway, Usage
from launch import preservation_stop, tagged_processes
import runner
from normalize import normalize, observed, shell_command

PLAN = {"approved": True, "total_cost_usd": 2, "total_seconds": 90, "run_seconds": 30,
        "run_cost_usd": 1, "max_steps": 2, "rates_per_million": {"test": {"input": 2, "output": 10}}}


class Admission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "budget.json"
        self.now = 100.0
        self.budget = Budget(self.path, copy.deepcopy(PLAN), lambda: self.now)
        self.budget.start("run")

    def tearDown(self):
        self.budget.close()
        self.temp.cleanup()

    def test_reserves_before_dispatch_and_settles_cache_conservatively(self):
        key = self.budget.reserve("run", "test", 100000, 80000)
        self.assertEqual(json.loads(self.path.read_text())["runs"]["run"]["pending"][key], 1_000_000)
        with self.assertRaises(LimitReached):
            self.budget.reserve("run", "test", 1, 1)
        self.budget.settle("run", key, {"input": 1000, "output": 200})
        self.assertEqual(self.budget.total(), 4000)
        self.assertEqual(self.budget.reserve("run", "test", 1, 1), "2")

    def test_steps_survive_turn_boundaries(self):
        for _ in range(2):
            key = self.budget.reserve("run", "test", 10, 10)
            self.budget.settle("run", key, {"input": 0, "output": 0})
        with self.assertRaisesRegex(LimitReached, "model-request"):
            self.budget.reserve("run", "test", 10, 10)
        with self.assertRaises(LimitReached):
            self.budget.start("run")

    def test_missing_usage_never_becomes_zero(self):
        key = self.budget.reserve("run", "test", 10, 10)
        self.budget.settle("run", key, None)
        self.assertEqual(self.budget.total(), 120)
        with self.assertRaisesRegex(LimitReached, "missing"):
            self.budget.start("next")

    def test_crash_retains_reservation_and_stops_restart(self):
        self.budget.reserve("run", "test", 10, 10)
        self.budget.close()
        self.budget = Budget(self.path, copy.deepcopy(PLAN), lambda: self.now)
        self.assertEqual(self.budget.total(), 120)
        with self.assertRaisesRegex(LimitReached, "unsettled"):
            self.budget.start("next")

    def test_two_launchers_cannot_double_spend(self):
        with self.assertRaisesRegex(LimitReached, "another campaign"):
            Budget(self.path, copy.deepcopy(PLAN))

    def test_concurrent_requests_admit_at_most_one_large_reservation(self):
        results = []
        def attempt():
            try:
                results.append(self.budget.reserve("run", "test", 100000, 50000))
            except LimitReached:
                results.append("denied")
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sorted(results), ["1", "denied"])

    def test_run_and_campaign_deadlines(self):
        self.now = 130
        with self.assertRaisesRegex(LimitReached, "run wall-time"):
            self.budget.reserve("run", "test", 1, 1)
        self.now = 190
        with self.assertRaisesRegex(LimitReached, "campaign wall-time"):
            self.budget.start("next")

    def test_total_limit_spans_runs(self):
        for name in ("run", "second"):
            if name != "run": self.budget.start(name)
            key = self.budget.reserve(name, "test", 0, 100000)
            self.budget.settle(name, key, {"input": 0, "output": 100000})
        with self.assertRaisesRegex(LimitReached, "campaign cost"):
            self.budget.start("third")

    def test_upstream_limit_breach_stops_campaign(self):
        key = self.budget.reserve("run", "test", 10, 10)
        self.budget.settle("run", key, {"input": 10, "output": 11})
        with self.assertRaisesRegex(LimitReached, "exceeded"):
            self.budget.start("next")

    def test_plan_cannot_change_after_start(self):
        self.budget.close()
        changed = {**PLAN, "max_steps": 3}
        with self.assertRaisesRegex(LimitReached, "plan changed"):
            Budget(self.path, changed)

    def test_restart_retains_original_stop_reason_with_pending_usage(self):
        self.budget.reserve("run", "test", 10, 10)
        self.budget.stop("preservation violation")
        self.budget.close()
        self.budget = Budget(self.path, copy.deepcopy(PLAN), lambda: self.now)
        with self.assertRaisesRegex(LimitReached, "^preservation violation$"):
            self.budget.check()

    def test_post_exit_preservation_check_stops_later_admissions(self):
        run = Path(self.temp.name) / "fixture"
        (run / "repo").mkdir(parents=True)
        (run / "evidence").mkdir()
        runner.save(run / "case.json", {"fixture": "empty"})
        runner.save(run / "baseline.json", {"protected": [], "user_file": "user edit\n"})
        (run / "repo/user.txt").write_text("base\n")
        self.assertEqual(preservation_stop(run, self.budget), "user file lost or modified")
        with self.assertRaisesRegex(LimitReached, "preservation violation"):
            self.budget.reserve("run", "test", 10, 10)


class ProtocolUsage(unittest.TestCase):
    def test_chat_requires_terminal_and_usage(self):
        usage = Usage()
        usage.accept({"usage": {"prompt_tokens": 1000, "completion_tokens": 20}})
        self.assertIsNone(usage.result())
        usage.accept("[DONE]")
        self.assertEqual(usage.result(), {"input": 1000, "output": 20})

    def test_responses_includes_reasoning_in_output(self):
        usage = Usage()
        usage.accept({"type": "response.completed", "response": {"usage": {
            "input_tokens": 100, "output_tokens": 70, "output_tokens_details": {"reasoning_tokens": 50}}}})
        self.assertEqual(usage.result(), {"input": 100, "output": 70})

    def test_anthropic_counts_cache_read_and_write_input(self):
        usage = Usage()
        usage.accept({"type": "message_start", "message": {"usage": {"input_tokens": 10,
            "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 500, "output_tokens": 1}}})
        usage.accept({"type": "message_delta", "usage": {"output_tokens": 20}})
        usage.accept({"type": "message_stop"})
        self.assertEqual(usage.result(), {"input": 1510, "output": 20})


class Observation(unittest.TestCase):
    def test_codex_resume_reuses_item_ids_without_losing_commands(self):
        turn = [{"type": "turn.started"}, {"type": "item.completed", "item": {
            "type": "command_execution", "id": "item_1", "command": "cat user.txt", "exit_code": 0}}]
        records, usage = normalize("codex", turn + turn)
        self.assertEqual(len(records), 2)
        self.assertEqual(usage["pending"], [])

    def test_codex_shell_wrapper_preserves_command_quotes(self):
        self.assertEqual(shell_command('/bin/zsh -lc "jj describe -m \'feature\' && jj st"'), "jj describe -m 'feature' && jj st")

    def test_nested_tool_calls_pair_by_id(self):
        records, coverage = observed([
            {"event": "tool.before", "tool": "execute", "id": "outer", "input": {"code": "..."}},
            {"event": "tool.before", "tool": "shell", "id": "inner", "input": {"command": "jj st"}},
            {"event": "tool.after", "tool": "shell", "id": "inner", "status": "completed"},
            {"event": "tool.after", "tool": "execute", "id": "outer", "status": "completed"}])
        self.assertEqual(coverage["unknown"], [])
        self.assertEqual([r["command"] for r in records], ["", "jj st"])

    def test_background_return_is_not_command_completion(self):
        _, coverage = observed([
            {"event": "tool.before", "tool": "shell", "id": "a", "input": {"command": "slow"}},
            {"event": "tool.after", "tool": "shell", "id": "a", "status": "completed",
             "result": {"metadata": {"status": "running"}}}])
        self.assertIn("tool returned before background command completion", coverage["unknown"])

    def test_native_missing_post_hook_remains_unknown(self):
        _, coverage = observed([{"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                "tool_use_id": "a", "tool_input": {"command": "jj st"}}])
        self.assertTrue(coverage["unknown"])

    def test_process_probe_does_not_report_itself(self):
        token = secrets.token_hex(16)
        old = os.environ.get("EVAL_RUN_TOKEN")
        os.environ["EVAL_RUN_TOKEN"] = token
        try:
            self.assertEqual(tagged_processes(token), [])
        finally:
            if old is None: os.environ.pop("EVAL_RUN_TOKEN")
            else: os.environ["EVAL_RUN_TOKEN"] = old

    def test_detached_process_with_inherited_marker_is_visible(self):
        token = secrets.token_hex(16)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
            env={**os.environ, "EVAL_RUN_TOKEN": token}, start_new_session=True)
        try:
            self.assertIn(child.pid, tagged_processes(token))
        finally:
            child.kill()
            child.wait()


class TransportAdmission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        plan = {**copy.deepcopy(PLAN), "request_output_limit": 100,
                "rates_per_million": {"gpt-6.1-terra": {"input": 2.5, "output": 7.5}}}
        self.budget = Budget(self.path / "ledger.json", plan)
        self.budget.start("run")
        self.received = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        owner = self
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                owner.received.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
                owner.entered.set()
                owner.release.wait(timeout=5)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"usage":{"prompt_tokens":10,"completion_tokens":2}}\n\ndata: [DONE]\n\n')
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.thread = threading.Thread(target=self.upstream.serve_forever)
        self.thread.start()
        self.gateway = Gateway(self.path, self.budget, "run", f"http://127.0.0.1:{self.upstream.server_port}/v1",
                               "upstream-secret", "gpt-6.1-terra", "local-secret")

    def tearDown(self):
        self.gateway.close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.thread.join()
        self.budget.close()
        self.temp.cleanup()

    def request(self, **overrides):
        body = {"model": "gpt-6.1-terra", "reasoning_effort": "medium", "stream": True,
                "messages": [{"role": "user", "content": "hello"}], "max_tokens": 9999, **overrides}
        request = urllib.request.Request(self.gateway.url + "/v1/chat/completions", data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer local-secret", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            error.close()
            raise

    def test_cap_and_usage_are_applied_to_real_http_exchange(self):
        self.assertIn(b"[DONE]", self.request())
        self.assertEqual(self.received[0]["max_tokens"], 100)
        self.assertTrue(self.received[0]["stream_options"]["include_usage"])
        # EOF is sent after settlement; closing joins the request before ledger inspection.
        self.assertEqual(self.budget.total(), 40)
        self.assertNotIn("upstream-secret", "".join(p.read_text() for p in self.path.glob("*.json")))

    def test_wrong_model_cannot_reach_upstream(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.request(model="other")
        self.assertEqual(self.received, [])
        self.assertEqual(self.budget.data["runs"]["run"]["steps"], 0)

    def test_close_waits_for_request_settlement(self):
        self.release.clear()
        response = []
        request = threading.Thread(target=lambda: response.append(self.request()))
        request.start()
        self.assertTrue(self.entered.wait(timeout=5))
        closed = threading.Event()
        def close():
            self.gateway.close()
            closed.set()
        closer = threading.Thread(target=close)
        closer.start()
        try:
            self.assertFalse(closed.wait(timeout=0.6))
        finally:
            self.release.set()
            request.join(timeout=5)
            closer.join(timeout=5)
        self.assertTrue(closed.is_set())
        self.assertEqual(self.budget.data["runs"]["run"]["pending"], {})
        self.assertEqual(self.budget.total(), 40)
        self.assertIn(b"[DONE]", response[0])

    def test_invalid_output_limit_cannot_reach_upstream(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.request(max_tokens=None)
        self.assertEqual(self.received, [])

    def test_over_budget_request_is_denied_before_forwarding(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.request(messages=[{"role": "user", "content": "x" * 500000}])
        self.assertEqual(self.received, [])

    def test_opaque_previous_context_is_not_priced_as_empty(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.request(previous_response_id="resp_unknown")
        self.assertEqual(self.received, [])

    def test_capture_only_never_dispatches(self):
        self.gateway.capture_only = True
        with self.assertRaises(urllib.error.HTTPError):
            self.request()
        self.assertEqual(self.received, [])
        self.assertTrue((self.path / "request-001.json").exists())


if __name__ == "__main__":
    unittest.main()
