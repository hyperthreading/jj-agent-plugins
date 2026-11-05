#!/usr/bin/env python3
"""Fixed-case isolated launches. Model traffic can only reach the budget gateway."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import secrets
import selectors
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runner
from budget import Budget, LimitReached, write_json
from gateway import Gateway

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HOST_HOME = Path.home()


def environment(run):
    home = run / "home"
    env = {k: os.environ[k] for k in ("PATH", "LANG", "USER", "LOGNAME") if k in os.environ}
    env.update(HOME=str(home), TMPDIR=str(run / "tmp"), XDG_CONFIG_HOME=str(home / "config"),
        XDG_DATA_HOME=str(home / "data"), XDG_CACHE_HOME=str(home / "cache"), XDG_STATE_HOME=str(home / "state"),
        OPENCODE_CONFIG_DIR=str(home / "config/opencode"), CODEX_HOME=str(home / "codex"),
        CLAUDE_CONFIG_DIR=str(home / "claude"), CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        CLAUDE_CODE_TMPDIR=str(run / "tmp"), CLAUDE_CODE_SHELL="/bin/bash",
        DISABLE_AUTOUPDATER="1", JJ_CONFIG=str(home / "jj.toml"), GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="Guidance checks", GIT_AUTHOR_EMAIL="guidance@example.invalid",
        GIT_COMMITTER_NAME="Guidance checks", GIT_COMMITTER_EMAIL="guidance@example.invalid", NO_COLOR="1",
        EVAL_RUN_TOKEN=secrets.token_hex(16), JJ_AGENT_SNAPSHOTS="0", JJ_AGENT_GUARD="0",
        JJ_AGENT_DETECT="0", JJ_AGENT_ADOPT_WORKTREES="0")
    for name in ("HOME", "TMPDIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
                 "OPENCODE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    Path(env["JJ_CONFIG"]).write_text('user.name="Guidance checks"\nuser.email="guidance@example.invalid"\n')
    return env


@contextlib.contextmanager
def fixture_environment(env):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def checked(argv, cwd, env, log):
    with log.open("w") as output:
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=90)
    if result.returncode:
        raise RuntimeError(f"installation failed ({result.returncode}): {log}")


def install(run, client, env, opencode_source, phase):
    packages = run / "packages"
    packages.mkdir()
    source = packages / "marketplace"
    source.mkdir()
    shutil.copytree(ROOT / ".claude-plugin", source / ".claude-plugin")
    shutil.copytree(ROOT / "plugins/jj-agent", source / "plugins/jj-agent")
    shutil.copytree(ROOT / "plugins/jj-skill", source / "plugins/jj-skill")
    evidence = run / "evidence"
    spec = runner.load(run / "case.json")
    delivery = runner.load(run / "delivery-options.json") if (run / "delivery-options.json").exists() else {}
    package = delivery.get("package", "jj-agent")
    apm = delivery.get("apm")
    env["JJ_AGENT_PREAMBLE"] = "0" if delivery.get("no_preamble") else "1"
    env["JJ_AGENT_STATE"] = "0" if delivery.get("no_state") else "1"
    if client == "opencode":
        for name in ("jj-compass", "effective-context"):
            dest = packages / name
            shutil.copytree(opencode_source / name, dest, ignore=shutil.ignore_patterns("node_modules", ".git", ".jj"))
            checked(["bun", "install", "--ignore-scripts"], dest, env, evidence / f"install-{name}.txt")
        observer = packages / "observer"
        observer.mkdir()
        shutil.copy(HERE / "observer.ts", observer / "index.ts")
        (observer / "node_modules").symlink_to(packages / "jj-compass/node_modules", target_is_directory=True)
        options = runner.load(run / "guidance/compass-options.json")
        if phase == "smoke":
            options["preparedState"] = False
        if delivery.get("no_preamble") or package == "jj-skill": options["preamble"] = False
        if delivery.get("no_state") or package == "jj-skill": options["instructions"] = False
        if delivery.get("disable_skill") == "jj": options["commandSkill"] = False
        if delivery.get("disable_skill") == "jj-workflow": options["workflow"] = False
        model = {"name": "GPT-6.1 Terra", "limit": {"context": 372000, "output": 128000},
            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
            "compatibility": {"reasoningField": "reasoning_content"},
            "settings": {"reasoningEffort": "medium"},
            "variants": [{"id": "medium", "settings": {"reasoningEffort": "medium"}}]}
        config = {"$schema": "https://opencode.ai/config.json", "model": "opencodex/gpt-6.1-terra",
            "update": "disable", "shell": "/bin/bash", "snapshots": False,
            "plugins": [{"package": str(packages / "jj-compass"), "options": options},
                        str(packages / "effective-context"), str(observer)],
            "providers": {"opencodex": {"package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": env["EVAL_GATEWAY"] + "/v1", "apiKey": "{env:EVAL_GATE_TOKEN}"},
                "models": {"gpt-6.1-terra": model}}},
            "policies": [{"action": "provider.use", "resource": "*", "effect": "deny"},
                         {"action": "provider.use", "resource": "opencodex", "effect": "allow"}]}
        if spec["arm"] in ("static", "nudge"):
            config["instructions"] = [str(run / "guidance" / ("AGENTS.md" if spec["arm"] == "static" else "preamble.md"))]
        write_json(Path(env["OPENCODE_CONFIG_DIR"]) / "opencode.json", config)
    else:
        if apm:
            checked([apm, "install", str(source / "plugins" / package), "--target", client],
                    run / "repo", env, evidence / "apm-install.txt")
        observer = packages / "observer.py"
        shutil.copy(HERE / "observer.py", observer)
        hooks = {"hooks": {name: [{"hooks": [{"type": "command",
            "command": shlex.join([sys.executable, str(observer)]), "timeout": 15}]}]
            for name in ("PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop")}}
        if client == "claude":
            hooks["hooks"]["PostToolUseFailure"] = hooks["hooks"]["PostToolUse"]
        if client == "codex":
            if not apm:
                checked(["codex", "plugin", "marketplace", "add", str(source), "--json"], run / "repo", env, evidence / "marketplace.txt")
                checked(["codex", "plugin", "add", package + "@hyperthreading", "--json"], run / "repo", env, evidence / "install.txt")
            config = Path(env["CODEX_HOME"]) / "config.toml"
            installed = config.read_text() if config.exists() else ""
            config.write_text('model="gpt-6.1-terra"\nmodel_provider="evaluation"\nmodel_reasoning_effort="medium"\n'
                'web_search="disabled"\nshell_environment_policy.inherit="all"\n'
                '[model_providers.evaluation]\nname="Evaluation gateway"\nwire_api="responses"\n'
                f'base_url="{env["EVAL_GATEWAY"]}/v1"\nenv_key="EVAL_GATE_TOKEN"\n'
                'request_max_retries=0\nstream_max_retries=0\n\n' + installed)
            if apm:
                with config.open("a") as file:
                    file.write(f'\n[projects.{json.dumps(str(run / "repo"))}]\ntrust_level="trusted"\n')
            if delivery.get("disable_skill"):
                installed_path = runner.load(evidence / "install.txt")["installedPath"]
                with config.open("a") as file:
                    file.write(f'\n[[skills.config]]\npath={json.dumps(installed_path + "/skills/" + delivery["disable_skill"] + "/SKILL.md")}\nenabled=false\n')
            write_json(Path(env["CODEX_HOME"]) / "hooks.json", hooks)
        else:
            if not apm:
                checked(["claude", "plugin", "install", package, "--marketplace", str(source), "--json"],
                        run / "repo", env, evidence / "install.txt")
            config = Path(env["CLAUDE_CONFIG_DIR"]) / "settings.json"
            settings = runner.load(config) if config.exists() else {}
            settings.update(hooks=hooks["hooks"], effortLevel="medium")
            if delivery.get("disable_skill"):
                settings["permissions"] = {"deny": [f'Skill({package}:{delivery["disable_skill"]})']}
            write_json(config, settings)
            env.update(ANTHROPIC_BASE_URL=env["EVAL_GATEWAY"], ANTHROPIC_API_KEY=env["EVAL_GATE_TOKEN"],
                       CLAUDE_CODE_MAX_OUTPUT_TOKENS="8192")
    write_json(evidence / "environment.json", {k: v for k, v in env.items() if k not in ("EVAL_GATE_TOKEN", "ANTHROPIC_API_KEY", "OPENCODE_PASSWORD")})
    write_json(evidence / "package-hashes.json", {str(p.relative_to(packages)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(packages.rglob("*")) if p.is_file() and "node_modules" not in p.relative_to(packages).parts})
    write_json(evidence / "launcher-hashes.json", {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / "evals").rglob("*")) if p.suffix in (".py", ".ts", ".yaml", ".json", ".md", ".sh")})


def sandbox(run, port, server_port=None):
    # All children inherit Seatbelt, including detached commands. Live home data and
    # other checkouts are unreadable; writes are limited to this run's working areas.
    allowed = [run / p for p in ("home", "tmp", "repo", "workspaces")]
    readable = [run, HOST_HOME / ".local/share/mise", HOST_HOME / ".local/bin"]
    parents = sorted({p for root in readable for p in root.parents})
    reads = ' '.join(f'(subpath {json.dumps(str(p))})' for p in readable)
    reads += ' ' + ' '.join(f'(literal {json.dumps(str(p))})' for p in parents)
    writes = ' '.join(f'(subpath {json.dumps(str(p))})' for p in allowed)
    writes += ' (literal "/dev/null") (literal "/dev/tty") (subpath "/dev/fd")'
    network = f'(remote ip "localhost:{port}") (remote unix-socket)'
    if server_port:
        network += f' (remote ip "localhost:{server_port}")'
    rules = ['(version 1)', '(allow default)',
             f'(deny file-write* (require-not (require-any {writes})))',
             f'(deny file-read-data (require-all (subpath {json.dumps(str(HOST_HOME))}) (require-not (require-any {reads}))))',
             f'(deny network-outbound (require-not (require-any {network})))']
    path = run / "sandbox.sb"
    path.write_text("\n".join(rules) + "\n")
    return ["/usr/bin/sandbox-exec", "-f", str(path)]


def preservation_stop(run, budget):
    violations = runner.preservation_failures(run)
    if violations:
        reason = "; ".join(violations)
        budget.stop("preservation violation: " + reason)
        write_json(run / "evidence/preservation-stop.json", violations)
        return reason
    return None


def argv_for(client, prompt, session=None, server=None, apm=False):
    if client == "opencode":
        args = ["opencode", "run", "--server", server, "--auto", "--format", "json", "--model", "opencodex/gpt-6.1-terra#medium"]
        if session:
            args += ["--session", session]
        return args + [prompt]
    if client == "codex":
        args = ["codex", "exec", "--strict-config", "--ignore-rules", "--json", "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust"]
        if session:
            args += ["resume", session]
        return args + [prompt]
    args = ["claude", "-p", "--model", "claude-sonnet-5-5", "--effort", "medium",
            "--output-format", "stream-json", "--verbose", "--include-hook-events", "--max-budget-usd", "1",
            "--dangerously-skip-permissions", "--strict-mcp-config", "--setting-sources", "user,project,local" if apm else "user", "--no-chrome"]
    if session:
        args += ["--resume", session]
    return args + [prompt]


def private_server(run, wrapper, env, port):
    log = (run / "evidence/server-stderr.txt").open("w")
    proc = subprocess.Popen(wrapper + ["opencode", "serve", "--stdio", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=run / "repo", env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, start_new_session=True)
    log.close()
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        if not selector.select(timeout=30):
            kill_group(proc)
            raise RuntimeError("private OpenCode server did not announce readiness")
        line = proc.stdout.readline()
    (run / "evidence/server-ready.json").write_bytes(line)
    if not line:
        proc.wait()
        raise RuntimeError("private OpenCode server exited before readiness")
    return proc


def stop_server(proc):
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        kill_group(proc)
    proc.stdout.close()


def kill_group(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin can return EPERM while a sandboxed group leader exits. Only
        # accept the race when wait proves the process has actually ended.
        proc.wait(timeout=1)
    proc.wait(timeout=5)


def verify_isolation(run, wrapper, env, gateway_port, upstream):
    managed = [Path(p) for p in ("/Library/Application Support/opencode", "/Library/Managed Preferences/ai.opencode.managed.plist",
        f"/Library/Managed Preferences/{HOST_HOME.name}/ai.opencode.managed.plist", "/Library/Application Support/ClaudeCode/managed-settings.json",
        "/etc/codex/config.toml", "/etc/codex/requirements.toml")]
    unexpected = [str(p) for p in managed if p.exists()]
    endpoint = urlparse(upstream)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port:
        raise ValueError("this launcher requires an explicit loopback HTTP upstream port")
    script = '''import json, socket, sys
from pathlib import Path
checks={}
try:
    with open(sys.argv[3], "rb") as file: file.read(1)
    checks["live_config_denied"]=False
except PermissionError: checks["live_config_denied"]=True
p=Path(sys.argv[1])
try:
    p.write_text("isolation probe")
    p.unlink()
    checks["outside_write_denied"]=False
except PermissionError: checks["outside_write_denied"]=True
try:
    with socket.create_connection(("127.0.0.1",int(sys.argv[4])),timeout=1): pass
    checks["direct_upstream_denied"]=False
except PermissionError: checks["direct_upstream_denied"]=True
with socket.create_connection(("127.0.0.1",int(sys.argv[2])),timeout=1): pass
checks["gateway_allowed"]=True
print(json.dumps(checks))
'''
    result = subprocess.run(wrapper + [sys.executable, "-c", script, str(run.parent / (run.name + "-write-probe")), str(gateway_port),
        str(HOST_HOME / ".config/opencode/opencode.json"), str(endpoint.port)],
        cwd=run / "repo", env=env, capture_output=True, text=True, timeout=10, check=True)
    checks = json.loads(result.stdout)
    checks["no_managed_sources"] = not unexpected
    write_json(run / "evidence/isolation.json", {"checks": checks, "unexpected": unexpected,
        "sandbox_sha256": hashlib.sha256((run / "sandbox.sb").read_bytes()).hexdigest()})
    if not all(checks.values()):
        raise RuntimeError("isolation preflight failed")


def tagged_processes(token):
    # Do not log ps's environment-bearing output. The unique marker also finds
    # reparented/background children that retained their launch environment.
    env = {k: v for k, v in os.environ.items() if k != "EVAL_RUN_TOKEN"}
    text = subprocess.check_output(["ps", "eww", "-axo", "pid=,command="], text=True, env=env)
    return [int(line.split(None, 1)[0]) for line in text.splitlines()
            if f"EVAL_RUN_TOKEN={token}" in line and int(line.split(None, 1)[0]) != os.getpid()]


def stop_tagged_processes(token):
    for pid in tagged_processes(token):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while tagged_processes(token):
        if time.monotonic() >= deadline:
            raise RuntimeError("evaluation processes remain after cleanup")
        time.sleep(0.05)


def launch(run, client, phase, plan, campaign, opencode_source, capture_only=False):
    env = environment(run)
    # Extract only the selected connection, before replacing HOME for host-side jj commands.
    connection = runner.load(HOST_HOME / ".config/opencode/opencode.json")["providers"]["opencodex"]["settings"]
    with fixture_environment(env):
        return launch_isolated(run, client, phase, plan, campaign, opencode_source, env, connection, capture_only)


def launch_isolated(run, client, phase, plan, campaign, opencode_source, env, connection, capture_only):
    evidence = run / "evidence"
    observation_lock = threading.Lock()
    cleanup = contextlib.ExitStack()
    budget = None if capture_only else Budget(campaign / "budget.json", plan)
    if budget:
        cleanup.callback(budget.close)
    model = "claude-sonnet-5-5" if client == "claude" else "gpt-6.1-terra"
    token = secrets.token_hex(24)

    def observe(event):
        with observation_lock:
            with (evidence / "observations.jsonl").open("a") as out:
                out.write(json.dumps(event) + "\n")

    server = None
    try:
        if budget:
            budget.check()
        gateway = Gateway(evidence, budget, run.name, connection["baseURL"], connection["apiKey"], model,
                          token, capture_only=capture_only, observe=observe)
        cleanup.callback(gateway.close)
        cleanup.callback(stop_tagged_processes, env["EVAL_RUN_TOKEN"])
        env.update(EVAL_GATEWAY=gateway.url, EVAL_GATE_TOKEN=token)
        if client == "opencode":
            env["OPENCODE_PASSWORD"] = secrets.token_hex(24)
        install(run, client, env, opencode_source, phase)
        server_port = None
        if client == "opencode":
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                server_port = sock.getsockname()[1]
        wrapper = sandbox(run, gateway.server.server_port, server_port)
        verify_isolation(run, wrapper, env, gateway.server.server_port, connection["baseURL"])
        # Trace output must be writable by child Git. Archive it after all children exit.
        trace = run / "home/git-trace.jsonl"
        trace.touch()
        env.update(GIT_TRACE2_EVENT=str(trace), EVAL_TEST_LOG=str(run / "home/branch-tests.jsonl"))
        if client == "opencode":
            server = private_server(run, wrapper, env, server_port)
            cleanup.callback(stop_server, server)
        infrastructure = tagged_processes(env["EVAL_RUN_TOKEN"]) if server else []
        write_json(evidence / "infrastructure.json", {"pids_before_prompt": infrastructure, "server_pid": server.pid if server else None})
        server_url = f"http://127.0.0.1:{server_port}" if server else None
        runner.command(run / "repo", ["git", "rev-parse", "--show-toplevel"],
                       {**env, "GIT_TRACE2_EVENT": str(evidence / "probe.jsonl")})
        if budget:
            budget.start(run.name)
        started = time.monotonic()
        spec = runner.load(run / "case.json")
        apm = runner.load(run / "delivery-options.json").get("apm")
        session, turns, leftovers = None, [], []
        stop, code = None, None
        for turn in range(1, spec["turns"] + 1):
            if turn > 1:
                runner.advance(run, turn)
            if phase == "pilot" and spec["fixture"] != "git":
                preparation = time.monotonic()
                runner.jj(run / "repo", "util", "snapshot", "--config", f'jj-agent.step="eval prompt {turn}"')
                write_json(evidence / f"preparation-{turn}.json", {"seconds": time.monotonic() - preparation})
            case = ROOT / "evals/cases" / spec["case"]
            prompt_file = case / (f"turns/{turn}.md" if spec["turns"] > 1 else "prompt.md")
            prompt = prompt_file.read_text()
            argv = wrapper + argv_for(client, prompt, session, server_url, apm)
            with (evidence / f"client-{turn}.jsonl").open("w") as out, (evidence / f"stderr-{turn}.txt").open("w") as err:
                proc = subprocess.Popen(argv, cwd=run / "repo", env=env, stdout=out, stderr=err, start_new_session=True)
                cleanup.callback(kill_group, proc)
                while proc.poll() is None:
                    if gateway.stopped:
                        stop = gateway.stopped
                    elif time.monotonic() - started >= plan["run_seconds"]:
                        stop = "run wall-time limit"
                    elif budget:
                        try:
                            budget.check(run.name)
                        except LimitReached as error:
                            stop = str(error)
                    if not capture_only:
                        stop = preservation_stop(run, budget) or stop
                    if stop:
                        kill_group(proc)
                        break
                    try:
                        proc.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        pass
                code = proc.wait()
            if not capture_only:
                # Validate unsnapshotted edits after the client turn has ended.
                # Polling the file view during a checkout can falsely report loss.
                if spec["fixture"] != "git" and spec.get("grading_contract", 1) >= 2:
                    runner.jj(run / "repo", "util", "snapshot", "--config", 'jj-agent.step="eval turn validation"')
                stop = preservation_stop(run, budget) or stop
                if stop:
                    budget.stop(stop)
            remaining = [pid for pid in tagged_processes(env["EVAL_RUN_TOKEN"]) if pid not in infrastructure]
            leftovers.extend(remaining)
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            turns.append({"turn": turn, "exit": code, "stop": stop, "argv": argv_for(client, prompt, session, server_url, apm)})
            events = [json.loads(line) for line in (evidence / f"client-{turn}.jsonl").read_text().splitlines() if line.strip()]
            for event in events:
                session = event.get("sessionID") or event.get("session_id") or event.get("thread_id") or session
            if code or stop or remaining:
                break
            if turn < spec["turns"] and not session:
                stop = "session id was not observed; cannot resume"
                break
        cleanup.close()
        stop = stop or gateway.stopped or (budget.data["stop"] if budget else None)
        shutil.copy(trace, evidence / "git-trace.jsonl")
        if (run / "home/branch-tests.jsonl").exists():
            shutil.copy(run / "home/branch-tests.jsonl", evidence / "branch-tests.jsonl")
        (evidence / "client.jsonl").write_text("".join(p.read_text() for p in sorted(evidence.glob("client-*.jsonl"))))
        write_json(evidence / "completion.json", {"exit": code, "timeout": stop is not None,
            "background_pending": bool(leftovers), "seconds": time.monotonic() - started,
            "stop": stop, "turns": turns, "leftover_pids": leftovers})
        return {"client": client, "stop": stop, "exit": code, "requests": gateway.count}
    finally:
        cleanup.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("client", choices=("opencode", "codex", "claude"))
    parser.add_argument("case")
    parser.add_argument("--arm", default="default", choices=runner.ARMS)
    parser.add_argument("--phase", default="smoke", choices=("smoke", "pilot"))
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--no-preamble", action="store_true")
    parser.add_argument("--no-state", action="store_true")
    parser.add_argument("--disable-skill", choices=("jj", "jj-workflow"))
    parser.add_argument("--package", choices=("jj-agent", "jj-skill"), default="jj-agent")
    parser.add_argument("--apm", type=Path)
    parser.add_argument("--opencode-source", type=Path, default=ROOT.parent / "jj-agent-guidance-opencode")
    args = parser.parse_args()
    if args.client != "opencode" and (args.arm != "default" or args.phase == "pilot"):
        parser.error("comparative arms are implemented only for OpenCode")
    if args.apm and (not args.capture_only or args.client == "opencode" or args.disable_skill):
        parser.error("APM path is for native-client delivery captures")
    run = args.directory.resolve()
    if run.exists():
        raise SystemExit("use a fresh run directory")
    # Fixture setup needs isolated jj/Git identity before runner.prepare creates the directory.
    staging = run.parent / (run.name + "-setup")
    env = environment(staging)
    with fixture_environment(env):
        runner.prepare(run, args.case, args.arm)
    shutil.rmtree(staging)
    write_json(run / "delivery-options.json", {"no_preamble": args.no_preamble, "no_state": args.no_state,
                                               "disable_skill": args.disable_skill, "package": args.package,
                                               "apm": str(args.apm.resolve()) if args.apm else None})
    print(json.dumps(launch(run, args.client, args.phase, runner.load(ROOT / "evals/plan.yaml"),
                            run.parent, args.opencode_source, args.capture_only), indent=2))


if __name__ == "__main__":
    main()
