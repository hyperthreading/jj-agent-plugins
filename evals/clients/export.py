#!/usr/bin/env python3
"""Export a stopped campaign's results and hashes without changing its ledger or grades."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from delivery import texts
from launch import fixture_environment
import runner


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_hashes(run):
    root = run / "packages"
    files = {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*"))
             if p.is_file() and "node_modules" not in p.relative_to(root).parts}
    return {"file_count": len(files), "sha256": hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def export(campaign, destination):
    ledger = runner.load(campaign / "budget.json")
    if not ledger["stop"]:
        raise ValueError("export requires a stopped campaign")
    files = set(campaign.glob("*.json"))
    attempts, captures, packages = [], [], {}
    for spec_path in sorted(campaign.glob("*/case.json")):
        run = spec_path.parent
        files.update(p for p in run.glob("*.json"))
        files.update(p for p in (run / "evidence").rglob("*") if p.is_file())
        files.update(p for p in (run / "guidance").rglob("*") if p.is_file())
        packages[run.name] = package_hashes(run)
        for name in ("sandbox.sb", "home/config/opencode/opencode.json", "home/codex/config.toml",
                     "home/codex/hooks.json", "home/claude/settings.json", "repo/apm.lock.yaml",
                     "repo/.codex/hooks.json", "repo/.claude/settings.json"):
            path = run / name
            if path.is_file():
                files.add(path)
        spec = runner.load(spec_path)
        if run.name in ledger["runs"]:
            usage = ledger["runs"][run.name]
            done = runner.load(run / "evidence/completion.json")
            attempts.append({"run": run.name, "client": run.name.split("-")[1], "case": spec["case"],
                "arm": spec["arm"], "grade": runner.load(run / "grade.json"), "exit": done["exit"],
                "stop": done["stop"], "seconds": done["seconds"], "requests": usage["steps"],
                "input_tokens": sum(r["usage"]["input"] for r in usage["requests"] if "usage" in r),
                "output_tokens": sum(r["usage"]["output"] for r in usage["requests"] if "usage" in r),
                "charged_micro_usd": usage["charged"], "pending_micro_usd": sum(usage["pending"].values()),
                "preparation_versions": runner.load(run / "versions.json")})
        delivery = run / "evidence/delivery.json"
        if delivery.exists():
            captures.append({"run": run.name, **runner.load(delivery)})
    for name in ("apm-check/pack.txt", "apm-check/install.txt", "tools/install-apm.txt"):
        files.add(campaign / name)
    summary = {"raw_root": str(campaign), "stop": ledger["stop"], "plan": ledger["plan"],
        "charged_micro_usd": sum(r["charged"] for r in ledger["runs"].values()),
        "pending_micro_usd": sum(sum(r["pending"].values()) for r in ledger["runs"].values()),
        "forwarded_requests": sum(r["steps"] for r in ledger["runs"].values()),
        "paid_attempts": attempts, "delivery_captures": captures, "package_trees": packages,
        "unexecuted_smoke": [{"client": c, "case": "control"} for c in ledger["plan"]["mandatory_smoke"]["clients"]],
        "pilot_runs_executed": 0, "comparative_conclusion": "inconclusive: pilot not started"}

    run = campaign / "smoke-claude-multi-turn-external-default-02"
    before = runner.load(run / "baseline.json")
    old = before["protected"][0]
    with fixture_environment(runner.load(run / "evidence/environment.json")):
        current = runner.capture(run / "repo", f'change_id({old["change_id"]})')[0]
        bookmark = runner.rows(run / "repo", "user-wip")[0]["change_id"]
        content = runner.jj(run / "repo", "file", "show", "--ignore-working-copy", "-r", "user-wip", "user.txt")
    request_text = "\n".join(texts(runner.load(run / "evidence/request-005.json")))
    states = re.findall(r'<context key="jj-state">(.*?)</context>', request_text, re.S)
    observations = [json.loads(line) for line in (run / "evidence/observations.jsonl").read_text().splitlines()]
    commands = [e["tool_input"]["command"] for e in observations
                if e.get("hook_event_name") == "PreToolUse" and e.get("tool_name") == "Bash"]
    preservation = {"run": run.name, "grade": runner.load(run / "grade.json"),
        "last_bash_command": commands[-1], "baseline_user_file": before["user_file"],
        "workspace_user_file": (run / "repo/user.txt").read_text(), "protected_change": old["change_id"],
        "protected_fields_match": {k: current[k] == old[k] for k in ("tree", "description", "parent_changes")},
        "bookmark_matches": bookmark == old["change_id"], "user_wip_file_stripped": content,
        "latest_delivered_state": states[-1].strip(),
        "interpretation": "Current-workspace content condition failed after branching from main; protected user history remains intact. Interrupted run stays unknown with observed failures."}
    destination.mkdir(parents=True, exist_ok=False)
    runner.save(destination / "summary.json", summary)
    runner.save(destination / "preservation.json", preservation)
    (destination / "SHA256SUMS").write_text("".join(
        f"{digest(p)}  {p.relative_to(campaign)}\n" for p in sorted(files)))
    return {"attempts": len(attempts), "captures": len(captures), "hashed_files": len(files),
            "charged_micro_usd": summary["charged_micro_usd"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.campaign.resolve(), args.destination.resolve()), indent=2))
