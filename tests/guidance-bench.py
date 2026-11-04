#!/usr/bin/env python3
"""Measure complete default hooks (including snapshot) and the read-only L1 renderer separately."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/jj-agent/scripts"
parser = argparse.ArgumentParser()
parser.add_argument("--runs", type=int, default=15)
parser.add_argument("--sizes", type=int, nargs="+", default=[10, 5000, 30000])
args = parser.parse_args()


def distribution(values):
    values = sorted(values)
    return {"n": len(values), "min_ms": round(values[0], 2), "p50_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[math.ceil(len(values) * .95) - 1], 2), "max_ms": round(values[-1], 2)}


with tempfile.TemporaryDirectory(prefix="jj-guidance-bench-") as tmp:
    tmp = Path(tmp).resolve()
    config = tmp / "jj.toml"
    config.write_text('user.name="Benchmark"\nuser.email="bench@example.invalid"\n')
    env = {key: value for key, value in os.environ.items() if not key.startswith(("JJ_AGENT_", "CLAUDE_", "CODEX_", "MUSE_"))}
    env.update(JJ_CONFIG=str(config), CLAUDE_PLUGIN_DATA=str(tmp / "data"))
    result = {"jj": subprocess.check_output(["jj", "--version"], text=True).strip(), "platform": platform.platform(), "sizes": {}}
    for size in args.sizes:
        repo = tmp / str(size)
        repo.mkdir()
        for index in range(size):
            directory = repo / str(index // 200)
            directory.mkdir(exist_ok=True)
            (directory / f"f{index}").write_text("base\n" * 20)
        subprocess.run(["jj", "git", "init"], cwd=repo, env=env, check=True, capture_output=True)
        subprocess.run(["jj", "commit", "-m", "base"], cwd=repo, env=env, check=True, capture_output=True)
        samples = {key: [] for key in ("session_start", "unchanged_prompt", "edited_prompt", "state_reader")}
        for index in range(args.runs + 1):
            for key in samples:
                if key == "edited_prompt": (repo / "0/f0").write_text(f"external edit {index}\n")
                script = "session-start.sh" if key == "session_start" else "user-prompt.sh"
                event = "SessionStart" if key == "session_start" else "UserPromptSubmit"
                payload = json.dumps(dict(cwd=str(repo), session_id="bench", hook_event_name=event))
                argv = ["/bin/bash", str(SCRIPTS / script)]
                if key == "state_reader":
                    argv = ["/bin/bash", "-c", '. "$1"; read_jj_state "$2"', "bash", str(SCRIPTS / "state.sh"), str(repo)]
                started = time.perf_counter()
                run = subprocess.run(argv, input=payload, cwd=repo, env=env, check=True, text=True, capture_output=True)
                elapsed = (time.perf_counter() - started) * 1000
                if run.stderr or "jj failed:" in run.stdout: raise RuntimeError(run.stderr + run.stdout)
                if index: samples[key].append(elapsed)
        result["sizes"][size] = {key: distribution(values) for key, values in samples.items()}
    print(json.dumps(result, indent=2))
