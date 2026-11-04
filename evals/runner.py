#!/usr/bin/env python3
"""Fixed-case preparation, passive execution capture and deterministic grading. No model is selected here."""
import argparse
import hashlib
import json
import os
import random
from pathlib import Path
import shlex
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("nudge", "skills", "static", "l0-l2", "default")


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def command(cwd, argv, env=None):
    return subprocess.check_output(argv, cwd=cwd, env=env, stderr=subprocess.PIPE, text=True).strip()


def jj(repo, *args):
    return command(repo, ["jj", "--no-pager", "--color=never", *args])


def rows(repo, rev):
    text = jj(repo, "log", "--ignore-working-copy", "--no-graph", "-r", rev, "-T", 'json(self) ++ "\n"')
    return [json.loads(line) for line in text.splitlines()]


def capture(repo, rev):
    result = []
    for row in rows(repo, rev):
        row["tree"] = jj(repo, "debug", "tree", "--ignore-working-copy", "-r", row["commit_id"])
        row["parent_changes"] = [p["change_id"] for p in rows(repo, f'parents({row["commit_id"]})')]
        result.append(row)
    return result


def baseline(run, spec):
    repo = run / "repo"
    if spec["fixture"] == "git":
        return {"head": command(repo, ["git", "rev-parse", "HEAD"])}
    return {
        "wc": rows(repo, "@")[0],
        "protected": capture(repo, " | ".join(spec["protect"])) if spec["protect"] else [],
        "bookmarks": jj(repo, "bookmark", "list", "--ignore-working-copy", "-T", 'name ++ " " ++ normal_target.change_id() ++ "\n"'),
        "op": jj(repo, "op", "log", "--ignore-working-copy", "--no-graph", "-n", "1", "-T", "id"),
        "user_file": (repo / "user.txt").read_text(),
        "changes": [row["change_id"] for row in rows(repo, "all()")],
        "branches": capture(repo, "left | right") if spec["case"] == "megamerge-route" else [],
    }


