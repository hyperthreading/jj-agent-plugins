#!/usr/bin/env python3
"""Serial mandatory smoke, then explicitly gated fixed-order pilot."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from finalize import finalize
from launch import ROOT
import runner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("phase", choices=("smoke", "pilot"))
    parser.add_argument("--attempt", type=int, default=2)
    args = parser.parse_args()
    root = args.directory.resolve()
    plan = runner.load(ROOT / "evals/plan.yaml")
    if args.phase == "pilot":
        acceptance = runner.load(root / "mandatory-acceptance.json")
        if any(acceptance.get(f"C{i}") is not True for i in range(1, 8)):
            raise SystemExit("mandatory acceptance is incomplete; pilot remains gated")
        entries = [{"client": "opencode", **r} for r in runner.load(ROOT / "evals/schedule.json")]
        if [{k: r[k] for k in ("case", "arm", "repeat")} for r in entries] != runner.schedule(plan):
            raise SystemExit("frozen schedule differs from the approved plan")
    else:
        entries = [{"client": c, "case": case, "arm": "default", "repeat": 1}
                   for case in plan["mandatory_smoke"]["cases"] for c in plan["mandatory_smoke"]["clients"]]
    results = []
    for index, entry in enumerate(entries):
        ledger = root / "budget.json"
        if ledger.exists() and runner.load(ledger)["stop"]:
            raise SystemExit("campaign stopped: " + runner.load(ledger)["stop"])
        name = f'{args.phase}-{entry["client"]}-{entry["case"]}-{entry["arm"]}-{args.attempt:02d}'
        run = root / name
        if run.exists():
            grade = runner.load(run / "grade.json")
            if grade["result"] != "pass":
                raise SystemExit(f"existing run needs investigation: {run}")
        else:
            command = [sys.executable, str(ROOT / "evals/clients/launch.py"), str(run), entry["client"], entry["case"],
                       "--arm", entry["arm"], "--phase", args.phase]
            result = subprocess.run(command, cwd=ROOT, timeout=300)
            if result.returncode:
                raise SystemExit(f"launcher failed: {name}")
        grade = finalize(run, entry["client"])
        results.append({"order": index + 1, **entry, **grade})
        runner.save(root / f"{args.phase}-attempt-{args.attempt:02d}.json", results)
        print(json.dumps(grade), flush=True)
        if grade["result"] != "pass":
            raise SystemExit("mandatory run needs investigation; remaining schedule not started")


if __name__ == "__main__":
    main()
