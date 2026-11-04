#!/usr/bin/env python3
"""Check the captured client request, before any provider dispatch is needed."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from texts(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from texts(item)


def verify(run, client):
    request = json.loads((run / "evidence/request-001.json").read_text())
    text = "\n".join(texts(request))
    preamble = (ROOT / "plugins/jj-agent/scripts/shared/preamble.md").read_text().strip()
    model = "claude-sonnet-5-5" if client == "claude" else "gpt-6.1-terra"
    effort = request.get("reasoning_effort") or request.get("reasoning", {}).get("effort") or request.get("output_config", {}).get("effort")
    options = json.loads((run / "delivery-options.json").read_text()) if (run / "delivery-options.json").exists() else {}
    standalone = options.get("package") == "jj-skill"
    checks = {"model": request.get("model") == model, "effort": effort == "medium",
              "preamble_count": text.count(preamble) == (0 if options.get("no_preamble") or standalone else 1),
              "state_count": text.count('<context key="jj-state">') == (0 if options.get("no_state") or standalone else 1),
              "repository": str(run / "repo") in text}
    for name in ("jj", "jj-workflow"):
        skill = (ROOT / f"plugins/jj-skill/skills/{name}/SKILL.md").read_text()
        description = next(line.removeprefix("description:").strip().strip('"')
                           for line in skill.splitlines() if line.startswith("description:"))
        checks[name + "_advertised"] = (description in text) == (options.get("disable_skill") != name)
    if client == "opencode":
        events = [json.loads(line) for line in (run / "evidence/observations.jsonl").read_text().splitlines()]
        context = next(e for e in events if e.get("event") == "context")
        skills = context["skills"]["data"]
        for name in ("jj", "jj-workflow"):
            body = (ROOT / f"plugins/jj-skill/skills/{name}/SKILL.md").read_text().split("---", 2)[2].strip()
            checks[name + "_body_registered"] = any(s["name"] == name and s["content"].strip() == body for s in skills) == (options.get("disable_skill") != name)
        plugins = [p for p in context["plugins"]["data"] if p["source"]["type"] != "builtin"]
        checks["plugin_isolation"] = {p["id"] for p in plugins} == {
            "jj-compass", "effective-context", "guidance-eval-observer"}
    result = {"client": client, "checks": checks, "passed": all(checks.values()),
              "scope": "first final client request at loopback gateway, before upstream dispatch"}
    (run / "evidence/delivery.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("client", choices=("opencode", "codex", "claude"))
    args = parser.parse_args()
    result = verify(args.run.resolve(), args.client)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