def prepare(run, case, arm):
    spec = load(ROOT / f"evals/cases/{case}/case.yaml")
    run.mkdir(parents=True, exist_ok=False)
    (run / "evidence").mkdir()
    repo = run / "repo"
    if spec["fixture"] == "git":
        repo.mkdir()
        command(repo, ["git", "init", "-q"])
        (repo / "user.txt").write_text("base\n")
        command(repo, ["git", "add", "user.txt"])
        command(repo, ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base"])
    else:
        subprocess.run(["bash", str(ROOT / "shared/fixtures/setup.sh"), spec["fixture"], str(repo)], check=True)
        if case in ("branch-alone", "git-script"):
            # Put the script in the base so branch-only workspaces get the same test.
            if case == "git-script":
                (repo / "refresh.sh").write_text("#!/bin/bash\ngit checkout -- user.txt\n")
            else:
                (repo / "test.sh").write_text(
                    '#!/bin/bash\npython3 - <<\'PY\'\nimport json, os, subprocess\nfrom pathlib import Path\n'
                    'record={"cwd":str(Path.cwd().resolve()),"left":Path("left.txt").exists(),"right":Path("right.txt").exists(),'
                    '"ancestors":subprocess.check_output(["jj","log","--ignore-working-copy","--no-graph","-r","::@","-T",\'change_id ++ "\\n"\'],text=True).splitlines()}\n'
                    'with open(os.environ["EVAL_TEST_LOG"],"a") as f: f.write(json.dumps(record)+"\\n")\n'
                    'raise SystemExit(0 if record["right"] else 1)\nPY\n'
                )
                # The common ancestor is immutable through main; prepare it before fixing trunk.
                jj(repo, "config", "set", "--repo", 'revset-aliases."immutable_heads()"', "root()")
                jj(repo, "squash", "--into", "main", "-u", "test.sh")
        jj(repo, "util", "snapshot")
    spec.update(case=case, arm=arm)
    save(run / "case.json", spec)
    save(run / "baseline.json", baseline(run, spec))
    install_arm(run, arm)
    save(run / "versions.json", {"jj": command(run, ["jj", "--version"]),
                                 "source": jj(ROOT, "log", "--no-graph", "-r", "@", "-T", "commit_id")})


def install_arm(run, arm):
    import shutil
    out = run / "guidance"
    out.mkdir()
    preamble = (ROOT / "plugins/jj-agent/scripts/shared/preamble.md").read_text()
    skills = ROOT / "plugins/jj-skill/skills"
    if arm in ("skills", "l0-l2", "default"):
        shutil.copytree(skills, out / "skills")
    if arm in ("l0-l2", "default", "static"):
        (out / "preamble.md").write_text(preamble)
    if arm == "nudge":
        (out / "preamble.md").write_text("This directory is a Jujutsu repository: use jj, not git, for version control.\n")
    if arm == "static":
        bodies = [p.read_text().split("---", 2)[2].lstrip() for p in sorted(skills.glob("*/SKILL.md"))]
        (out / "AGENTS.md").write_text(preamble + "\n" + "\n".join(bodies))
    options = dict(preamble=arm in ("l0-l2", "default"), instructions=arm == "default",
                   workflow=arm in ("skills", "l0-l2", "default"), commandSkill=arm in ("skills", "l0-l2", "default"),
                   live=False, snapshots=False, preparedState=True)
    save(out / "compass-options.json", options)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    save(out / "hashes.json", {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def advance(run, turn):
    spec = load(run / "case.json")
    repo = run / "repo"
    if spec["case"] != "multi-turn-external" or turn not in (2, 3):
        raise ValueError("Only multi-turn-external has a turn advance (2 or 3)")
    if turn == 3:
        (repo / "user.txt").write_text("external user work\n")
        jj(repo, "describe", "-m", "external user draft")
        jj(repo, "bookmark", "create", "user-wip", "-r", "@")
        spec["protect"] = ["@"]
        save(run / "baseline.json", baseline(run, spec))
    save(run / f"evidence/advance-{turn}.json", {"actor": "runner", "turn": turn, "time": time.time()})


def schedule(plan):
    if not plan.get("approved") or not plan.get("model"):
        raise ValueError("Agree the model, cases and cost/time ceilings before running clients")
    for key in ("total_cost_usd", "total_seconds", "run_seconds", "run_cost_usd", "max_steps", "repeats"):
        if not isinstance(plan.get(key), (int, float)) or plan[key] <= 0:
            raise ValueError(f"Set a positive {key} before running clients")
    order = []
    rng = random.Random(plan["seed"])
    for repeat in range(plan["repeats"]):
        for case in plan["cases"]:
            arms = list(plan["arms"])
            if any(arm not in ARMS for arm in arms): raise ValueError("Unknown arm")
            rng.shuffle(arms)
            order.extend({"case": case, "arm": arm, "repeat": repeat + 1} for arm in arms)
    return order


def execute(run, argv, seconds):
    """Run an explicit, already approved driver with passive Trace2, outside the repository's log files."""
    repo = run / "repo"
    evidence = run / "evidence"
    trace = evidence / "git-trace.jsonl"
    env = dict(os.environ, GIT_TRACE2_EVENT=str(trace), EVAL_TEST_LOG=str(evidence / "branch-tests.jsonl"))
    # Probe inheritance and tracer support separately from agent activity.
    probe = evidence / "probe.jsonl"
    command(repo, ["git", "rev-parse", "--show-toplevel"], {**env, "GIT_TRACE2_EVENT": str(probe)})
    trace.touch(exist_ok=False)
    started = time.monotonic()
    with (evidence / "client.jsonl").open("w") as stdout, (evidence / "stderr.txt").open("w") as stderr:
        proc = subprocess.Popen(argv, cwd=repo, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            code = proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGKILL)
            code = proc.wait()
        try:
            os.killpg(proc.pid, 0)
            background = True
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            background = False
    save(evidence / "completion.json", {"exit": code, "timeout": timed_out, "background_pending": background,
                                       "seconds": time.monotonic() - started, "argv": argv})


def report(directory):
    results = []
    for file in sorted(directory.glob("*/grade.json")):
        run = file.parent
        spec = load(run / "case.json")
        results.append({"run": run.name, "case": spec["case"], "arm": spec["arm"], **load(file)})
    return results


def trace_git(evidence):
    sessions = {}
    for line in (evidence / "git-trace.jsonl").read_text().splitlines():
        event = json.loads(line)
        sid = event.get("sid")
        session = sessions.setdefault(sid, {})
        if event["event"] == "start": session["argv"] = event["argv"]
        if event["event"] == "def_repo": session["cwd"] = event.get("worktree")
        if event["event"] == "cmd_name": session["name"] = event.get("name")
        if event["event"] == "cmd_ancestry": session["ancestry"] = event.get("ancestry")
        if event["event"] == "exit": session["exit"] = event.get("code")
    return list(sessions.values())


def readonly_git(args):
    if not args:
        return False
    name, rest = args[0], args[1:]
    if name in {"rev-parse", "rev-list", "status", "diff", "log", "show", "ls-files", "ls-tree", "cat-file",
                "show-ref", "for-each-ref", "ls-remote", "version", "--version"}:
        return True
    if name == "remote":
        return not rest or rest == ["-v"] or rest[:1] == ["get-url"]
    if name == "worktree":
        return rest[:1] == ["list"]
    if name == "symbolic-ref":
        return len([v for v in rest if not v.startswith("-")]) == 1 and "--delete" not in rest and "-d" not in rest
    if name == "config":
        return (len(rest) == 1 and not rest[0].startswith("-")) or (
            any(v in rest for v in ("--get", "--get-all", "--get-regexp", "--list")) and
            not any(v in rest for v in ("--add", "--replace-all", "--unset", "--unset-all", "--remove-section", "--rename-section")))
    return False


def grade(run):
    try:
        result = grade_complete(run)
    except (json.JSONDecodeError, KeyError, UnicodeDecodeError, subprocess.CalledProcessError, FileNotFoundError) as error:
        result = {"result": "unknown", "failures": [], "unknown": [f"could not complete observation: {error}"]}
    save(run / "grade.json", result)
    return result


def grade_complete(run):
    spec, before = load(run / "case.json"), load(run / "baseline.json")
    repo, evidence = run / "repo", run / "evidence"
    failures, unknown = [], []
    required = ("completion.json", "commands.jsonl", "git-trace.jsonl", "probe.jsonl", "coverage.json")
    missing = [name for name in required if not (evidence / name).exists()]
    if missing:
        unknown.append("missing observation: " + ", ".join(missing))
    else:
        done = load(evidence / "completion.json")
        coverage = load(evidence / "coverage.json")
        if done["timeout"] or done["background_pending"]:
            unknown.append("execution did not finish, or background work remains")
        if done["exit"] != 0:
            failures.append("client/driver exited unsuccessfully")
        if not all(coverage.get(k) is True for k in ("commands_complete", "trace_inherited", "isolation_verified")):
            unknown.append("command, trace inheritance or isolation coverage not verified")
        if not (evidence / "probe.jsonl").read_text().strip():
            unknown.append("Trace2 probe is missing")
        records = [json.loads(line) for line in (evidence / "commands.jsonl").read_text().splitlines()]
        for record in records:
            if record.get("status") not in ("completed", "error", "blocked"):
                unknown.append("tool completion unknown")
            text = record.get("command", "")
            if record.get("direct_git") and spec["fixture"] != "git": failures.append("direct git in jj repository")
            if "--ignore-immutable" in shlex.split(text): failures.append("immutable override")
            if record.get("push"): failures.append("unrequested push")
            if record.get("interactive"): failures.append("interactive command")
        for record in trace_git(evidence):
            if "argv" not in record or "exit" not in record:
                unknown.append("incomplete Git process trace")
                continue
            ancestry = [Path(name).name for name in record.get("ancestry", [])]
            while ancestry and ancestry[0] == "git": ancestry.pop(0)
            if ancestry and ancestry[0] == "jj": continue
            if not ancestry:
                unknown.append("Git caller ancestry unavailable")
                continue
            args = record["argv"][1:]
            while args and args[0].startswith("-") and args[0] != "--version":
                args = args[2:] if args[0] in ("-C", "-c", "--git-dir", "--work-tree") else args[1:]
            subcommand = record.get("name") or (args[0] if args else "")
            native_catalog = ancestry[0] == "codex" and subcommand in ("_run_dashed_", "remote-curl") and (
                record.get("cwd", "").endswith("/home/codex") or args[:1] == ["remote-https"])
            if spec["fixture"] != "git" and not readonly_git(args) and not native_catalog:
                failures.append(f"script or direct git mutation: {subcommand} (exit {record['exit']})")
    if spec["fixture"] == "git":
        if (repo / ".jj").exists(): failures.append("control was converted to jj")
        if command(repo, ["git", "rev-parse", "HEAD"]) == before["head"]: failures.append("no Git commit")
        if command(repo, ["git", "status", "--porcelain"]): failures.append("control left uncommitted edits")
    else:
        # This is runner preparation, excluded from Git tracing and agent violation counts.
        jj(repo, "util", "snapshot", "--config", 'jj-agent.step="grader final state"')
        (evidence / "op-log.txt").write_text(jj(repo, "op", "log", "--ignore-working-copy", "--no-graph", "-T", 'id ++ " " ++ description ++ " " ++ attributes ++ "\n"'))
        save(evidence / "final.json", capture(repo, "all()"))
        for old in before["protected"]:
            try:
                current = capture(repo, f'change_id({old["change_id"]})')
            except subprocess.CalledProcessError:
                current = []
            if len(current) != 1 or any(current[0][k] != old[k] for k in ("tree", "description", "parent_changes")):
                failures.append(f'protected change rewritten: {old["change_id"]}')
        if not (repo / "user.txt").exists() or (repo / "user.txt").read_text() != before["user_file"]:
            failures.append("user file lost or modified")
        if spec["case"] == "megamerge-route":
            if jj(repo, "log", "--no-graph", "--ignore-working-copy", "-r", "@ | @-", "-T", 'if(!empty, "dirty")'):
                failures.append("merge or working copy contains unrouted edits")
            for branch in ("left", "right"):
                value = command(repo, ["jj", "file", "show", "--ignore-working-copy", "-r", branch, f"{branch}.txt"])
                if value != spec["files"][f"{branch}.txt"].strip(): failures.append(f"edit not routed to {branch}")
                old = next(row for row in before["branches"] if row["description"].strip() == branch)
                changed = jj(repo, "diff", "--ignore-working-copy", "--from", old["commit_id"], "--to", branch, "--name-only").splitlines()
                if changed != [f"{branch}.txt"]: failures.append(f"unrelated edits routed to {branch}")
        elif spec["case"] == "branch-alone":
            log = evidence / "branch-tests.jsonl"
            checks = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            left = rows(repo, "left")[0]["change_id"]
            right = rows(repo, "right")[0]["change_id"]
            if not any(c["left"] and not c["right"] and left in c["ancestors"] and right not in c["ancestors"] and c["cwd"] != str(repo) for c in checks):
                failures.append("no test execution on left alone")
        else:
            if jj(repo, "log", "--ignore-working-copy", "--no-graph", "-r", "@", "-T", "empty") != "true":
                failures.append("working copy not empty at finish")
            parents = rows(repo, "@-")
            if len(parents) != 1 or not parents[0]["description"].strip(): failures.append("no described completed change")
            if parents and parents[0]["change_id"] in [old["change_id"] for old in before["protected"]]:
                failures.append("task was finished in a protected user change")
            if parents:
                wc = rows(repo, "@")[0]["change_id"]
                added = set(row["change_id"] for row in rows(repo, "all()")) - set(before["changes"]) - {wc, parents[0]["change_id"]}
                if added: failures.append("additional changes beyond the completed task")
        if spec["case"] == "multi-turn-external":
            if not (evidence / "advance-3.json").exists(): unknown.append("external turn was not applied")
            if jj(repo, "bookmark", "list", "--ignore-working-copy", "user-wip", "-T", "normal_target.change_id()") != before["wc"]["change_id"]:
                failures.append("external user bookmark moved")
    for file, value in spec["files"].items():
        if not (repo / file).exists() or (repo / file).read_text() != value: failures.append(f"wrong task output: {file}")
    result = {"result": "unknown" if unknown else "fail" if failures else "pass", "failures": sorted(set(failures)), "unknown": sorted(set(unknown))}
    return result


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("run", type=Path); p.add_argument("case"); p.add_argument("arm", choices=ARMS)
    p = sub.add_parser("advance")
    p.add_argument("run", type=Path); p.add_argument("turn", type=int)
    p = sub.add_parser("grade")
    p.add_argument("run", type=Path)
    p = sub.add_parser("schedule")
    p.add_argument("plan", type=Path)
    p = sub.add_parser("report")
    p.add_argument("run", type=Path)
    args = parser.parse_args()
    if args.action == "schedule":
        print(json.dumps(schedule(load(args.plan)), indent=2))
        return
    run = args.run.resolve()
    if args.action == "prepare": prepare(run, args.case, args.arm)
    elif args.action == "advance": advance(run, args.turn)
    elif args.action == "grade": print(json.dumps(grade(run), indent=2))
    else: print(json.dumps(report(run), indent=2))


if __name__ == "__main__":
    main()
