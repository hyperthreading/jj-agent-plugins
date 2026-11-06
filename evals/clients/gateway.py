"""Loopback admission/capture proxy for the three selected client protocols."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request

from budget import LimitReached, write_json


class Usage:
    def __init__(self):
        self.input = self.output = None
        self.terminal = False

    def accept(self, event):
        if event == "[DONE]":
            self.terminal = True
            return
        kind = event.get("type")
        if kind in ("response.completed", "message_stop"):
            self.terminal = True
        if kind == "message_start":
            u = event["message"]["usage"]
            self.input = u["input_tokens"] + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            self.output = u.get("output_tokens", 0)
        u = event.get("usage") or event.get("response", {}).get("usage")
        if u:
            if "prompt_tokens" in u:
                self.input, self.output = u["prompt_tokens"], u["completion_tokens"]
            elif "input_tokens" in u and kind != "message_delta":
                self.input = u["input_tokens"] + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            if "output_tokens" in u:
                self.output = u["output_tokens"]

    def result(self):
        return {"input": self.input, "output": self.output} if self.terminal else None


class Gateway:
    def __init__(self, evidence, budget, run, upstream, key, model, token, capture_only=False, observe=None):
        self.evidence, self.budget, self.run = evidence, budget, run
        self.upstream, self.key, self.model, self.token = upstream.rstrip("/"), key, model, token
        self.capture_only, self.observe = capture_only, observe
        self.count = 0
        self.stopped = None
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 60

            def log_message(self, *_):
                pass

            def do_POST(self):
                try:
                    self.handle_request()
                except (BrokenPipeError, ConnectionResetError):
                    owner.stopped = "client disconnected during request"

            def handle_request(self):
                length = int(self.headers.get("content-length", "0"))
                if not 0 < length <= 2_000_000:
                    self.send_error(413)
                    return
                body = json.loads(self.rfile.read(length))
                if self.path == "/observe":
                    if self.headers.get("x-eval-token") != owner.token:
                        self.send_error(403)
                        return
                    if owner.observe:
                        owner.observe(body)
                    self.send_response(204)
                    self.end_headers()
                    return
                credential = self.headers.get("authorization", "").removeprefix("Bearer ") or self.headers.get("x-api-key")
                if credential != owner.token:
                    self.send_error(403)
                    return
                if self.path.split("?")[0] not in ("/v1/chat/completions", "/v1/responses", "/v1/messages"):
                    self.send_error(403, "unmetered endpoint denied")
                    return
                with owner.lock:
                    owner.count += 1
                    number = owner.count
                write_json(owner.evidence / f"request-{number:03d}.json", body)
                if owner.capture_only:
                    owner.stopped = "capture-only: request recorded, no upstream dispatch"
                    self.send_error(403, owner.stopped)
                    return
                try:
                    if owner.stopped:
                        raise LimitReached(owner.stopped)
                    wire, bound, output = owner.prepare(body, self.path)
                    request_id = owner.budget.reserve(owner.run, owner.model, bound, output)
                except (LimitReached, ValueError, KeyError) as error:
                    owner.stopped = str(error)
                    self.send_error(403, owner.stopped)
                    return
                write_json(owner.evidence / f"admitted-{request_id}.json", wire)
                headers = {"Authorization": "Bearer " + owner.key, "x-api-key": owner.key,
                           "Content-Type": "application/json", "Accept-Encoding": "identity"}
                for name in ("anthropic-version", "anthropic-beta"):
                    if self.headers.get(name):
                        headers[name] = self.headers[name]
                request = urllib.request.Request(owner.upstream + self.path.removeprefix("/v1"),
                    data=json.dumps(wire).encode(), headers=headers, method="POST")
                usage = Usage()
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        self.send_response(response.status)
                        self.send_header("Content-Type", response.headers.get("Content-Type", "text/event-stream"))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        with (owner.evidence / f"response-{request_id}.sse").open("wb") as log:
                            for line in response:
                                log.write(line)
                                if line.startswith(b"data:"):
                                    text = line[5:].strip().decode()
                                    usage.accept(text if text == "[DONE]" else json.loads(text))
                                self.wfile.write(line)
                                self.wfile.flush()
                        self.close_connection = True
                except (OSError, ValueError, urllib.error.URLError) as error:
                    owner.stopped = f"upstream/stream failed: {type(error).__name__}"
                    write_json(owner.evidence / f"transport-error-{request_id}.json", {"error": owner.stopped,
                               "status": getattr(error, "code", None)})
                finally:
                    owner.budget.settle(owner.run, request_id, usage.result())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # Settlement must finish before the launcher releases the ledger lock.
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def prepare(self, body, path):
        wire = dict(body)
        if wire.get("model") != self.model:
            raise ValueError(f"unexpected model: {wire.get('model')}")
        if wire.get("previous_response_id") or not wire.get("stream"):
            raise ValueError("only explicit, streamed request histories are metered")
        # Reject non-text input, remote references and hosted tools with separate charges.
        def visit(value):
            if isinstance(value, dict):
                kind = value.get("type", "")
                if isinstance(kind, str) and any(x in kind for x in ("image", "audio", "video", "file", "web_search", "computer")):
                    raise ValueError(f"unpriced input/tool type: {kind}")
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(wire)
        cap = self.budget.plan["request_output_limit"]
        for field in ("max_completion_tokens", "max_tokens", "max_output_tokens"):
            if field in wire and (type(wire[field]) is not int or wire[field] <= 0):
                raise ValueError("invalid output limit")
        if path.startswith("/v1/chat/"):
            if wire.get("reasoning_effort") != "medium":
                raise ValueError("medium effort was not selected")
            limit_field = "max_completion_tokens" if "max_completion_tokens" in wire else "max_tokens"
            cap = min(cap, wire.pop("max_completion_tokens", cap), wire.pop("max_tokens", cap))
            wire[limit_field] = cap
            wire["stream_options"] = {**wire.get("stream_options", {}), "include_usage": True}
        elif path.startswith("/v1/responses"):
            if wire.get("reasoning", {}).get("effort") != "medium":
                raise ValueError("medium effort was not selected")
            cap = min(cap, wire.get("max_output_tokens", cap))
            wire["max_output_tokens"] = cap
        else:
            if wire.get("output_config", {}).get("effort") != "medium":
                raise ValueError("medium effort was not selected")
            cap = min(cap, wire.get("max_tokens", cap))
            wire["max_tokens"] = cap
            wire["model"] = "anthropic/" + self.model
        # Text-only byte bound deliberately overcounts JSON and reserves extra protocol framing.
        # Billing remains API-equivalent: hidden gateway retries/subscription billing are not observable.
        bound = len(json.dumps(wire, ensure_ascii=False).encode()) + 8192
        if type(cap) is not int or cap <= 0:
            raise ValueError("invalid output limit")
        return wire, bound, cap

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        if self.budget and self.budget.data["runs"].get(self.run, {}).get("pending"):
            self.budget.stop("gateway closed with unresolved upstream work; reservations retained")
