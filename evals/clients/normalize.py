#!/usr/bin/env python3
"""Normalize tool observations; raw client JSONL is retained next to the result."""
import argparse
import json
from pathlib import Path
import re
import shlex


def annotate(record):
    text = record.get("command", "")
    record["direct_git"] = bool(re.search(r"(?:^|[;&|\n])\s*(?:\w+=\S+\s+)*(?:\S*/)?git(?:\s|$)", text))
    record["push"] = bool(re.search(r"\b(?:jj\s+git|git)\s+push\b", text))
    record["interactive"] = bool(re.search(r"\b(?:vim|nvim|nano|emacs)\b|\bjj\s+\S+[^\n]*(?:--interactive| -i\b)", text))
    return record


def shell_command(command):
    args = shlex.split(command)
    if len(args) == 3 and Path(args[0]).name in ("sh", "bash", "zsh") and args[1] in ("-c", "-lc"):
        return args[2]
    return command


def normalize(client, events):
    records, usage, pending = {}, [], set()
    turn = 0
    for event in events:
        if client == "codex" and event.get("type") == "turn.started":
            turn += 1
        if client == "opencode" and event.get("type") == "tool_use":
            part = event["part"]
            state = part["state"]
            records[part["id"]] = annotate({"id": part["id"], "tool": part["tool"], "status": state["status"],
                "input": state.get("input"), "command": (state.get("input") or {}).get("command", ""),
                "output": state.get("output"), "metadata": state.get("metadata"), "session": part.get("sessionID")})
        elif client == "opencode" and event.get("type") == "step_finish":
            usage.append(event["part"])
        elif client == "codex" and event.get("type") in ("item.started", "item.completed"):
            item = event["item"]
            if item.get("type") != "command_execution": continue
            key = f'{turn}:{item["id"]}'
            if event["type"] == "item.started": pending.add(key)
            else: pending.discard(key)
            records[key] = annotate({"id": key, "tool": "shell", "command": shell_command(item.get("command", "")),
                                    "client_command": item.get("command", ""),
                                    "status": "completed" if event["type"] == "item.completed" else "running",
                                    "exit": item.get("exit_code"), "output": item.get("aggregated_output")})
        elif client == "codex" and event.get("type") == "turn.completed":
            usage.append(event.get("usage", {}))
        elif client == "claude":
            for part in event.get("message", {}).get("content", []):
                if not isinstance(part, dict): continue
                if part.get("type") == "tool_use":
                    key = part["id"]
                    pending.add(key)
                    records[key] = annotate({"id": key, "tool": part["name"], "input": part["input"],
                        "command": part["input"].get("command", ""), "status": "running"})
                elif part.get("type") == "tool_result":
                    key = part["tool_use_id"]
                    pending.discard(key)
                    if key in records:
                        records[key].update(status="error" if part.get("is_error") else "completed", output=part.get("content"))
            if event.get("type") == "result": usage.append(event)
    return list(records.values()), {"raw": usage, "pending": sorted(pending)}


def observed(events):
    records, pending, unknown, shells = {}, set(), [], []
    for event in events:
        kind = event.get("event") or event.get("hook_event_name")
        if kind == "shell":
            shells.append(event)
            continue
        if kind not in ("tool.before", "tool.after", "PreToolUse", "PostToolUse", "PostToolUseFailure"):
            continue
        key = event.get("id") or event.get("tool_use_id")
        if not key:
            unknown.append("tool observation without call id")
            continue
        tool = event.get("tool") or event.get("tool_name")
        inp = event.get("input") or event.get("tool_input") or {}
        if kind in ("tool.before", "PreToolUse"):
            if key in records:
                unknown.append("duplicate tool start")
            pending.add(key)
            records[key] = annotate({"id": key, "tool": tool, "input": inp, "status": "running",
                "command": inp.get("command", inp.get("cmd", "")) if tool in ("shell", "Bash", "exec_command") else ""})
        else:
            if key not in pending:
                unknown.append("tool completion without start")
                continue
            pending.remove(key)
            result = event.get("result") or event.get("tool_response")
            records[key].update(status=event.get("status", "error" if kind == "PostToolUseFailure" else "completed"), output=result)
            if isinstance(result, dict) and result.get("metadata", {}).get("status") in ("running", "background"):
                unknown.append("tool returned before background command completion")
    if pending:
        unknown.append("tools still pending: " + ", ".join(sorted(pending)))
    for record in records.values():
        if re.search(r"\b(?:nohup|setsid)\b|\benv\s+-i\b|\b(?:unset\s+)?GIT_TRACE2|\bPopen\b|(?<!&)&(?!&)", record["command"]):
            unknown.append("command needs detached-process/trace review: " + record["id"])
    return list(records.values()), {"pending": sorted(pending), "unknown": sorted(set(unknown)), "shells": shells}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("client", choices=("opencode", "claude", "codex"))
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    events = [json.loads(line) for line in (args.evidence / "client.jsonl").read_text().splitlines()]
    records, usage = normalize(args.client, events)
    (args.evidence / "commands.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
    (args.evidence / "usage.json").write_text(json.dumps(usage, indent=2) + "\n")
