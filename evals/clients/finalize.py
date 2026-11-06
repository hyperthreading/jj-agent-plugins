#!/usr/bin/env python3
"""Join passive tool observations with client events; leave missing coverage unknown."""
import argparse
import collections
import json
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runner
from normalize import normalize, observed
from launch import fixture_environment


def finalize(run, client):
    evidence = run / "evidence"
    previous = run / "grade.json"
    if previous.exists():
        content = previous.read_bytes()
        (evidence / ("grade-" + hashlib.sha256(content).hexdigest()[:12] + ".json")).write_bytes(content)
    events = [json.loads(line) for line in (evidence / "client.jsonl").read_text().splitlines() if line.strip()]
    observations = [json.loads(line) for line in (evidence / "observations.jsonl").read_text().splitlines()]
    cli, usage = normalize(client, events)
    records, coverage = observed(observations)
    (evidence / "commands.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    runner.save(evidence / "usage.json", usage)
    if client == "opencode":
        trace_ok = all(s.get("trace") == str(run / "home/git-trace.jsonl") for s in coverage["shells"])
        cli_ids = {r["id"] for r in cli}
        observed_ids = {r["id"] for r in records}
        paired = cli_ids == observed_ids
    else:
        trace_ok = all(e.get("_trace") == str(run / "home/git-trace.jsonl") for e in observations
                       if e.get("hook_event_name") in ("PreToolUse", "PostToolUse"))
        cli_commands = collections.Counter(r["command"] for r in cli if r.get("command"))
        observed_commands = collections.Counter(r["command"] for r in records if r.get("command"))
        paired = cli_commands == observed_commands
    isolation_path = evidence / "isolation.json"
    isolation = runner.load(isolation_path) if isolation_path.exists() else {}
    proof = {"commands_complete": bool(records) and paired and not coverage["unknown"] and not usage["pending"],
             "trace_inherited": trace_ok and bool(records),
             "isolation_verified": bool(isolation.get("checks")) and all(isolation["checks"].values()),
             "client_observer_match": paired, "observation_unknown": coverage["unknown"],
             "scope": "paired client/passive tool events; traced Git; inherited process markers; Seatbelt. Environment scrubbing/libgit2 are not certified."}
    runner.save(evidence / "coverage.json", proof)
    env = runner.load(evidence / "environment.json")
    # Never trace grader preparation or reuse live jj settings.
    with fixture_environment(env):
        result = runner.grade(run)
    return {"client": client, "run": run.name, **result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("client", choices=("opencode", "codex", "claude"))
    args = parser.parse_args()
    print(json.dumps(finalize(args.run.resolve(), args.client), indent=2))
