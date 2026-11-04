#!/usr/bin/env python3
"""Native-client passive hooks; never emit guidance or alter a tool decision."""
import json
import os
import sys
import urllib.request

event = json.load(sys.stdin)
event["_trace"] = os.environ.get("GIT_TRACE2_EVENT")
request = urllib.request.Request(os.environ["EVAL_GATEWAY"] + "/observe",
    data=json.dumps(event).encode(), headers={"Content-Type": "application/json",
    "x-eval-token": os.environ["EVAL_GATE_TOKEN"]}, method="POST")
with urllib.request.urlopen(request, timeout=10) as response:
    response.read()
