#!/usr/bin/env python3
"""Normalize tool observations; raw client JSONL is retained next to the result."""
import argparse
import json
from pathlib import Path
import re


def annotate(record):
    text = record.get("command", "")
    record["direct_git"] = bool(re.search(r"(?:^|[;&|\n])\s*(?:\w+=\S+\s+)*(?:\S*/)?git(?:\s|$)", text))
    record["push"] = bool(re.search(r"\b(?:jj\s+git|git)\s+push\b", text))
    record["interactive"] = bool(re.search(r"\b(?:vim|nvim|nano|emacs)\b|\bjj\s+\S+[^\n]*(?:--interactive| -i\b)", text))
    return record


def normalize(client, events):
    records, usage, pending = {}, [], set()
    for event in events:
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
            key = item["id"]
            if event["type"] == "item.started": pending.add(key)
            else: pending.discard(key)
            records[key] = annotate({"id": key, "tool": "shell", "command": item.get("command", ""),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("client", choices=("opencode", "claude", "codex"))
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    events = [json.loads(line) for line in (args.evidence / "client.jsonl").read_text().splitlines()]
    records, usage = normalize(args.client, events)
    (args.evidence / "commands.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
    (args.evidence / "usage.json").write_text(json.dumps(usage, indent=2) + "\n")
